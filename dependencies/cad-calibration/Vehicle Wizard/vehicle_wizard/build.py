"""Deterministic generation from reviewed component ownership and CAD hardpoints."""
from __future__ import annotations
import copy
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import zipfile
import numpy as np
from .project import CORNERS,sha256,write_json
from .kinematics import inspect_all
from .collada import export_meshes


def expanded(rows):
    defaults={}
    for row in rows[1:]:
        if isinstance(row,dict):defaults.update(row)
        else:
            options=defaults| (row[-1] if isinstance(row[-1],dict) else {})
            yield row[:-1] if isinstance(row[-1],dict) else row,options


class Graph:
    def __init__(self,frame):
        self.part=copy.deepcopy(frame);self.nodes={};self.beams=[];self.groups={};self.edge_set=set()
        self.mass={};self.mounts=[]
        for row,options in expanded(frame['nodes']):
            if options.get('fixed'):raise ValueError('Chassis contains a fixture pin; select an unpinned chassis')
            self.nodes[row[0]]={'pos':np.array(row[1:4]),'options':options|{'group':['frame']}}
        self.frame_ids=list(self.nodes);self.frame_mass=sum(n['options']['nodeWeight'] for n in self.nodes.values())
        self.groups['frame']=self.frame_ids.copy()
        for row,options in expanded(frame['beams']):self.beams.append([*row[:2],options]);self.edge_set.add(tuple(sorted(row[:2])))
        self.original_beam_count=len(self.beams)

    def node(self,name,pos,groups=()):
        if name in self.nodes:raise ValueError('Duplicate node '+name)
        self.nodes[name]={'pos':np.array(pos,dtype=float),'options':{'collision':False,'selfCollision':False,'nodeMaterial':'|NM_METAL','group':list(groups)}}
        for group in groups:self.groups.setdefault(group,[]).append(name)
        return name

    def group(self,name,ids):
        self.groups[name]=list(dict.fromkeys(ids))
        for key in self.groups[name]:
            if name not in self.nodes[key]['options']['group']:self.nodes[key]['options']['group'].append(name)

    def beam(self,a,b,**options):
        edge=tuple(sorted((a,b)))
        if a==b or np.linalg.norm(self.nodes[a]['pos']-self.nodes[b]['pos'])<1e-5:raise ValueError('Zero length structural beam '+str(edge))
        if edge in self.edge_set:return
        self.edge_set.add(edge)
        self.beams.append([a,b,{'beamType':'|NORMAL','beamSpring':250000.,'beamDamp':60.,'beamDeform':80000.,'beamStrength':160000.,'beamPrecompression':1.,'breakGroup':''}|options])

    def rigid(self,ids):
        for a,b in itertools.combinations(ids,2):self.beam(a,b)

    def mount(self,name,pos):
        self.node(name,pos,['frame']);self.mounts.append(name)
        ordered=sorted(self.frame_ids,key=lambda k:np.linalg.norm(self.nodes[k]['pos']-pos))
        supports=[]
        for key in ordered:
            vector=self.nodes[key]['pos']-pos
            if np.linalg.norm(vector)<.002:continue
            candidate=supports+[key]
            vectors=np.array([self.nodes[n]['pos']-pos for n in candidate])
            if len(supports)>=3 or np.linalg.matrix_rank(vectors,tol=1e-4)>len(supports):supports.append(key)
            if len(supports)==4:break
        if len(supports)<4:raise ValueError('Cannot find noncoplanar chassis supports for '+name)
        for key in supports:self.beam(name,key,beamSpring=120000.,beamDamp=35.)
        return name

    def allocate(self,group,mass):
        ids=self.groups.get(group,[])
        if not ids:raise ValueError('No structural group for '+group)
        for key in ids:self.mass[key]=self.mass.get(key,0)+mass/len(ids)

    def finish(self):
        # Added mount mass is borrowed from the frame, preserving total CAD frame mass.
        mount_mass=.12*len(self.mounts)
        if mount_mass>self.frame_mass*.4:raise ValueError('Too many mount nodes for chassis mass')
        for key in self.frame_ids:self.mass[key]=self.mass.get(key,0)+self.nodes[key]['options']['nodeWeight']*(1-mount_mass/self.frame_mass)
        for key in self.mounts:self.mass[key]=self.mass.get(key,0)+.12
        for key,node in self.nodes.items():
            if self.mass.get(key,0)<=0:raise ValueError('Unallocated physical mass at '+key)
            node['options']['nodeWeight']=self.mass[key]
        degree={key:0 for key in self.nodes}
        for a,b,_ in self.beams:degree[a]+=1;degree[b]+=1
        # New template members are numerical rigidifiers, not calibrated material specimens.
        # Budget stiffness across incident beams so tiny mount nodes cannot explode at 2 kHz.
        for a,b,options in self.beams[self.original_beam_count:]:
            if options['beamType']=='|BOUNDED':continue
            cap=min(self.mass[a]/max(1,degree[a]),self.mass[b]/max(1,degree[b]))*(2*math.pi*200)**2
            options['beamSpring']=min(options['beamSpring'],cap)
            reduced=self.mass[a]*self.mass[b]/(self.mass[a]+self.mass[b])
            options['beamDamp']=min(options['beamDamp'],.3*math.sqrt(options['beamSpring']*reduced))
        self.part['nodes']=[['id','posX','posY','posZ']]+[[key,*n['pos'].tolist(),n['options']] for key,n in self.nodes.items()]
        self.part['beams']=[['id1:','id2:']]+self.beams
        # Every structural beam has its own properties; generated wheels start from clean defaults.
        self.part['beams'].append({'beamType':'|NORMAL','beamPrecompression':1,'beamSpring':250000,'beamDamp':60,'beamDeform':80000,'beamStrength':160000,'breakGroup':''})
        return self.part


