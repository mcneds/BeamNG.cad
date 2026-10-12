"""Independent recipes enter through saved CAD point/joint bindings, not JSON templates."""
import copy
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from test_vehicle_template_graph import fixture
from joint_authoring import definition,requests
from authored_shafts import compile_chains
from joint_contract import validate
from shaft_chains import validate as validate_shafts
from vehicle_templates import generate,frame_mount_plan


def authored(variant):
    project,frame,spec,cad=fixture(variant)
    project['MvpTemplates']=[dict(Category=k,Template=v) for k,v in spec['templates'].items()]
    project.update(Anchors=[],Connections=[])
    workspace=project['JointWorkspace']=dict(Mode='authored',Bindings=[],Joints=[],Members=[],Parameters=dict(rack_half_travel_m=.01,tire_rays=16.))
    def bind(key,owner,point):
        project['Anchors'].append(dict(Id=key,ComponentId=owner,Status='resolved',Position=point))
        workspace['Bindings'].append(dict(Request=key,ComponentId=owner,Status='resolved',AnchorId=key))
    for request in requests(project):
        corner,key=request['id'].split('.')
        bind(request['id'],request['role'],spec['hardpoints'][corner][key])
    for owner,shaft in spec['halfshafts'].items():
        bind(owner+'.inner_joint',owner,shaft['inner']);bind(owner+'.outer_joint',owner,shaft['outer'])
    for owner,shaft in spec['shafts'].items():
        bind(owner+'.input_joint',owner,shaft['inner']);bind(owner+'.output_joint',owner,shaft['outer'])
    for owner,points in spec['fixed_mounts'].items():
        for i,point in enumerate(points):
            a='frame_'+owner+str(i);b=owner+str(i)
            project['Anchors'].extend([dict(Id=k,ComponentId=c,Status='resolved',Position=point) for k,c in ((a,'frame'),(b,owner))])
            project['Connections'].append(dict(Id=b,Name=b,AnchorA=a,AnchorB=b,Template='breakable_fastener' if owner.startswith('panel') else 'fixed',
                                               ReleaseSet='',AttachmentLength=.006,Spring=0,Damping=0,Strength=4000))
    workspace['Members']=[dict(Id='h',Kind='housing',ComponentId='steering_rack'),dict(Id='s',Kind='rack',ComponentId='steering_rack')]
    workspace['Joints']=[dict(Id='rack_joint',Name='Native rack',Kind='prismatic',Status='approved',Parent='steering_rack',Child='steering_rack',ParentMember='h',ChildMember='s',Axis=[1.,0,0])]
    return project,spec


