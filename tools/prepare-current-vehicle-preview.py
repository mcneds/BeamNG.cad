"""Prepare an isolated, explicitly diagnostic vehicle from a native CAD intake.

The working assembly/project is never overwritten. Suspension points must all
resolve from native mates. Mechanical material, collider and fit checks remain
in the normal vehicle builder. Provisional sheet settings are recorded.
"""
import argparse,copy,json,sys,uuid,shutil
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
import joint_authoring as ja
import joint_inference as ji
from vehicle_templates import frame_mount_plan,TemplateModel,Mechanism

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def support_sites(points):
    points=np.asarray(points,float);a=points[0];b=points[np.argmax(np.linalg.norm(points-a,axis=1))]
    cross=np.linalg.norm(np.cross(points-a,b-a),axis=1);d=points[np.argmax(cross)]
    if max(cross)<1e-8:raise ValueError('Rigid body has no separated non-collinear support sites')
    return np.array([a,b,d]).tolist()

def prepare(intake,output,panel_thickness,panel_density,tab_thickness,tab_density,mount_sites=None,native=None):
    output.mkdir(parents=True,exist_ok=False);p=read(intake);original=copy.deepcopy(p)
    c.write(output/'native-project.json',original)
    w=p['JointWorkspace'];w['Joints']=ja.proposals(w)
    for joint in w['Joints']:
        if not joint.get('Issue'):joint['Status']='approved'
    for row in ji.rows(p):
        for binding in row.get('Bindings',[]):w['Bindings']=[b for b in w['Bindings'] if b['Request']!=binding['Request']]+[binding]
        for anchor in row.get('Anchors',[]):p['Anchors']=[a for a in p['Anchors'] if a['Id']!=anchor['Id']]+[anchor]
    values=ja.resolve_bindings(p);requested=ja.requests(p)
    missing=[v['id'] for v in requested if v['id'] not in values]
    if missing:raise ValueError('Native suspension points missing: '+', '.join(missing))
    assumptions=['Initial CAD integration build: suspension hardpoints come from native mates; mechanical qualification is pending.',
                 'The unsplit rack uses equivalent tie-rod actuators; rack housing/slider internals and steering-wheel rotation are not represented.',
                 'Coilover axial motion is represented; spring-seat free spin is not simulated.',
                 'Unmeasured tire, engine, gear-ratio, damping and attachment-strength parameters use provisional template settings.']
    fixed={};halfshafts={};fixed_shafts=[];audits={};all_meshes={}
    def capture_geometry(comp,group,thickness,density):
        source=Path(group['GeometryDirectory']);geometry=read(source/'geometry.json')
        if comp['MvpRole']=='frame':return geometry
        target=output/'geometry'/group['Id'];target.mkdir(parents=True)
        defaults=[];sheets=[]
        for mesh in geometry['Meshes']:
            shutil.copy2(source/mesh['File'],target/mesh['File'])
            if mesh.get('BodyKind')=='surface':
                if not mesh.get('DensityKgM3'):mesh['DensityKgM3']=density;sheets.append(mesh['Id'])
            elif not mesh.get('MassKg'):
                record=(native or {}).get(mesh['Id'],{});value=record.get('effective_density_kg_m3')
                if value is None:raise ValueError(comp['Name']+': native effective density unavailable for '+mesh['Body'])
                for captured,exported in [('properties','NativeUnitDensityProperties'),('center_assembly','NativeCenterAssembly'),('axes_assembly','NativeAxesAssembly')]:
                    if not np.allclose(record[captured],mesh[exported],atol=1e-12,rtol=1e-8):raise ValueError(comp['Name']+': native property snapshot differs from exported CAD')
                mesh['MassKg']=value*mesh['NativeUnitDensityProperties'][3]
                mesh['MassSource']='Native CAD volume times captured effective document density; no assigned physical material'
                defaults.append(dict(body=mesh['Id'],density_kg_m3=value,native_mass_error=record.get('mass_error')))
        if sheets:assumptions.append(comp['Name']+f': {len(sheets)} surface bodies use provisional {thickness*1000:g} mm thickness and {density:g} kg/m3 density.')
        if defaults:assumptions.append(comp['Name']+': unassigned solid materials use captured SolidWorks effective/default densities; measured component mass and material confirmation required.')
        c.write(target/'geometry.json',geometry);c.write(target/'provisional-properties.json',dict(default_densities=defaults,provisional_surface_bodies=sheets,thickness_m=thickness,density_kg_m3=density,source_geometry=str(source)))
        if (source/'material-snapshot.json').exists():shutil.copy2(source/'material-snapshot.json',target/'material-snapshot.json')
        group['GeometryDirectory']=str(target)
        return geometry
    # Native mass data supplements early high-quality snapshots if needed; only
    # non-frame display captures use these records for physical moments.
    for comp in p['Components']:
        if not comp.get('GeometryDirectory'):raise ValueError('CAD export missing: '+comp['Name'])
        panel=comp['Template']=='panel';thickness=comp.get('Thickness') or (panel_thickness if panel else tab_thickness);density=panel_density if panel else tab_density
        geometry=capture_geometry(comp,comp,thickness,density)
        sheets=[m for m in geometry['Meshes'] if m.get('BodyKind')=='surface']
        if sheets and not comp.get('Thickness'):comp['Thickness']=thickness
        meshes,moments,_=c.read_geometry(comp);all_meshes[comp['Id']]=meshes
        if panel:
            from frame_harness.materials import load_snapshot
            try:load_snapshot(Path(comp['GeometryDirectory'])/'material-snapshot.json',comp['BodyIds'])
            except ValueError:
                comp['ProvisionalElastic']=dict(young_pa=70e9,poisson=.33,reason='Initial diagnostic sheet model; CAD has no complete material assignment')
                assumptions.append(comp['Name']+': provisional sheet elasticity E=70 GPa, Poisson=0.33; not material calibrated.')
            shape=c.suggest(np.concatenate([t for _,t in meshes]),moments[0]);ext=shape['principal_extent_m']
            if ext[2]>.15*ext[1]:
                comp['Method']='alpha_wrap';assumptions.append(comp['Name']+': curved panel uses a coarse wrapped collision envelope; planar flattening is not used.')
        audits[comp['Id']]=dict(name=comp['Name'],mass_kg=moments[0],center_m=moments[1].tolist(),inertia_kg_m2=moments[2].tolist(),bodies=len(meshes))
        role=comp.get('MvpRole','');owner=comp['Id']
        if role in ('engine','cvt','front_diff','rear_diff','rear_final_drive','shaft_carrier'):
            comp['Method']='oriented_box';assumptions.append(comp['Name']+': coarse oriented-box collision envelope for the first integration build; exact native mass moments and detailed visual meshes retained.')
        if role.endswith('_spring_damper'):
            members=[m for m in w['Members'] if m['ComponentId']==owner]
            if len(members)==3 and {m['Kind'] for m in members}=={'housing','shaft','spring'}:
                for member in members:capture_geometry(comp,member,thickness,density)
                comp['AppearanceCoilover']=dict(HousingMount='top',Pieces=[dict(Kind=m['Kind'],GeometryDirectory=m['GeometryDirectory'],BodyIds=m['BodyIds'],Selections=m['Selections']) for m in members])
        moving=role.startswith(('fl_','fr_','rl_','rr_'))
        if role=='frame':continue
        if role.endswith('_halfshaft'):
            ends=[values.get(owner+'.'+end+'_joint') for end in ('inner','outer')]
            if any(v is None for v in ends):raise ValueError(comp['Name']+': native shaft endpoints missing')
            halfshafts[owner]=dict(inner=ends[0],outer=ends[1],corner=role[:2].upper());continue
        if moving:continue
        if role in ('front_propshaft','cvt_output_shaft'):
            placements=[v for v in w['Placements'] if v['ComponentId']==owner]
            if not placements or not all(v['Fixed'] for v in placements):raise ValueError(comp['Name']+': nonfixed shaft needs an articulated chain')
            fixed_shafts.append(owner)
        # Existing fastener positions are retained when this group has them.
        anchors={a['Id']:a for a in p['Anchors']}
        points=[anchors[v['AnchorB']]['Position'] for v in p['Connections'] if anchors[v['AnchorB']]['ComponentId']==owner]
        if len(points)<3:
            xyz=np.concatenate([t.reshape(-1,3) for _,t in meshes]);points=mount_sites[owner] if mount_sites else support_sites(xyz)
            assumptions.append(comp['Name']+': three CAD-derived support sites for initial attachment; physical bolt placement unqualified.')
        fixed[owner]=points
        if comp['Template']!='panel':comp['Template']='bulk'
    definition=dict(kind='vehicle_template',version=1,templates={x['Category']:x['Template'] for x in p['MvpTemplates']},
        hardpoints={corner:{} for corner in ('FL','FR','RL','RR')},parameters=dict(travel_m=.06,steer_degrees=20),
        fixed_mounts=fixed,halfshafts=halfshafts,shafts={},fixed_shafts=fixed_shafts,diagnostic_assumptions=assumptions,
        declaration_source=dict(kind='native_cad_diagnostic',source_project=str(intake),source_fingerprint=c.fingerprint(original)))
    for r in requested:
        corner,key=r['id'].split('.',1);definition['hardpoints'][corner][key]=values[r['id']]
    radii=[];widths=[]
    for corner in definition['hardpoints']:
        comp=next(v for v in p['Components'] if v['MvpRole']==corner.lower()+'_wheel');xyz=np.concatenate([t.reshape(-1,3) for _,t in all_meshes[comp['Id']]])
        points=definition['hardpoints'][corner];hub=np.array(points['hub']);axis=np.array(points['hub_axis'])-hub;axis/=np.linalg.norm(axis)
        distances=xyz-hub;axial=distances@axis;radii.append(float(np.linalg.norm(distances-axial[:,None]*axis,axis=1).max()));widths.append(float(np.ptp(axial)))
    definition['parameters'].update(tire_radius_m=float(np.median(radii)),tire_width_m=float(np.median(widths)))
    checks={corner:Mechanism(TemplateModel(definition),corner).inspect() for corner in definition['hardpoints']}
    # This isolated template compilation deliberately does not claim that the
    # complete native mate graph compiled. Preserve that graph in provenance.
    w['Mode']='legacy';p['TemplateDefinitionPath']=str(output/'template.json')
    p['Anchors']=[];p['Connections']=[]
    p['Identity']=dict(id=uuid.uuid5(uuid.NAMESPACE_URL,str(intake.resolve())).hex,namespace='mochi_cad_preview_20261010')
    c.write(output/'template.json',definition);c.write(output/'project.json',p);c.write(output/'cad-audit.json',audits);c.write(output/'kinematics.json',checks)
    c.write(output/'frame-mounts.json',frame_mount_plan(definition,p['Components']))
    c.write(output/'profile.json',dict(Name='Mochi CAD integration preview',Brand='CAD',Author='ak1di',Description='Actual assigned CAD with provisional hardware properties; diagnostic build',Configuration='CAD first drive',PreviewImage=''))
    print('PREVIEW_READY '+str(output/'project.json'),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('intake',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--panel-thickness-mm',type=float,required=True);parser.add_argument('--panel-density',type=float,required=True)
    parser.add_argument('--tab-thickness-mm',type=float,required=True);parser.add_argument('--tab-density',type=float,required=True)
    parser.add_argument('--mount-sites',type=Path)
    parser.add_argument('--native-properties',type=Path)
    a=parser.parse_args();prepare(a.intake,a.output,a.panel_thickness_mm/1000,a.panel_density,a.tab_thickness_mm/1000,a.tab_density,read(a.mount_sites) if a.mount_sites else None,read(a.native_properties) if a.native_properties else None)
