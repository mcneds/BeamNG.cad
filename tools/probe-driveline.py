"""Build an analytic graph fixture and optionally record isolated BeamNG pilots.

This is synthetic engineering evidence, never a calibrated CAD vehicle or a
qualification receipt. No installed mod, source CAD or saved project is changed.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from test_driveline import physical_fixture
from vehicle_templates import generate
from frame_harness.build import write_json,beam_table
import components as c


def build(output,floating=True,model_kind="floating",match_manifest=None):
    def mechanical_scope(spec,components,moments):
        omitted={c['Id'] for c in components if c['Template']=='panel' or c.get('MvpRole')=='accessory'}
        components[:]=[c for c in components if c['Id'] not in omitted]
        for owner in omitted:spec['fixed_mounts'].pop(owner,None)
        spec['components']=[c for c in spec.get('components',[]) if c['id'] not in omitted]
    if model_kind=='legacy':
        from test_vehicle_template_graph import fixture
        project,frame,spec,cad=fixture('primary',mechanical_scope)
    else:
        project,frame,spec,cad=physical_fixture(mechanical_scope)
    extra={}
    # The algebraic unit fixture has no vehicle reference frame. Supply the
    # known synthetic box's +Y rear / +X left / +Z up nodes explicitly, as a
    # calibrated exporter does, rather than letting the engine choose them.
    frame['refNodes']=[['ref:','back:','left:','up:'],['0','2','4','1']]
    # The unit fixture deliberately preserves tiny CAD-only support masses to
    # test exact accounting. A native pilot uses production conditioning and
    # reports its additional numerical mass separately.
    spec['parameters'].update(loaded_node_mass_policy='reported_ballast',assembled_rigid_conditioning=True)
    # Explicit synthetic chassis: the 10 kg unit-test frame is intended for
    # algebraic mass checks, not to support a complete native vehicle. Scale its
    # analytic mass and axial stiffness together; this is never real CAD evidence.
    chassis_scale=16.
    original_frame=next(v for v in project['Components'] if v['Id']=='frame')
    mass,center,inertia=cad(original_frame)[1];extra['frame']=(mass*chassis_scale,center,inertia*chassis_scale)
    for row in frame['nodes'][1:]:row[-1]['nodeWeight']*=chassis_scale
    for row in frame['beams'][1:]:
        row[-1]['beamSpring']*=chassis_scale;row[-1]['beamDamp']*=chassis_scale
    if match_manifest:
        baseline=json.loads(match_manifest.read_text())
        keys=('spring_n_m','damper_ns_m','spring_preload_n')
        spec['parameters']['suspension_physical_settings']={corner:{k:w[k] for k in keys} for corner,w in baseline['wheels'].items()}
    drive=spec.get('driveline',dict(shafts=[]))
    if model_kind in ('ideal','slider'):
        drive['version']=2
        for section in drive['shafts']:
            if model_kind=='slider' and section['component'].endswith('_halfshaft'):continue
            section.update(representation='ideal',half_travel_m=.06 if section['component'].endswith('_halfshaft') else .03)

    # All three comparison variants use the same analytic halfshaft moments.
    # Splitting a uniform rod into two halves preserves its assembled tensor
    # by the parallel-axis theorem. The old and ideal generators lump its mass.
    if model_kind in ('legacy','ideal','slider'):
        for comp in project['Components']:
            owner=comp['Id']
            if not owner.endswith('_halfshaft'):continue
            item=next(item for item in spec['components'] if item['id']==owner)['primitives'][0]
            a,b=np.array(item['a']),np.array(item['b'])
            delta=b-a;mass=cad(comp)[1][0]
            tensor=mass*((delta@delta/12+.0002)*np.eye(3)-np.outer(delta,delta)/12)
            extra[owner]=(mass,(a+b)/2,tensor)
    selected=[s for s in drive['shafts'] if s['component'].endswith('_halfshaft') or floating and s['component']=='front_propshaft']
    if model_kind in ('legacy','ideal'):selected=[]
    for section in selected:
        endpoints={e['id']:e for e in drive['endpoints']};a,b=[np.array(endpoints[section[k]]['position'],float) for k in ('a','b')]
        articulated=section['component']=='front_propshaft'
        # Start the ideal floating bend at its gravity minimum. A sideways
        # bend is an undamped pendulum around the line between the housings;
        # it is useful transient evidence, but cannot promise a settled rest
        # state without adding a rotational loss model that we do not have.
        # Keep the nonzero bend and all existing acceptance thresholds.
        bend=np.zeros(3)
        if articulated:
            line=b-a;line/=np.linalg.norm(line)
            down=np.array([0.,0.,-1.]);down-=line*(down@line)
            if np.linalg.norm(down)<1e-8:raise ValueError('Floating pilot needs a nonvertical housing axis')
            bend=.04*down/np.linalg.norm(down)
        center=(a+b)/2+bend;old=next(v for v in project['Components'] if v['Id']==section['component']);mass=cad(old)[1][0]
        project['Components'].remove(old);drive['shafts'].remove(section)
        new=[]
        for i,(p,q) in enumerate(((a,center),(center,b))):
            owner=section['component']+'_section_'+str(i);project['Components'].append(dict(Id=owner,Name=owner,MvpRole='',Template='bulk'))
            ea,eb=owner+'_a',owner+'_b';axis=q-p;axis/=np.linalg.norm(axis)
            drive['endpoints'].extend([dict(id=ea,name=ea,component=owner,position=p.tolist(),axis=axis.tolist()),dict(id=eb,name=eb,component=owner,position=q.tolist(),axis=axis.tolist())])
            drive['shafts'].append(dict(id=owner,component=owner,a=ea,b=eb));new.append((ea,eb))
            length=np.linalg.norm(q-p);u=axis;inertia=mass/2*((length**2/12+.0002)*np.eye(3)-(length**2/12)*np.outer(u,u))
            extra[owner]=(mass/2,(p+q)/2,inertia)
        for link in drive['connections']:
            for key in ('a','b'):
                if link[key]==section['a']:link[key]=new[0][0]
                elif link[key]==section['b']:link[key]=new[1][1]
        drive['endpoints']=[e for e in drive['endpoints'] if e['id'] not in (section['a'],section['b'])]
        drive['connections'].append(dict(id='joint_'+section['id'],a=new[0][1],b=new[1][0],kind='spherical' if articulated else 'slider',travel=0 if articulated else .06))
    def geometry(comp):return ([],extra[comp['Id']],{}) if comp['Id'] in extra else cad(comp)
    with patch.object(c,'read_geometry',side_effect=geometry):
        graph,part,wheels,_,contract,_,_=generate(project,frame,spec)
    model='driveline_graph_probe';vehicle=output/'vehicles'/model;vehicle.mkdir(parents=True)
    part.update(slotType='main',information=dict(name='Synthetic driveline graph diagnostic',authors='BeamNG CAD',value=0))
    # Physics-only fixture has no mesh source. Do not claim rendered coverage.
    part.pop('flexbodies',None);part.pop('props',None)
    write_json(vehicle/'main.jbeam',{model:part});write_json(vehicle/'base.pc',dict(format=2,parts={model:model}))
    nodes={n:dict(position=v['position'],mass_kg=v['options']['nodeWeight'],component=graph.owners[n]) for n,v in graph.nodes.items()}
    ref=part['refNodes'][1][0]
    minimum=min(p['hub'][2]-spec.get('parameters',{}).get('tire_radius_m',.28) for p in spec['hardpoints'].values())
    spawn_z=.06+nodes[ref]['position'][2]-minimum
    manifest=dict(kind='exported_vehicle',version=1,model=model,main_part=model,main_jbeam='main.jbeam',config='base.pc',
        vehicle_directory='vehicles/'+model,nodes=nodes,chassis_nodes=graph.frame_ids,fixed_nodes=[],wheels=wheels,
        expected_wheel_names=list(wheels),allows_generated_wheel_graph=True,spawn_z=spawn_z,
        expected_dry_mass_kg=sum(v['mass_kg'] for v in nodes.values())+sum(w['wheel_mass_kg'] for w in wheels.values()),
        explicit_beams=len(beam_table(part)),device_contract=contract,template_definition=spec,component_roles={v['Id']:v['MvpRole'] for v in project['Components']},
        mass_allocations=graph.mass_allocations,joints=graph.joints,mounts=graph.mounts,shaft_chains={},driveline_physics=getattr(graph,'driveline_physics',{}),numerical_mass=graph.numerical_mass,probe_model=model_kind,
        component_meshes={},required_controllers={},qualification_status='diagnostic_only',
        limitations=['Analytic fake CAD mass/geometry; floating-shaft engineering fixture, not a calibrated or physically qualified vehicle.',
                     'Mechanical scope only: optional panels and accessories are omitted. Their attachment/settling acceptance is separate.',
                     'Only the floating pilot includes a bent propshaft. Floating bend starts at its gravity minimum. Ideal spherical joints have no rotational loss model; arbitrary sideways bends may swing indefinitely.'])
    manifest['files']={p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in vehicle.iterdir()}
    write_json(output/'manifest.json',manifest)
    return output/'manifest.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--profile',type=Path)
    parser.add_argument('--native',action='store_true');parser.add_argument('--supported-only',action='store_true')
    parser.add_argument('--match-suspension',type=Path,help='Reuse the four corner hardware settings from a generated pilot manifest')
    parser.add_argument('--shaft-model',choices=['floating','legacy','ideal','slider'],default='floating')
    parser.add_argument('--scenarios',nargs='+',choices=['settle','supported','articulation'],default=['settle','supported','articulation']);args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False);manifest=build(output,not args.supported_only and args.shaft_model=='floating',args.shaft_model,args.match_suspension)
    if not args.native:return
    if not args.profile:parser.error('--native requires a dedicated --profile')
    from frame_harness.models import HarnessProject
    from frame_harness.vehicle import run_vehicle
    ProbeSession=runpy.run_path(str(ROOT/'tools/probe-drive-execution.py'))['ProbeSession']
    class NumericSession(ProbeSession):
        def execute(self,job,run,output,capture=True):return super().execute(job,run,output,capture=False)
    project=HarnessProject(userpath=args.profile.resolve(),source=output,runs=output/'tests',startup_timeout=180,test_timeout=180)
    results=[]
    with NumericSession(project,'vehicle') as session:
        session.mode='null';session.visible_for_evidence=False
        (session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/visuals.lua').write_text("return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}\n",encoding='utf-8')
        for scenario in args.scenarios:
            result=run_vehicle(manifest,scenario,project=project,session=session)
            results.append(result);print(json.dumps(dict(scenario=scenario,status=result.get('status'),reason=result.get('reason'),failed=[k for k,v in result.get('checks',{}).items() if not v])),flush=True)
    numeric=[]
    for result in results:
        failed=[k for k,v in result.get('checks',{}).items() if not v and k!='capture_saved']
        if result.get('recording_status')!='completed' or not result.get('checks'):failed.append('missing_recording_or_checks')
        numeric.append(dict(scenario=result['scenario'],recording_status=result.get('recording_status'),failed_checks=failed))
    write_json(output/'diagnostic-pilots.json',dict(qualification_status='diagnostic_only',renderer='null',rendered_coverage=False,numerical=numeric,results=results))


if __name__=='__main__':main()