class AuthoredVehicleTests(unittest.TestCase):
    def test_permanent_frame_mounts_do_not_allocate_breakaway_cages(self):
        project,_=authored('primary');spec=definition(project)
        plan=frame_mount_plan(spec,project['Components'])
        for mount in spec['attachment_contract']:
            row=plan['fastener_'+mount['id']]
            self.assertEqual(row['position'],mount['position'])
            self.assertEqual(row['mode'],'short' if mount['group'] else 'direct')
            if mount['group']:self.assertEqual(row['attachment_length_m'],mount['length'])
            else:self.assertNotIn('attachment_length_m',row)

    def test_authored_graphs_preserve_mass_and_detachable_boundaries_in_two_layouts(self):
        for variant,conditioned in (('primary',False),('independent_rear',False),('primary',True)):
            with self.subTest(variant=variant,conditioned=conditioned):
                project,_=authored(variant);spec=definition(project)
                spec['parameters'].update(loaded_node_mass_policy='preserve_cad',assembled_rigid_conditioning=False)
                if conditioned:spec['parameters'].update(loaded_node_mass_policy='reported_ballast',assembled_rigid_conditioning=True)
                def customize(target,components,moments):
                    target.clear();target.update(copy.deepcopy(spec))
                _,frame,_,cad=fixture(variant,customize)
                # The analytic fixture inserts locator seed masses; an actual
                # frame is calibrated after that insertion. Keep this isolated
                # test's declared frame mass and its existing step bound exact.
                scale=cad(dict(Id='frame'))[1][0]/sum(row[-1]['nodeWeight'] for row in frame['nodes'][1:])
                for row in frame['nodes'][1:]:row[-1]['nodeWeight']*=scale
                for row in frame['beams'][1:]:
                    if isinstance(row,list):row[-1]['beamSpring']*=scale;row[-1]['beamDamp']*=scale
                for member in project['JointWorkspace']['Members']:
                    member.update(Name=member['Id'],GeometryDirectory='analytic',Selections=[],BodyIds=[member['Id']])
                original=cad(dict(Id='steering_rack'))[1]
                def geometry(component):
                    if component['Id'] not in ('h','s'):return cad(component)
                    scale=.6 if component['Id']=='h' else .4
                    return [],(original[0]*scale,original[1],original[2]*scale),{}
                with patch('components.read_geometry',side_effect=geometry):graph,part,wheels,*_=generate(project,frame,spec)
                self.assertEqual(graph.release_audit['status'],'passed')
                self.assertEqual(len(part['hydros'][1:]),2)
                declared={tuple(sorted(a['nodes'])) for a in graph.steering_contract['actuators']}
                self.assertEqual(len(declared),2)
                self.assertEqual({tuple(sorted(row[:2])) for row in part['hydros'][1:]},declared)
                expected=sum(cad(c)[1][0] for c in project['Components'])
                actual=sum(n['options']['nodeWeight'] for n in graph.nodes.values())+sum(w['wheel_mass_kg'] for w in wheels.values())
                self.assertAlmostEqual(actual,expected+graph.numerical_mass['added_mass_kg'],places=6)
                if conditioned:
                    self.assertIn('h',graph.rigid_refits);self.assertIn('s',graph.rigid_refits)
                    self.assertFalse(set(graph.rigid_refits['h']['nodes'])&set(graph.rigid_refits['s']['nodes']))
                    self.assertNotIn('steering_rack',graph.rigid_refits)
                self.assertTrue(all(m['group'] for m in graph.mounts if m['child'].startswith('panel_')))

    def test_each_layout_uses_its_own_points_and_independent_panel_mounts(self):
        for variant in ('primary','independent_rear','radius_toe'):
            with self.subTest(variant=variant):
                project,spec=authored(variant);result=definition(project)
                self.assertEqual(result['templates'],spec['templates'])
                for request in requests(project):
                    corner,key=request['id'].split('.')
                    self.assertEqual(result['hardpoints'][corner][key],spec['hardpoints'][corner][key])
                self.assertIsInstance(result['parameters']['tire_rays'],int)
                self.assertEqual(result['joint_contract']['native_joints'],['rack_joint'])
                mounts=[m for m in result['attachment_contract'] if m['group']]
                self.assertTrue(mounts);self.assertEqual(len(mounts),len({m['group'] for m in mounts}))
                validate_shafts(result,project['Components'])

    def test_wrong_owner_missing_points_and_unsupported_motion_are_rejected(self):
        project,_=authored('primary');baseline=copy.deepcopy(project)
        project['JointWorkspace']['Bindings'][0]['ComponentId']='fr_wheel'
        with self.assertRaisesRegex(ValueError,'wrong component'):definition(project)
        project=copy.deepcopy(baseline);project['JointWorkspace']['Bindings'].pop(0)
        with self.assertRaisesRegex(ValueError,'Bind required CAD'):definition(project)
        project=copy.deepcopy(baseline);project['JointWorkspace']['Joints'].append(dict(Id='extra',Name='Unused hinge',Kind='revolute',Status='approved'))
        with self.assertRaisesRegex(ValueError,'Unused hinge'):definition(project)
        project['JointWorkspace']['Joints'][-1]['Status']='positioning_only'
        definition(project)

    def test_native_ball_attachment_cannot_be_replaced_by_a_hinge(self):
        project,_=authored('primary');binding=next(b for b in project['JointWorkspace']['Bindings'] if b['Request']=='FL.upper_ball')
        joint=dict(Id='wrong',Name='Wrong joint',Parent=binding['ComponentId'],Child='fl_upright',Kind='revolute',Status='approved',Center=[0.,0.,0.])
        project['JointWorkspace']['Joints'].append(joint);binding['JointId']='wrong'
        with self.assertRaisesRegex(ValueError,'spherical attachment'):definition(project)

    def test_native_rigid_panel_placement_uses_fasteners_without_a_hidden_weld(self):
        project,_=authored('primary');baseline=definition(project)
        panel=next(m['child'] for m in baseline['attachment_contract'] if m['group'])
        joint=dict(Id='panel_joint',Name='Panel assembly mates',Parent='frame',Child=panel,Kind='rigid',Status='approved')
        project['JointWorkspace']['Joints'].append(joint);result=definition(project)
        self.assertIn('panel_joint',result['joint_contract']['native_joints'])
        self.assertEqual(result['attachment_contract'],baseline['attachment_contract'])
        joint['Kind']='spherical'
        with self.assertRaisesRegex(ValueError,'remove this native joint motion'):definition(project)

    def test_hinge_pair_must_lie_on_native_axis_and_limits_cannot_be_ignored(self):
        project,_=authored('primary');result=definition(project)
        binding=next(b for b in project['JointWorkspace']['Bindings'] if b['Request']=='RL.hinge_inner')
        hp=result['hardpoints']['RL'];joint=dict(Id='hinge',Name='Rear hinge',Parent=binding['ComponentId'],Child='frame',Kind='revolute',Status='approved',Center=hp['hinge_inner'],Axis=[1.,0,0])
        binding['JointId']='hinge';project['JointWorkspace']['Joints'].append(joint)
        validate(project,result)
        joint['Axis']=[0.,1,0]
        with self.assertRaisesRegex(ValueError,'native hinge axis'):validate(project,result)
        joint.update(Axis=[1.,0,0],HasLimits=True)
        with self.assertRaisesRegex(ValueError,'travel limits'):validate(project,result)

    def test_two_shaft_sections_follow_supported_joint_topology_not_list_order(self):
        points=[[0,1.8,.35],[.1,1,.4],[0,0,.35]]
        project=dict(Components=[dict(Id=x,Name=x,MvpRole=x,Template='bulk') for x in ('rear_final_drive','front_diff','shaft_carrier')],JointWorkspace=dict(Bindings=[],Joints=[]))
        definition=dict(templates=dict(drivetrain='cvt_rear_front_output'),fixed_mounts={x:[[0,0,0],[1,0,0],[0,1,0]] for x in ('rear_final_drive','front_diff','shaft_carrier')})
        values={}
        for owner,indexes,parents in [('second',(2,1),('front_diff','shaft_carrier')),('first',(0,1),('rear_final_drive','shaft_carrier'))]:
            project['Components'].append(dict(Id=owner,Name=owner,MvpRole='front_propshaft'))
            for suffix,i,parent in zip(('input_joint','output_joint'),indexes,parents):
                key=owner+'.'+suffix;values[key]=points[i]
                project['JointWorkspace']['Bindings'].append(dict(Request=key,ComponentId=owner,JointId=key))
                project['JointWorkspace']['Joints'].append(dict(Id=key,Kind='spherical',Status='approved',Parent=parent,Child=owner))
        chains=compile_chains(project,definition,values,{});definition['shaft_chains']=chains
        self.assertEqual([s['component'] for s in chains['front_propshaft']['segments']],['first','second'])
        checked=validate_shafts(definition,project['Components'])
        self.assertNotEqual(checked['front_propshaft']['segments'][0]['axis'],checked['front_propshaft']['segments'][1]['axis'])
        values['second.output_joint']=[.2,1,.4]
        with self.assertRaisesRegex(ValueError,'unbranched chain'):compile_chains(project,definition,values,{})


if __name__=='__main__':unittest.main()