def component_group(component,key=None):
    role=component['role'];corner=component['corner']
    if role=='frame':return 'frame'
    if role in ('engine','cvt'):return role
    if role in ('fixed_accessory','differential','shaft'):return key or component.get('attachment_group','frame')
    if not corner:raise ValueError(component['name']+': assign a suspension corner')
    if role=='wheel':return 'rim_'+corner
    if role=='tire':return 'tire_'+corner
    if role=='locating_link':return component.get('link_group') or corner+'_link_0'
    return corner+'_'+role


def make_structure(project,checks):
    source=json.loads(Path(project.data['frame']).read_text(encoding='utf-8'))
    mains=[p for p in source.values() if p.get('slotType')=='main']
    if len(mains)!=1:raise ValueError('Select a chassis with exactly one main part')
    graph=Graph(mains[0]);part=graph.part;p=project.data['parameters'].copy();hydros=[];wheels=[];corners={}
    for role in ('engine','cvt'):
        assigned_mass=sum(c['mass_kg'] for c in project.data['components'].values() if c['role']==role and c['meshes'])
        if assigned_mass:p[role+'_mass_kg']=assigned_mass
    # Prototype suspension mass defaults are explicit assumptions, overridden by assigned components.
    masses={}
    for c in CORNERS:
        masses.update({c+'_upright':3.,c+'_upper_arm':1.5,c+'_lower_arm':2.5,c+'_trailing_arm':5.,
                       c+'_shock_body':1.,c+'_shock_rod':1.,c+'_tie_rod':.4})
    assigned={}
    objects={o['id']:o for o in project.index()['objects']}
    for key,comp in project.data['components'].items():
        if not comp['meshes'] or comp['role'] in ('ignore','frame','wheel','tire','engine','cvt'):continue
        group=component_group(comp,key);assigned[group]=assigned.get(group,0)+comp['mass_kg']
        if comp['role'] in ('fixed_accessory','differential','shaft'):
            from .project import transform
            bounds=[]
            for mesh in comp['meshes']:
                lo,hi=objects[mesh]['bounds'];bounds.extend(transform(list(itertools.product(*zip(lo,hi))),project.object_transform(mesh)))
            center=np.asarray(bounds).mean(axis=0);ids=[]
            for i,offset in enumerate(((1,1,1),(-1,-1,1),(-1,1,-1),(1,-1,-1))):ids.append(graph.mount(key+f'_{i}',center+np.array(offset)*.04))
            graph.rigid(ids);graph.group(group,ids)
    masses.update(assigned)
    attached_mass=sum(c['mass_kg'] for c in project.data['components'].values() if c['meshes'] and c['role'] in ('fixed_accessory','differential','shaft'))
    total_sprung=graph.frame_mass+p['engine_mass_kg']+p['cvt_mass_kg']+p['ballast_kg']+attached_mass
    for c in CORNERS:
        pts=project.corner_points(c);ids={};front=c.startswith('F');info=checks[c]
        mounts=['upper_inner_front','upper_inner_rear','lower_inner_front','lower_inner_rear','tie_inner','shock_top'] if front else ['trailing_pivot','shock_top']
        for role,point in pts.items():
            if role in ('hub_axis','hub'):continue
            ids[role]=graph.mount(c+'_'+role,point) if role in mounts else graph.node(c+'_'+role,point)
        axis=pts['hub_axis']-pts['hub'];axis/=np.linalg.norm(axis)
        if axis[0]<0:axis*=-1
        ids['axis_in']=graph.node(c+'_axis_in',pts['hub']-axis*.075)
        ids['axis_out']=graph.node(c+'_axis_out',pts['hub']+axis*.075)
        if front:
            for arm in ('upper','lower'):
                armids=[ids[arm+'_inner_front'],ids[arm+'_inner_rear'],ids[arm+'_ball']]
                if arm=='lower':armids.append(ids['shock_bottom'])
                # A tetrahedron avoids a planar arm folding in its own plane.
                coords=np.array([graph.nodes[k]['pos'] for k in armids[:3]]);normal=np.cross(coords[1]-coords[0],coords[2]-coords[0]);normal/=np.linalg.norm(normal)
                armids.append(graph.node(c+'_'+arm+'_brace',coords.mean(axis=0)+normal*.035))
                graph.rigid(armids);graph.group(c+'_'+arm+'_arm',armids)
            upright=[ids[k] for k in ('upper_ball','lower_ball','tie_outer','axis_in','axis_out')]
            graph.rigid(upright);graph.group(c+'_upright',upright)
            graph.group(c+'_tie_rod',[ids['tie_inner'],ids['tie_outer']])
            tie=float(np.linalg.norm(pts['tie_inner']-pts['tie_outer']))
            hydros.append([ids['tie_inner'],ids['tie_outer'],{'inputSource':'steering_input','inRate':2,'outRate':2,
                'factor':-info['steer_length_m']/tie,'beamSpring':200000,'beamDamp':50,'beamDeform':80000,'beamStrength':160000}])
            torque_arm=ids['lower_ball']
        else:
            rigid=[ids[k] for k in ('trailing_pivot','shock_bottom','axis_in','axis_out')]
            for i,link in enumerate(project.data['corners'][c]['links']):
                inner=graph.mount(c+f'_link_{i}_inner',project.point(link['inner']))
                outer=graph.node(c+f'_link_{i}_outer',project.point(link['outer']));rigid.append(outer)
                graph.beam(inner,outer);group=c+f'_link_{i}';graph.group(group,[inner,outer]);masses.setdefault(group,.6)
            graph.rigid(rigid);graph.group(c+'_trailing_arm',rigid);graph.group(c+'_upright',rigid)
            torque_arm=ids['shock_bottom']
        graph.group(c+'_shock_body',[ids['shock_top'],ids['shock_bottom']]);graph.group(c+'_shock_rod',[ids['shock_top'],ids['shock_bottom']])
        ratio=info['motion_ratio'];sprung=total_sprung/4;spring=sprung*(2*math.pi*p['frequency_hz'])**2/ratio**2
        damping=2*p['damping_ratio']*math.sqrt(spring*sprung)/ratio
        length=float(np.linalg.norm(pts['shock_top']-pts['shock_bottom']));preload=sprung*9.81/ratio/spring
        graph.beam(ids['shock_top'],ids['shock_bottom'],beamType='|BOUNDED',beamSpring=spring,beamDamp=damping,
                   beamPrecompression=1+preload/length,beamLongBound=p['travel_m']*ratio/2/length,
                   beamShortBound=p['travel_m']*ratio/2/length,beamLimitSpring=150000,beamLimitDamp=250)
        wheel_mass=sum(comp['mass_kg'] for comp in project.data['components'].values() if comp['corner']==c and comp['role'] in ('wheel','tire') and comp['meshes']) or p['wheel_mass_kg']
        w={'hubRadius':p['rim_radius_m'],'radius':p['tire_radius_m'],'hubWidth':p['tire_width_m']*.85,'tireWidth':p['tire_width_m'],
           'beamSpring':100000,'beamDamp':10,'beamDeform':50000,'beamStrength':100000,'beamPrecompression':1,
           'tireSupportBeamSpring':100000,'tireSupportBeamDamp':10,
           'numRays':16,'hasTire':True,'enableHubcaps':False,'hubNodeWeight':wheel_mass*.45/32,'nodeWeight':wheel_mass*.55/32,
           'hubTreadBeamSpring':-.7,'hubPeripheryBeamSpring':-.7,'hubSideBeamSpring':-.7,'hubReinfBeamSpring':-.7,
           'hubTreadBeamDamp':-1,'hubPeripheryBeamDamp':-1,'hubSideBeamDamp':-1,'hubReinfBeamDamp':-1,'hubBeamDeform':40000,'hubBeamStrength':80000,
           'wheelSideBeamSpring':p['tire_pressure_psi']*850,'wheelSideBeamDamp':8,
           'wheelSideBeamSpringExpansion':125000,'wheelSideBeamDampExpansion':8,
           'wheelTreadBeamSpring':60000,'wheelTreadBeamDamp':12,'wheelPeripheryBeamSpring':45000,'wheelPeripheryBeamDamp':10,
           'wheelSideBeamDeform':20000,'wheelSideBeamStrength':50000,'wheelTreadBeamDeform':20000,'wheelTreadBeamStrength':50000,
           'wheelPeripheryBeamDeform':40000,'wheelPeripheryBeamStrength':60000,
           'pressurePSI':p['tire_pressure_psi'],'nodeMaterial':'|NM_RUBBER','frictionCoef':1.0,'slidingFrictionCoef':.95,
           'triangleCollision':False,'selfCollision':False,'collision':True,'brakeTorque':p['brake_torque_nm'],
           'parkingTorque':p['brake_torque_nm'] if not front else 0,'enableABS':False}
        wheels.append([c,'rim_'+c,'tire_'+c,ids['axis_in'],ids['axis_out'],9999,torque_arm,1,w])
        corners[c]={'nodes':ids,'wheel_mass_kg':wheel_mass,'spring_n_m':spring,'damper_ns_m':damping,'motion_ratio':ratio}
    for role,size in [('engine',.12),('cvt',.075)]:
        center=project.point(role+'_center');ids=[]
        for i,offset in enumerate(((1,1,1),(-1,-1,1),(-1,1,-1),(1,-1,-1))):ids.append(graph.node(role+str(i),center+np.array(offset)*size,[role]))
        graph.rigid(ids);graph.allocate(role,p[role+'_mass_kg'])
        if role=='engine':
            for i in range(1,4):
                mount=graph.mount('engine_mount'+str(i),project.point('engine_mount_'+str(i)))
                for key in ids:graph.beam(mount,key,beamSpring=150000,beamDamp=70)
        else:
            for a in ids:
                for b in graph.groups['engine']:graph.beam(a,b)
    for group,mass in masses.items():
        if group in graph.groups:graph.allocate(group,mass)
    if p['ballast_kg']:graph.allocate('frame',p['ballast_kg'])
    part=graph.finish();part.pop('flexbodies',None);part.pop('slots',None)
    part['information']={'authors':'BeamNG CAD guided wizard','name':project.data['name'],'value':10000}
    part['hydros']=[['id1:','id2:']]+hydros
    part['pressureWheels']=[['name','hubGroup','group','node1:','node2:','nodeS','nodeArm:','wheelDir']]+wheels
    part['controller']=[['fileName'],['vehicleController',{}],['driveModes',{'name':'driveSelector'}]]
    part['driveSelector']={'enabledModes':['rwd','4wd'],'defaultMode':'rwd','modes':{}}
    for mode,title,state in [('rwd','Rear wheel drive','disconnected'),('4wd','Four wheel drive','connected')]:
        part['driveSelector']['modes'][mode]={'name':title,'order':0 if mode=='rwd' else 1,
            'settings':[['type'],['powertrainDeviceMode',{'deviceName':'frontShaft','mode':state}],
                        ['simpleControlButton',{'buttonId':'driveSelector','uiName':title,'icon':'powertrain_shaft_connected'}]]}
    part['powertrain']=[['type','name','inputName','inputIndex'],['combustionEngine','mainEngine','dummy',0],
        ['centrifugalClutch','clutch','mainEngine',1],['cvtGearbox','gearbox','clutch',1],
        ['differential','transfercase','gearbox',1,{'diffType':'locked','lockTorque':4000,'defaultVirtualInertia':10}],
        ['shaft','frontShaft','transfercase',2,{'canDisconnect':True,'isDisconnected':True}]]
    for axle,source,port in [('R','transfercase',1),('F','frontShaft',1)]:
        part['powertrain'].append(['differential','diff'+axle,source,port,{'diffType':p['front_diff' if axle=='F' else 'rear_diff'],'gearRatio':p['final_drive']}])
        for i,side in enumerate('LR',1):part['powertrain'].append(['shaft','axle'+axle+side,'diff'+axle,i,{'connectedWheel':axle+side}])
    torque=p['engine_power_kw']*1000/(p['engine_peak_rpm']*math.pi/30)
    part['mainEngine']={'torque':[['rpm','torque'],[0,0],[p['idle_rpm'],torque*.8],[p['engine_peak_rpm'],torque],[p['max_rpm'],torque*.7]],
        'idleRPM':p['idle_rpm'],'maxRPM':p['max_rpm'],'inertia':.15,'friction':1.5,'dynamicFriction':.005,'engineBrakeTorque':8,
        'burnEfficiency':.3,'energyStorage':'fuelTank','requiredEnergyType':'gasoline','thermalsEnabled':False,
        'torqueReactionNodes:':['engine0','engine1','engine2'],'engineNode':'engine0','starterTorque':35,'starterMaxRPM':1500}
    part['clutch']={'engageRPMStart':p['clutch_start_rpm'],'engageRPMEnd':p['clutch_full_rpm'],'lockTorque':torque*3,'thermalsEnabled':False}
    part['gearbox']={'minGearRatio':p['cvt_min'],'maxGearRatio':p['cvt_max'],'friction':.5,'parkLockTorque':2500,'gearboxNode:':['cvt0']}
    part['vehicleController']={'automaticModes':'PRND','cvtHighRPM':p['engine_peak_rpm'],'cvtLowRPM':p['clutch_full_rpm'],
        'cvtAggression':.2,'cvtGearRatioSmoothingIn':3,'cvtGearRatioSmoothingOut':1,'cvtTargetAVSmoothingIn':1,'cvtTargetAVSmoothingOut':1}
    part['energyStorage']=[['type','name'],['fuelTank','fuelTank']]
    part['fuelTank']={'energyType':'gasoline','fuelCapacity':p['fuel_liters'],'startingFuelCapacity':p['fuel_liters'],'fuel':{'fuelLiquidDensity':.75}}
    return graph,part,corners


