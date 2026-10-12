"""Graph/kinematic checks use analytic moments; native acceptance is separate."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from test_vehicle_template_graph import fixture
from vehicle_templates import generate,TemplateModel
from translating_rack import declaration,control_direction,travel_speed
from synthetic_vehicle import recipe
from vehicle_wizard.kinematics import Mechanism


class TranslatingRackTests(unittest.TestCase):
    def test_symmetric_rack_does_not_steer_under_symmetric_transverse_load(self):
        import json,runpy,tempfile
        def authored(spec,components,moments):
            spec['steering']=dict(kind='translating_rack',component='steering_rack',housing_member='housing',rack_member='slider',axis=[1.,0,0],half_travel_m=.01)
        project,frame,spec,cad=fixture('primary',authored)
        project['JointWorkspace']=dict(Members=[dict(Id=i,ComponentId='steering_rack',Name=i,Kind=k,GeometryDirectory='fake',Selections=[],BodyIds=[i]) for i,k in [('housing','housing'),('slider','rack')]])
        original=cad(dict(Id='steering_rack'))[1]
        def member_cad(component):
            if component['Id'] not in ('housing','slider'):return cad(component)
            factor=.6 if component['Id']=='housing' else .4
            return [],(original[0]*factor,original[1],original[2]*factor),{}
        with patch('components.read_geometry',side_effect=member_cad):graph,part,*_=generate(project,frame,spec)
        # Solve the exported static stiffness under symmetric road loads with
        # housing mounts fixed. A symmetric CAD rack must have zero mean axial
        # response; an arbitrary numerical actuator side must not introduce it.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'rack.jbeam').write_text(json.dumps(dict(rack=part)))
            (root/'manifest.json').write_text(json.dumps(dict(vehicle_directory='.',main_jbeam='rack.jbeam',main_part='rack',
                steering_contract=graph.steering_contract,nodes=graph.nodes)))
            report=runpy.run_path(str(ROOT/'tools/diagnose-rack-stiffness.py'))['diagnose'](root/'manifest.json')
        for load in ('common_vertical','common_fore_aft','opposed'):
            self.assertLess(abs(report['cases'][load]['mean_axial_m']),1e-8,load)

    def test_control_direction_follows_front_and_rear_racks_and_reversed_axis(self):
        for ahead in (False,True):
            for axis_sign in (-1,1):
                with self.subTest(ahead=ahead,axis_sign=axis_sign):
                    spec=recipe('primary')
                    spec['steering']=dict(kind='translating_rack',axis=[axis_sign,0.,0.],half_travel_m=.01)
                    if ahead:
                        for corner in ('FL','FR'):
                            p=spec['hardpoints'][corner]
                            for key in ('tie_inner','tie_outer'):p[key][1]=2*p['hub'][1]-p[key][1]
                    control=control_direction(spec)
                    self.assertEqual(control['input_to_rack_sign'],axis_sign*(-1 if ahead else 1))
                    for corner in ('FL','FR'):
                        linkage=Mechanism(TemplateModel(spec),corner)
                        _,zero=linkage.solve(0,0)
                        def toe(p):
                            a=p['hub_axis']-p['hub'];a*=1 if a[0]>0 else -1
                            return np.arctan2(a[1],a[0])
                        for command in (-.7,.7):
                            _,pose=linkage.solve(0,command*.01*control['input_to_rack_sign'])
                            self.assertLess(command*(toe(pose)-toe(zero)),0.)

    def test_opposed_front_linkages_are_rejected(self):
        spec=recipe('primary');spec['steering']=dict(kind='translating_rack',axis=[1.,0,0],half_travel_m=.01)
        p=spec['hardpoints']['FR']
        for key in ('tie_inner','tie_outer'):p[key][1]=2*p['hub'][1]-p[key][1]
        with self.assertRaisesRegex(ValueError,'opposite directions'):control_direction(spec)

    def test_opposed_actuators_and_independent_rigid_members_preserve_cad_mass(self):
        def authored(spec,components,moments):
            spec['steering']=dict(kind='translating_rack',component='steering_rack',housing_member='housing',rack_member='slider',axis=[1.,0,0],half_travel_m=.01)
        project,frame,spec,cad=fixture('primary',authored)
        project['JointWorkspace']=dict(Members=[dict(Id=i,ComponentId='steering_rack',Name=i,Kind=k,GeometryDirectory='fake',Selections=[],BodyIds=[i]) for i,k in [('housing','housing'),('slider','rack')]])
        original=cad(dict(Id='steering_rack'))[1]
        def member_cad(component):
            if component['Id'] not in ('housing','slider'):return cad(component)
            factor=.6 if component['Id']=='housing' else .4
            return [],(original[0]*factor,original[1],original[2]*factor),{}
        with patch('components.read_geometry',side_effect=member_cad):graph,part,*_=generate(project,frame,spec)
        self.assertEqual(len(part['hydros'][1:]),2)
        # The assembled budget may reduce both supports for this light fixture.
        # They share the former requested total, rather than doubling it.
        self.assertLessEqual(sum(row[2]['beamSpring'] for row in part['hydros'][1:]),1500000.)
        self.assertLessEqual(sum(row[2]['beamDamp'] for row in part['hydros'][1:]),60.)
        np.testing.assert_allclose([part['hydros'][1][2][k] for k in ('beamSpring','beamDamp')],
                                   [part['hydros'][2][2][k] for k in ('beamSpring','beamDamp')],rtol=1e-6)
        np.testing.assert_allclose(graph.point(part['hydros'][1][0])+graph.point(part['hydros'][2][0]),2*graph.point(part['hydros'][1][1]),atol=1e-10)
        self.assertEqual([v['rack_motion_sign'] for v in graph.steering_contract['actuators']],[1,-1])
        self.assertAlmostEqual(part['hydros'][1][2]['factor'],-part['hydros'][2][2]['factor'])
        actuator=part['hydros'][1]
        np.testing.assert_allclose(graph.point(actuator[1]),(graph.point('FL_tie_inner')+graph.point('FR_tie_inner'))/2,atol=1e-10)
        self.assertNotIn(actuator[1],('FL_tie_inner','FR_tie_inner'))
        rest=np.linalg.norm(graph.point(actuator[1])-graph.point(actuator[0]))
        for key in ('inRate','outRate','autoCenterRate'):
            self.assertAlmostEqual(actuator[2][key]*rest,.1)
        self.assertEqual(graph.steering_contract['speed_m_s'],.1)
        for command in (-.7,.7):
            displacement=command*actuator[2]['factor']*rest
            for corner in ('FL','FR'):
                _,pose=Mechanism(TemplateModel(spec),corner).solve(0,displacement)
                axis=pose['hub_axis']-pose['hub'];axis*=1 if axis[0]>0 else -1
                toe=np.arctan2(axis[1],axis[0])
                self.assertLess(command*toe,0.,'Positive BeamNG input must steer right (-yaw)')
        self.assertEqual(len(part['slidenodes'][1:]),3)
        self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.20001)
        self.assertAlmostEqual(sum(graph.mass_allocations['steering_rack'].values()),original[0],places=7)
        self.assertNotIn('FL_tie_inner',frame['cadMountPatches'])
        for corner in ('FL','FR'):
            pair={corner+'_tie_inner',corner+'_tie_outer'}
            self.assertTrue(any(isinstance(row,list) and set(row[:2])==pair for row in part['beams'][1:]))
        self.assertEqual(len(graph.moving_render['steering_rack']),2)
        self.assertTrue(set(graph.steering_contract['slider_nodes']).isdisjoint(graph.steering_contract['housing_nodes']))

    def test_joint_review_and_complete_member_partition_are_required(self):
        project=dict(Components=[dict(Id='rack',MvpRole='steering_rack')],JointWorkspace=dict(Members=[dict(Id='h',ComponentId='rack',Kind='housing'),dict(Id='s',ComponentId='rack',Kind='rack')]))
        joint=dict(Id='j',Kind='prismatic',Status='review',ParentMember='h',ChildMember='s',Axis=[1.,0,0])
        with self.assertRaisesRegex(ValueError,'Review one'):declaration(project,[joint],{})
        joint['Status']='approved';project['JointWorkspace']['Parameters']=[dict(Key='rack_half_travel_m',Value=.017)]
        self.assertEqual(declaration(project,[joint],{})['half_travel_m'],.017)
        project['JointWorkspace']['Parameters'].append(dict(Key='rack_speed_m_s',Value=.08))
        self.assertEqual(declaration(project,[joint],{})['speed_m_s'],.08)
        project['JointWorkspace']['Members'].append(dict(Id='extra',ComponentId='rack',Kind='rack'))
        with self.assertRaisesRegex(ValueError,'Classify'):declaration(project,[joint],{})

    def test_rack_speed_requires_finite_physical_units(self):
        for speed in (0.,-.1,float('nan'),float('inf'),.501):
            with self.subTest(speed=speed),self.assertRaisesRegex(ValueError,'Rack speed'):travel_speed(speed)
        self.assertEqual(travel_speed(.005),.005)
        self.assertEqual(travel_speed(.5),.5)


if __name__=='__main__':unittest.main()
