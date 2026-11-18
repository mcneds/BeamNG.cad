"""Explicit legacy-to-graph adapter. Missing CAD axes remain repair requests."""
import copy
from driveline import settings


def from_project(project):
    from vehicle_drivetrain import generate
    from mvp_inventory import configuration
    import json
    from pathlib import Path
    catalog=json.loads(Path(__file__).with_name('template_catalog.json').read_text())
    selected,_,_=configuration(catalog,project)
    params=settings(project.get('JointWorkspace',{}).get('Parameters'))
    part,_=generate(selected['drivetrain']['id'],params,['a','b','c'],'d')
    roles={}
    for c in project['Components']:roles.setdefault(c.get('MvpRole'),[]).append(c['Id'])
    def owner(role):
        values=roles.get(role,[])
        if len(values)!=1:raise ValueError('Preset needs exactly one '+role+' CAD owner; use an empty graph for a new arrangement')
        return values[0]
    rear=owner('rear_final_drive' if selected['drivetrain']['id']=='cvt_rear_front_output' else 'rear_diff')
    bindings={b['Request']:b for b in project.get('JointWorkspace',{}).get('Bindings',[])}
    old_definition={}
    old_path=Path(project.get('TemplateDefinitionPath') or '')
    if old_path.is_file():old_definition=json.loads(old_path.read_text(encoding='utf-8-sig'))
    if old_definition.get('fixed_shafts'):raise ValueError('This definition uses explicitly fixed shaft bodies. Preserve those mounts and author their ideal device ports explicitly; no articulated conversion is inferred.')
    graph=dict(version=2,devices=[],endpoints=[],shafts=[],connections=[])
    def endpoint(identity,component,binding=None):
        e=dict(id=identity,name=identity,component=component)
        if binding:
            if binding.get('JointId'):e['joint']=binding['JointId']
            elif binding.get('AnchorId'):e['anchor']=binding['AnchorId']
        graph['endpoints'].append(e);return identity
    def link(a,b,kind):
        graph['connections'].append(dict(id='link_'+str(len(graph['connections'])),name='Connection',a=a,b=b,kind=kind,travel=0.))
    type_map={'combustionEngine':'engine','centrifugalClutch':'clutch','cvtGearbox':'cvt','shaft':'reduction','differential':'differential','splitShaft':'splitter'}
    rows={r[1]:r for r in part['powertrain'][1:] if r[1]!='frontPropshaft'}
    for name,row in rows.items():
        wheel=name[4:] if name.startswith('axle') else None
        component=owner(wheel.lower()+'_wheel') if wheel else owner('engine') if name=='mainEngine' else owner('cvt') if name in ('clutch','gearbox') else owner('front_diff') if name=='frontDifferential' else rear
        kind='wheel' if wheel else type_map[row[0]]
        numeric={k:v for k,v in row[4].items() if type(v) in (float,int)} if len(row)>4 else {}
        if kind=='cvt':numeric={k:v for k,v in part['gearbox'].items() if k in ('minGearRatio','maxGearRatio','dynamicFriction','parkLockTorque')}
        if kind=='clutch':numeric={k:v for k,v in part['clutch'].items() if type(v) in (float,int)}
        d=dict(id=name,name=name,type=kind,component=component,parameters=numeric,ports=[])
        if wheel:d['wheel']=wheel
        for direction,count in (('input',0 if kind=='engine' else 1),('output',0 if wheel else 2 if kind in ('differential','splitter') else 1)):
            for i in range(1,count+1):
                key=name+'_'+direction+str(i);e=endpoint(key,component)
                d['ports'].append(dict(id=key,name=direction+' '+str(i),direction=direction,index=i,endpoint=e))
        graph['devices'].append(d)
    for name,row in rows.items():
        if name=='mainEngine':continue
        parent=row[2];index=row[3]
        if parent=='frontPropshaft':parent='frontOutputGear';index=1
        a=parent+'_output'+str(index);b=name+'_input1'
        role=(name[4:].lower()+'_halfshaft') if name.startswith('axle') else 'front_propshaft' if name=='frontDifferential' else 'cvt_output_shaft' if name=='rearReduction' else None
        sections=roles.get(role,[]) if role else []
        if len(sections)>1:
            chain=next((v for v in old_definition.get('shaft_chains',{}).values() if v.get('role')==role),None)
            if not chain or {s['component'] for s in chain['segments']}!=set(sections):
                raise ValueError(role+': provide the reviewed shaft_chains declaration; the adapter never uses list order')
            import numpy as np
            previous=a
            for i,segment in enumerate(chain['segments']):
                component=segment['component'];sa='cad_'+component+'_end_a';sb='cad_'+component+'_end_b'
                pa=np.array(chain['joints'][i]['position'],float);pb=np.array(chain['joints'][i+1]['position'],float);axis=pb-pa
                if np.linalg.norm(axis)<.001:raise ValueError(component+': collapsed reviewed shaft section')
                axis/=np.linalg.norm(axis)
                for identity,position in ((sa,pa),(sb,pb)):
                    endpoint(identity,component);graph['endpoints'][-1].update(position=position.tolist(),axis=axis.tolist())
                graph['shafts'].append(dict(id='section_'+str(len(graph['shafts'])),name=component,component=component,a=sa,b=sb,legacy_plunge_m=segment['plunge_m']))
                link(previous,sa,'spherical')
                if i:
                    carrier=chain['joints'][i]['parent_component'];site='carrier_'+component
                    endpoint(site,carrier);graph['endpoints'][-1].update(position=pa.tolist(),axis=axis.tolist());link(sa,site,'bearing')
                previous=sb
            link(previous,b,'spherical')
            continue
        if sections:
            component=sections[0];sa='cad_'+component+'_end_a';sb='cad_'+component+'_end_b'
            suffixes=('inner_joint','outer_joint') if role.endswith('_halfshaft') else ('input_joint','output_joint')
            endpoint(sa,component,bindings.get(component+'.'+suffixes[0]));endpoint(sb,component,bindings.get(component+'.'+suffixes[1]))
            prior=(old_definition.get('halfshafts',{})|old_definition.get('shafts',{})).get(component,{})
            if 'inner' in prior and 'outer' in prior:
                import numpy as np
                first,last=(prior['outer'],prior['inner']) if role=='front_propshaft' else (prior['inner'],prior['outer'])
                axis=np.asarray(last)-first
                if np.linalg.norm(axis)<.001:raise ValueError(component+': collapsed shaft')
                axis=(axis/np.linalg.norm(axis)).tolist()
                for end,position in ((sa,first),(sb,last)):
                    e=next(e for e in graph['endpoints'] if e['id']==end)
                    if not e.get('anchor') and not e.get('joint'):e.update(position=position,axis=axis)
            graph['shafts'].append(dict(id='section_'+str(len(graph['shafts'])),name=role,component=component,a=sa,b=sb,
                representation='ideal',half_travel_m=float(prior.get('plunge_m',.06)),legacy_plunge_m=float(prior.get('plunge_m',.06))))
            link(a,sa,'spherical');link(sb,b,'spherical')
        else:
            ca=next(e['component'] for e in graph['endpoints'] if e['id']==a);cb=next(e['component'] for e in graph['endpoints'] if e['id']==b)
            link(a,b,'internal' if ca==cb else 'direct')
    return graph