def build_vehicle(project,progress=print,cancel=None):
    errors=project.validate(for_build=True)
    if errors:raise ValueError('\n'.join(errors))
    if sha256(project.data['assembly'])!=project.data['assembly_sha256']:raise ValueError('Assembly changed on disk; reimport before building')
    checks=inspect_all(project);fingerprint=project.fingerprint();model=project.data['model']
    target=project.root/'builds'/fingerprint[:16];working=target.with_name(target.name+'.working')
    if target.exists():
        from frame_harness.vehicle import intake
        intake(target/'manifest.json')
        project.data['last_build']=str(target/'manifest.json');project.save();return target/'manifest.json'
    if working.exists():
        if not working.resolve().is_relative_to((project.root/'builds').resolve()):raise ValueError('Unsafe build folder')
        shutil.rmtree(working)
    folder=working/'vehicles'/model;folder.mkdir(parents=True)
    progress('Checking rigid link travel and generating the node/beam graph')
    graph,part,corners=make_structure(project,checks)
    records=export_meshes(project,folder/(model+'.dae'),progress,cancel)
    material=model+'_metal'
    write_json(folder/'main.materials.json',{material:{'name':material,'mapTo':material,'class':'Material','Stages':[{'baseColorFactor':[.45,.48,.52,1],'metallicFactor':.25,'roughnessFactor':.65}], 'version':1.5}})
    part['flexbodies']=[['mesh','[group]:','nonFlexMaterials']]
    for mesh,key in records:
        component=project.data['components'][key];group=component_group(component,key)
        if component['role'] in ('tie_rod','shock_body','shock_rod','locating_link'):
            # Two endpoints alone cannot provide a volumetric flexbody binding basis.
            # Add nearby existing anchors to skinning only; no extra mass or constraints.
            ids=graph.groups[group].copy();center=np.mean([graph.nodes[n]['pos'] for n in ids],axis=0)
            candidates=[n for n in graph.nodes if n.startswith(component['corner']+'_') or n in graph.frame_ids]
            for name in sorted(candidates,key=lambda n:np.linalg.norm(graph.nodes[n]['pos']-center)):
                points=np.array([graph.nodes[n]['pos'] for n in ids])
                rank=np.linalg.matrix_rank(points-points[0],tol=1e-6)
                if rank==3:break
                if name in ids:continue
                trial=np.array([*points,graph.nodes[name]['pos']])
                if np.linalg.matrix_rank(trial-trial[0],tol=1e-6)>rank:ids.append(name)
            if np.linalg.matrix_rank(np.array([graph.nodes[n]['pos'] for n in ids])-graph.nodes[ids[0]]['pos'],tol=1e-6)<3:raise ValueError(component['name']+': cannot find a volumetric flexbody binding')
            graph.group(group,ids)
        part['flexbodies'].append([mesh,[group],[]])
    write_json(folder/(model+'.jbeam'),{model:part})
    write_json(folder/'base.pc',{'format':2,'model':model,'parts':{'main':model},'vars':{}})
    write_json(folder/'info.json',{'Name':project.data['name'],'Brand':'BeamNG CAD','Author':'Guided Vehicle Wizard','Type':'Car','default_pc':'base'})
    write_json(folder/'info_base.json',{'Configuration':'Prototype - provisional hardware','Description':'Front double wishbone, rear trailing arms and locating links; selectable RWD/4WD. Generated from a reviewed guided project.'})
    write_json(working/'project.snapshot.json',project.data)
    write_json(working/'kinematics.json',checks)
    nodes={k:{'position':v['pos'].tolist(),'mass_kg':v['options']['nodeWeight']} for k,v in graph.nodes.items()}
    manifest={'version':1,'kind':'exported_vehicle','model':model,'main_part':model,'name':project.data['name'],'config':'base.pc',
        'main_jbeam':model+'.jbeam','chassis_nodes':graph.frame_ids,
        'project_fingerprint':fingerprint,'assembly_sha256':project.data['assembly_sha256'],'frame_sha256':sha256(project.data['frame']),
        'vehicle_directory':'vehicles/'+model,'nodes':nodes,'explicit_beams':len(graph.beams),'wheels':corners,
        'expected_wheel_names':list(CORNERS),'allows_generated_wheel_graph':True,'fixed_nodes':[],
        'expected_dry_mass_kg':sum(n['mass_kg'] for n in nodes.values())+sum(v['wheel_mass_kg'] for v in corners.values()),
        'limitations':['Prototype hardware assumptions; not fracture-qualified.','Mesh clipping and self-contact require visual review.'],
        'files':{str(f.relative_to(working)).replace('\\','/'):sha256(f) for f in folder.iterdir() if f.is_file()}}
    reference=part['refNodes'][1][0];min_z=min(project.corner_points(c)['hub'][2]-project.data['parameters']['tire_radius_m'] for c in CORNERS)
    manifest['spawn_z']=.06+nodes[reference]['position'][2]-min_z
    write_json(working/'manifest.json',manifest);working.rename(target)
    project.data['last_build']=str(target/'manifest.json');project.save();progress('Build saved: '+str(target))
    return target/'manifest.json'


def install_build(manifest_path,mods_path):
    manifest_path=Path(manifest_path);m=json.loads(manifest_path.read_text());root=manifest_path.parent
    for relative,digest in m['files'].items():
        file=(root/relative).resolve()
        if not file.is_relative_to(root.resolve()) or sha256(file)!=digest:raise ValueError('Build changed or invalid path: '+relative)
    destination=Path(mods_path)/(m['model']+'.zip');destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        backup=destination.with_suffix('.zip.previous');shutil.copy2(destination,backup)
    temporary=destination.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
        for relative in m['files']:archive.write(root/relative,relative)
    temporary.replace(destination);return destination
