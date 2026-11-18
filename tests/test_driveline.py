"""Offline graph/mass/constraint checks, not native vehicle qualification."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import driveline as d
from driveline_physics import configure


def graph(layout='rwd'):
    result=dict(version=1,devices=[],endpoints=[],shafts=[],connections=[])
    def device(identity,kind,owner=None,wheel=None,ratio=None):
        item=dict(id=identity,name=identity,type=kind,component=owner or identity,ports=[],parameters={})
        if wheel:item['wheel']=wheel
        if ratio is not None:item['parameters']['gearRatio']=ratio
        for direction,count in (('input',0 if kind=='engine' else 1),('output',0 if kind=='wheel' else 2 if kind in ('differential','splitter') else 1)):
            for i in range(1,count+1):
                key=identity+'_'+direction+str(i)
                item['ports'].append(dict(id=key,name=key,direction=direction,index=i,endpoint=key))
                result['endpoints'].append(dict(id=key,name=key,component=item['component'],position=[0,0,0],axis=[1,0,0]))
        result['devices'].append(item)
    def connect(a,b,port=1):
        result['connections'].append(dict(id='link_'+str(len(result['connections'])),a=a+'_output'+str(port),b=b+'_input1',kind='direct'))
    device('motor','engine');device('engagement','clutch','motor');device('variable','cvt');device('reduction','reduction',ratio=8)
    connect('motor','engagement');connect('engagement','variable');connect('variable','reduction')
    if layout=='awd':
        device('takeoff','splitter');device('front_gears','reduction',ratio=.125);device('front_diff','differential',ratio=8)
        connect('reduction','takeoff');connect('takeoff','front_gears',2);connect('front_gears','front_diff');rear='takeoff'
    else:rear='reduction'
    device('final','differential');connect(rear,'final')
    for corner in ('FL','FR') if layout=='fwd' else ('FL','FR','RL','RR') if layout=='awd' else ('RL','RR'):
        device('wheel_'+corner,'wheel',corner.lower()+'_wheel',wheel=corner)
        connect('front_diff' if layout=='awd' and corner.startswith('F') else 'final','wheel_'+corner,1 if corner.endswith('L') else 2)
    return result


class DrivelineTests(unittest.TestCase):
    def test_layouts_and_device_ids_do_not_define_routing(self):
        for layout,driven in [('rwd',['RL','RR']),('fwd',['FL','FR']),('awd',['FL','FR','RL','RR'])]:
            spec=graph(layout);part,contract=d.compile(spec,['a','b','c'],'v',{})
            self.assertEqual(contract['driven_wheels'],driven)
            self.assertEqual(contract['devices']['drive_final']['inputName'],'drive_takeoff' if layout=='awd' else 'drive_reduction')
            spec['devices'].reverse();spec['connections'].reverse();spec['endpoints'].reverse()
            again,_=d.compile(spec,['a','b','c'],'v',{})
            self.assertEqual(part['powertrain'],again['powertrain'])

    def test_body_names_and_duplicate_roles_do_not_control_topology(self):
        spec=graph();project=dict(Components=[dict(Id=e,Name='Housing',MvpRole='') for e in {p['component'] for p in spec['endpoints']}])
        data=d.validate(spec,project)
        self.assertEqual(d.wheel_housings(spec),dict(RL='final',RR='final'))
        self.assertEqual(data['devices']['reduction']['parameters']['gearRatio'],8)

    def test_shaft_section_is_a_native_edge_between_explicit_ports(self):
        spec=graph();link=next(l for l in spec['connections'] if l['a']=='variable_output1');spec['connections'].remove(link)
        for key,p in [('shaft_a',[0,0,0]),('shaft_b',[0,1,0])]:spec['endpoints'].append(dict(id=key,component='physical_shaft',position=p,axis=[0,1,0]))
        next(e for e in spec['endpoints'] if e['id']=='reduction_input1')['position']=[0,1,0]
        spec['shafts'].append(dict(id='arbitrary_section',component='physical_shaft',a='shaft_a',b='shaft_b'))
        spec['connections'].extend([dict(id='joint_a',a='variable_output1',b='shaft_a',kind='spherical'),dict(id='joint_b',a='shaft_b',b='reduction_input1',kind='spherical')])
        part,contract=d.compile(spec,['a','b','c'],'v',{})
        self.assertEqual(contract['devices']['drive_reduction']['inputName'],'shaft_arbitrary_section')
        self.assertEqual(contract['devices']['shaft_arbitrary_section']['inputName'],'gearbox')

    def test_invalid_graphs_fail_before_generation(self):
        mutations={
            'duplicate ID':lambda s:s['devices'].append(copy.deepcopy(s['devices'][0])),
            'missing connection':lambda s:s['connections'].pop(),
            'duplicate output':lambda s:s['connections'].append(dict(id='extra',a='final_output1',b='wheel_RR_input1',kind='direct')),
            'port index':lambda s:s['devices'][-1]['ports'][0].update(index=2),
            'unknown type':lambda s:s['devices'][0].update(type='magic'),
            'bad ratio':lambda s:s['devices'][3]['parameters'].update(gearRatio=0),
            'nonfinite':lambda s:s['endpoints'][0].update(position=[float('nan'),0,0]),
            'zero axis':lambda s:s['endpoints'][0].update(axis=[0,0,0]),
            'double engine':lambda s:s['devices'][3].update(type='engine'),
            'duplicate wheel':lambda s:s['devices'][-1].update(wheel='RL'),
        }
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                spec=graph();mutate(spec)
                with self.assertRaises(ValueError):d.validate(spec)

    def test_private_cad_bindings_resolve_without_publishing_references(self):
        spec=graph();anchors=[]
        for e in spec['endpoints']:
            for key,pos in [('anchor',[0,0,0]),('axis_anchor',[1,0,0])]:
                aid=e['id']+'_'+key;e[key]=aid;anchors.append(dict(Id=aid,ComponentId=e['component'],Status='resolved',Position=pos,References=['private']))
            e.pop('position');e.pop('axis')
        project=dict(Driveline=spec,Anchors=anchors,Components=[dict(Id=x,Name=x) for x in {e['component'] for e in spec['endpoints']}])
        resolved=d.resolve(project)
        self.assertFalse(any('anchor' in e or 'axis_anchor' in e for e in resolved['endpoints']))
        self.assertIn('anchor',project['Driveline']['endpoints'][0])
        project['Anchors'][0]['Status']='needs_repair'
        with self.assertRaisesRegex(ValueError,'repair'):d.resolve(project)

    def test_native_normalization_uses_actual_compiled_child_names(self):
        spec=graph('awd');part,contract=d.compile(spec,['a','b','c'],'v',{})
        wheels=dict(FL=.11,FR=.12,RL=.135,RR=.14);recoil={k:.0005 for k in wheels}
        configure(part,contract,wheels,recoil,{})
        self.assertEqual(contract['devices']['drive_takeoff']['inertiaChildren'],['drive_final','drive_front_gears'])
        self.assertEqual(set(contract['coupling_budgets']),{'drive_engagement','gearbox','drive_takeoff'})
        for budget in contract['coupling_budgets'].values():
            self.assertGreater(budget['native_inertia_kg_m2'],0)
            self.assertLess(budget['step_eigenvalue'],2)
            self.assertTrue(all(np.isfinite(list(budget['expected'].values()))))

    def test_reviewed_coordinates_never_mask_broken_native_references(self):
        spec=graph();project=dict(Driveline=spec,Components=[dict(Id=x,Name=x) for x in {e['component'] for e in spec['endpoints']}])
        self.assertEqual(d.resolve(project)['version'],1)
        spec['endpoints'][0]['anchor']='deleted'
        with self.assertRaisesRegex(ValueError,'repair'):d.resolve(project)

    def test_primary_output_two_and_reversed_reduction_keep_native_normalization(self):
        spec=graph('awd');next(v for v in spec['devices'] if v['id']=='takeoff')['parameters']['primaryOutputID']=2
        next(v for v in spec['devices'] if v['id']=='front_gears')['parameters']['direction']=-1
        part,contract=d.compile(spec,['a','b','c'],'v',{})
        self.assertEqual(contract['devices']['drive_front_gears']['gearRatio'],-.125)
        self.assertEqual(contract['wheel_rotation_signs']['FL'],-1)
        wheels=dict(FL=.11,FR=.12,RL=.135,RR=.14);configure(part,contract,wheels,{k:.0005 for k in wheels},{})
        budget=contract['coupling_budgets']['drive_takeoff'];self.assertGreater(budget['native_inertia_kg_m2'],0)
        self.assertLess(budget['step_eigenvalue'],2)

    def test_wheel_reaction_follows_the_last_declared_gear_housing_axis(self):
        spec=graph();spec['devices'].append(dict(id='last_reduction',type='reduction',component='custom_case',parameters=dict(gearRatio=2),ports=[
            dict(id='in',direction='input',index=1,endpoint='new_in'),dict(id='out',direction='output',index=1,endpoint='new_out')]))
        spec['endpoints'].extend([dict(id=e,component='custom_case',position=[0,0,0],axis=[0,0,1]) for e in ('new_in','new_out')])
        link=next(l for l in spec['connections'] if l['b']=='wheel_RL_input1');link['b']='new_in'
        spec['connections'].append(dict(id='last_link',a='new_out',b='wheel_RL_input1',kind='direct'))
        self.assertEqual(d.wheel_reactions(spec)['RL'],dict(component='custom_case',axis=[0,0,1]))

    def test_bearing_sites_are_supports_instead_of_torque_branches(self):
        spec=graph();spec['connections']=[l for l in spec['connections'] if l['a']!='variable_output1']
        for name,owner,p in [('sa','shaftA',[0,0,0]),('sb','shaftA',[0,1,0]),('carrier','bearing',[0,1,0])]:
            spec['endpoints'].append(dict(id=name,component=owner,position=p,axis=[0,1,0]))
        next(e for e in spec['endpoints'] if e['id']=='reduction_input1')['position']=[0,1,0]
        spec['shafts']=[dict(id='section',component='shaftA',a='sa',b='sb')]
        spec['connections'].extend([dict(id='ja',a='variable_output1',b='sa',kind='spherical'),dict(id='jb',a='sb',b='reduction_input1',kind='spherical'),dict(id='bearing_link',a='sb',b='carrier',kind='bearing')])
        self.assertEqual(len(d.validate(spec)['routes']),6)

    def test_migration_keeps_plunge_and_does_not_assume_uuid_starts_with_a_letter(self):
        from driveline_presets import from_project
        import json,tempfile
        spec=graph();roles=['engine','cvt','rear_diff','rl_wheel','rr_wheel','rl_halfshaft']
        components=[dict(Id=('1abc' if r=='rl_halfshaft' else r),MvpRole=r,Name=r) for r in roles]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'definition.json';path.write_text(json.dumps(dict(halfshafts={'1abc':dict(plunge_m=.027)})))
            project=dict(Components=components,MvpTemplates=[dict(Category='drivetrain',Template='cvt_rear_drive')],TemplateDefinitionPath=str(path))
            converted=from_project(project);shaft=converted['shafts'][0]
            self.assertEqual(shaft['legacy_plunge_m'],.027)
            self.assertTrue(shaft['a'].startswith('cad_1abc'))
            self.assertNotIn('axis',next(e for e in converted['endpoints'] if e['id']==shaft['a']))

    def test_native_rate_checks_follow_device_ports_instead_of_axle_names(self):
        sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
        from frame_harness.driveline_checks import sampled_checks
        part,contract=d.compile(graph('awd'),['a','b','c'],'v',{});state={}
        for row in part['powertrain'][1:]:
            kind,name,parent,port=row[:4];ratio=2.5 if kind=='cvtGearbox' else row[4].get('gearRatio',1.)
            incoming=state[parent]['output_av2' if port==2 else 'output_av'] if parent in state else 100.
            out=incoming/ratio
            state[name]=dict(input_av=incoming,output_av=out,ratio=ratio)
            if kind in ('differential','splitShaft'):state[name]['output_av2']=out
        checks,_=sampled_checks(contract,[dict(t=15,devices=state),dict(t=16,devices=state)])
        self.assertTrue(all(checks.values()))
        state['drive_front_gears']['input_av']*=2
        checks,_=sampled_checks(contract,[dict(t=15,devices=state)])
        self.assertFalse(checks['drive_front_gears_input_rate_matches_port'])
        state['drive_front_gears']['input_av']/=2;state['drive_front_diff'].pop('output_av2')
        checks,_=sampled_checks(contract,[dict(t=15,devices=state)])
        self.assertFalse(checks['drive_front_diff_native_ratio_law'])

    def test_reviewed_definition_graph_overrides_preset_roles_without_mutating_project(self):
        from component_worker import validate_project
        project=dict(Identity=dict(id='a'*32,namespace='fixture_aaaaaaaa'),
            Components=[dict(Id='front_case',Name='Front case',MvpRole='front_diff',BodyIds=['one_body'])],
            Anchors=[],Connections=[],MvpTemplates=[dict(Category='drivetrain',Template='cvt_rear_drive')])
        reviewed=dict(endpoints=[dict(component='front_case')])
        with patch('component_representation.validate'):
            with self.assertRaisesRegex(ValueError,'outside'):validate_project(project)
            validate_project(project,reviewed)
        self.assertNotIn('Driveline',project)


def physical_fixture(postprocess=None):
    from test_vehicle_template_graph import fixture
    from driveline_presets import from_project
    def customize(spec,components,moments):
        project=dict(Components=components,JointWorkspace=dict(Parameters=spec['parameters'],Bindings=[]),MvpTemplates=[dict(Category=k,Template=v) for k,v in spec['templates'].items()])
        spec['driveline']=from_project(project);spec['driveline']['version']=1;spec['version']=2
        ep={e['id']:e for e in spec['driveline']['endpoints']}
        for e in ep.values():e['position']=moments[e['component']][1].tolist();e['axis']=[1,0,0]
        for s in spec['driveline']['shafts']:
            s.pop('representation',None);s.pop('half_travel_m',None)
            s.pop('legacy_plunge_m',None) # Explicit fixed-length synthetic fixture, not a migrated user's vehicle.
            owner=s['component'];decl=(spec['shafts']|spec['halfshafts'])[owner]
            a,b=decl['inner'],decl['outer']
            if owner=='front_propshaft':a,b=b,a
            ep[s['a']]['position']=list(a);ep[s['b']]['position']=list(b)
            axis=np.array(b)-a;axis/=np.linalg.norm(axis)
            ep[s['a']]['axis']=axis.tolist();ep[s['b']]['axis']=axis.tolist()
        for link in spec['driveline']['connections']:
            if link['kind']!='spherical':continue
            a,b=ep[link['a']],ep[link['b']]
            shaft=a if any(s['a']==a['id'] or s['b']==a['id'] for s in spec['driveline']['shafts']) else b
            other=b if shaft is a else a;other['position']=shaft['position']
        spec['shafts']={};spec['halfshafts']={}
        if postprocess:postprocess(spec,components,moments)
    return fixture('primary',customize)


class DrivelinePhysicsTests(unittest.TestCase):
    def test_ideal_port_routes_use_suspension_hubs_and_no_internal_shaft_nodes(self):
        import components as c
        from vehicle_templates import generate
        def route_ports(spec, components, moments):
            drive=spec['driveline']
            drive['version']=2
            for shaft in drive['shafts']:
                for key in ('a','b'):
                    old=shaft[key]
                    link=next(link for link in drive['connections'] if old in (link['a'],link['b']))
                    shaft[key]=link['b'] if link['a']==old else link['a']
                    drive['connections'].remove(link)
                    drive['endpoints']=[e for e in drive['endpoints'] if e['id']!=old]
                shaft.update(representation='ideal',half_travel_m=.025)
            for device in drive['devices']:
                if device['type']=='wheel':
                    endpoint=next(e for e in drive['endpoints'] if e['id']==device['ports'][0]['endpoint'])
                    endpoint.pop('position');endpoint.pop('axis')
        project,frame,spec,cad=physical_fixture(route_ports)
        with patch.object(c,'read_geometry',side_effect=cad):
            structure,part,_,_,contract,meshes,bindings=generate(project,frame,spec)
        self.assertFalse(structure.driveline_physics['rails'])
        self.assertEqual(contract['driven_wheels'],['FL','FR','RL','RR'])
        for section in structure.driveline_physics['sections']:
            owner=section['component'];self.assertEqual(section['representation'],'ideal')
            self.assertEqual(len(section['nodes']),2);self.assertEqual(section['half_travel_m'],.025)
            self.assertEqual(set(section['nodes']),set(structure.mass_allocations[owner]))
            self.assertEqual(sum(structure.mass_allocations[owner].values()),cad({'Id':owner})[1][0])
            self.assertIn(owner,meshes);self.assertIn(owner,bindings)
        self.assertFalse(any(n.startswith('driveline_axis_') for n in structure.nodes))

    def test_wrong_wheel_terminal_is_rejected_before_frame_calibration(self):
        from vehicle_templates import frame_mount_plan
        project,_,spec,_=physical_fixture()
        terminal=next(d for d in spec['driveline']['devices'] if d.get('wheel')=='FL')['ports'][0]['endpoint']
        next(e for e in spec['driveline']['endpoints'] if e['id']==terminal)['axis']=[0,1,0]
        with self.assertRaisesRegex(ValueError,'hub axis'):frame_mount_plan(spec,project['Components'])

    def test_floating_joint_and_explicit_slider_use_independent_rigid_bodies(self):
        import components as c
        from vehicle_templates import Structure
        from driveline_physics import generate,housing_points
        for kind in ('spherical','slider'):
            with self.subTest(kind=kind):
                spec=graph();spec['connections']=[l for l in spec['connections'] if l['a']!='variable_output1']
                points=[[0,0,0],[0,.5,0],[.2,1,0]] if kind=='spherical' else [[0,0,0],[0,.5,0],[0,1,0]]
                ep={e['id']:e for e in spec['endpoints']}
                ep['variable_output1']['position']=points[0];ep['reduction_input1']['position']=points[2]
                for name,owner,point in [('sa','sectionA',points[0]),('sb','sectionA',points[1]),('sc','sectionB',points[1]),('sd','sectionB',points[2])]:
                    spec['endpoints'].append(dict(id=name,component=owner,position=point,axis=[0,1,0]))
                spec['shafts']=[dict(id='first',component='sectionA',a='sa',b='sb'),dict(id='second',component='sectionB',a='sc',b='sd')]
                spec['connections'].extend([dict(id='ja',a='variable_output1',b='sa',kind='spherical'),dict(id='floating',a='sb',b='sc',kind=kind,travel=.02),dict(id='jb',a='sd',b='reduction_input1',kind='spherical')])
                components=[dict(Id=x,Name=x,MvpRole='',Template='bulk') for x in {e['component'] for e in spec['endpoints']}]
                project=dict(Components=components)
                frame=dict(nodes=[['id','posX','posY','posZ'],['f',0,0,-1,dict(nodeWeight=1,group=['frame'])]],beams=[['id1:','id2:']])
                structure=Structure(frame);structure.driveline_hub_owners={}
                centers={'variable':np.array(points[0]),'reduction':np.array(points[2]),'sectionA':(np.array(points[0])+points[1])/2,'sectionB':(np.array(points[1])+points[2])/2}
                def cad(comp):return [],(2.,centers[comp['Id']],np.eye(3)*.04),{}
                with patch.object(c,'read_geometry',side_effect=cad):
                    for owner in ('variable','reduction'):
                        p=centers[owner];required=housing_points(spec,owner)
                        required.update({owner+'_support_'+str(i):p+v for i,v in enumerate(([-.1,-.1,-.1],[.1,-.1,-.1],[0,.1,.1]))})
                        structure.rigid_component(next(v for v in components if v['Id']==owner),required)
                    contract=generate(spec,structure,project,{}, {},lambda g,o,p: __import__('vehicle_templates').joint_supports(g,o,p))
                self.assertEqual(len(contract['sections']),2)
                self.assertAlmostEqual(sum(structure.mass_allocations['sectionA'].values()),2.)
                self.assertAlmostEqual(sum(structure.mass_allocations['sectionB'].values()),2.)
                if kind=='spherical':
                    a,b=contract['sections'];self.assertEqual(a['endpoints'][1],b['endpoints'][0])
                    self.assertEqual(len([j for j in contract['joints'] if j['kind']=='floating']),1)
                    self.assertFalse(any(j.get('parent')=='frame' for j in contract['joints']))
                else:
                    self.assertEqual(len(contract['rails']),3)
                    self.assertEqual(len(structure.part['slidenodes']),4)
                    for rail in contract['rails']:
                        self.assertAlmostEqual(np.linalg.norm(structure.point(rail['b'])-structure.point(rail['a'])),.04)
                    centers=[(structure.point(r['a'])+structure.point(r['b']))/2 for r in contract['rails']]
                    sliders=[structure.point(r['slider']) for r in contract['rails']]
                    np.testing.assert_allclose(np.mean(centers,axis=0),points[1],atol=1e-12)
                    np.testing.assert_allclose(np.mean(sliders,axis=0),points[1],atol=1e-12)
                    np.testing.assert_allclose(structure.point('driveline_sc'),points[1],atol=1e-12)

    def test_graph_generates_with_cad_owned_rigid_sections(self):
        import components as c
        from vehicle_templates import generate
        project,frame,spec,cad=physical_fixture()
        with patch.object(c,'read_geometry',side_effect=cad):
            graph,part,wheels,_,contract,meshes,bindings=generate(project,frame,spec)
        self.assertEqual(contract['template'],'driveline_graph')
        self.assertEqual(set(contract['driven_wheels']),{'FL','FR','RL','RR'})
        self.assertEqual(len(graph.driveline_physics['sections']),len(spec['driveline']['shafts']))
        for section in spec['driveline']['shafts']:
            owner=section['component'];self.assertIn(owner,meshes)
            self.assertGreater(len(graph.mass_allocations[owner]),2)
            self.assertAlmostEqual(sum(graph.mass_allocations[owner].values()),cad(next(c for c in project['Components'] if c['Id']==owner))[1][0])
            self.assertLess(graph.reports[owner]['center_error_m'],1e-5)


if __name__=='__main__':unittest.main()
