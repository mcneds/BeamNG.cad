import copy
from pathlib import Path
import sys
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from synthetic_vehicle import recipe
from frame_harness.vehicle_motion import Predictor, compare, reference, hub_datum


def fixture(variant='primary', steer=.0, rear_extension=.0, rack=False):
    definition=recipe(variant);nodes={};wheels={};roles={};chassis=[]
    if rack:definition['steering']=dict(kind='translating_rack',axis=[1.,0,0],half_travel_m=.02)
    for i,p in enumerate([[-.3,0,.3],[.3,0,.3],[-.3,1.9,.3],[.3,1.9,.6]]):
        name='frame_'+str(i);chassis.append(name);nodes[name]=dict(position=p,mass_kg=2,component='frame')
    for corner,points in definition['hardpoints'].items():
        template=definition['templates']['front_suspension' if corner[0]=='F' else 'rear_suspension'];wish=template=='double_wishbone';linked=template in ('trailing_radius_toe','trailing_ball_radius_toe');ball=template=='trailing_ball_radius_toe'
        owner=corner+'_body';roles[owner]=corner.lower()+('_upright' if wish or linked else '_trailing_arm')
        rigid=['carrier_axis_a','carrier_axis_b','tie_outer'] if ball else ['upper_ball','lower_ball','tie_outer'] if wish else ['carrier_ball','radius_upper_outer','radius_lower_outer','tie_outer'] if linked else ['hinge_inner','hinge_outer','shock_bottom']
        for name,p in points.items():
            if name in ('hub','hub_axis'):continue
            nodes[corner+'_'+name]=dict(position=p,mass_kg=1,component=owner if name in rigid else 'other')
        for name,offset in [('axis_in',-.075),('axis_out',.075)]:
            p=np.array(points['hub'])+[offset,0,0];nodes[corner+'_'+name]=dict(position=p.tolist(),mass_kg=2,component=owner)
        wheels[corner]=dict(nodes={name:corner+'_'+name for name in ('axis_in','axis_out','shock_top')})
        if (wish or linked) and corner.startswith('R') and rear_extension:
            length=np.linalg.norm(np.array(points['tie_outer'])-points['tie_inner'])+rear_extension
            wheels[corner]['toe_link']=dict(nodes=[corner+'_tie_inner',corner+'_tie_outer'],reference_length_m=float(length))
    manifest=dict(template_definition=definition,chassis_nodes=chassis,component_roles=roles,nodes=nodes,wheels=wheels)
    if rack:
        # Independent rigid bodies are exercised in graph tests. These existing
        # noncollinear points keep this fixture focused on steering kinematics.
        manifest['steering_contract']=dict(kind='translating_rack',slider_nodes=chassis,housing_nodes=chassis)
    predictor=Predictor(manifest);ref=reference(manifest);samples=[]
    for t in np.linspace(0,5,51):
        points={n:np.array(v['position'],float) for n,v in nodes.items()};targets={}
        for corner,mechanism in predictor.mechanisms.items():
            extension=steer if corner.startswith('F') else rear_extension if mechanism.wishbone or mechanism.radius_toe or mechanism.ball_radius_toe else 0
            pose=predictor.solve(corner,.02*np.sin(t),extension)
            if corner.startswith('F') or corner in {c for c,w in wheels.items() if 'toe_link' in w}:
                targets[corner]=np.linalg.norm(mechanism.p['tie_outer']-mechanism.p['tie_inner'])+extension
            for key in ref['corners'][corner]['points']:points[corner+'_'+key]=pose[key]
            axis=pose['hub_axis']-pose['hub'];axis/=np.linalg.norm(axis);axis*=1 if mechanism.p['hub_axis'][0]>mechanism.p['hub'][0] else -1
            points[corner+'_axis_in']=pose['hub']-.075*axis;points[corner+'_axis_out']=pose['hub']+.075*axis
        r=Rotation.from_euler('xyz',[.2*np.sin(t),.1*np.cos(t),.1*t]).as_matrix()
        transformed={n:(p@r+[12+t,30-t,5]).tolist() for n,p in points.items()}
        samples.append(dict(t=float(t),reference_positions=transformed,actuator_rest_lengths=targets,steering_command=0,
                            rack_target_m=steer if rack else None,steering_applied=0.,control_filter='FILTER_AI',control_source='cadHarness'))
    return manifest,dict(motion_reference_version=2,samples=samples)


class VehicleMotionTests(unittest.TestCase):
    def test_fixed_part_drift_fails_even_without_shape_change(self):
        manifest,motion=fixture()
        host=manifest['chassis_nodes'][0]
        manifest['nodes']['fixed_child']=copy.deepcopy(manifest['nodes'][host])
        manifest['fixed_attachment_contract']={'accessory':dict(nodes=['fixed_child'])}
        for sample in motion['samples']:
            sample['reference_positions']['fixed_child']=list(sample['reference_positions'][host])
        self.assertTrue(compare(manifest,motion,'settle')['checks']['accessory_fixed_attachment_holds'])
        motion['samples'][-1]['reference_positions']['fixed_child'][2]-=.02
        result=compare(manifest,motion,'settle')
        self.assertFalse(result['checks']['accessory_fixed_attachment_holds'])
        self.assertAlmostEqual(result['metrics']['accessory_peak_fixed_displacement_m'],.02)
        del motion['samples'][-1]['reference_positions']['fixed_child']
        with self.assertRaisesRegex(ValueError,'missing reference nodes'):compare(manifest,motion,'settle')

    def test_fixed_mount_groups_are_monitored_without_manual_repair_contract(self):
        manifest,_=fixture()
        manifest['template_definition']['fixed_mounts']={'floor_tabs':[], 'bolted_panel':[], 'rack':[]}
        manifest['mass_allocations']={k:{'frame_0':1} for k in ('floor_tabs','bolted_panel','rack')}
        manifest['mounts']=[dict(child='bolted_panel',group='release_panel')]
        manifest['template_definition']['steering']={'component':'rack'}
        fixed=reference(manifest)['fixed_components']
        self.assertIn('floor_tabs',fixed)
        self.assertNotIn('bolted_panel',fixed)
        self.assertNotIn('rack',fixed)

    def test_offset_wheel_mass_center_preserves_rotating_cad_datum(self):
        hub=np.array([.6,.2,.1]);axis=np.array([[.641,.2,.1],[.731,.2,.1]])
        rotation=Rotation.from_euler('zy',[12,8],degrees=True).as_matrix()
        shift=np.array([.1,-.2,.3])
        np.testing.assert_allclose(hub_datum(hub,axis,axis@rotation.T+shift),hub@rotation.T+shift,atol=1e-12)
        with self.assertRaisesRegex(ValueError,'not on'):
            hub_datum(hub+[0,.01,0],axis,axis)

    def test_every_paired_rack_actuator_must_report_the_same_physical_target(self):
        from frame_harness.vehicle_motion import rack_actuator_target
        contract=dict(actuators=[dict(nodes=['a','rack']),dict(nodes=['b','rack'])])
        sample=dict(rack_target_m=.01,rack_targets_m=[.01,.01])
        self.assertEqual(rack_actuator_target(sample,contract,.02),.01)
        for values in ([],[.01],[.01,-.01],[.01,float('nan')],[.01,.01,.01]):
            with self.subTest(values=values),self.assertRaisesRegex(ValueError,'paired'):
                rack_actuator_target(sample|dict(rack_targets_m=values),contract,.02)
        self.assertEqual(rack_actuator_target(dict(rack_target_m=.01),{},.02),.01)

    def test_turn_heading_accepts_a_complete_circle_but_rejects_sliding_wrong_or_reversed_turns(self):
        from frame_harness.vehicle_motion import turn_heading
        for scenario,sign in (('left_turn',-1),('right_turn',1)):
            for angles,accepted in ((np.linspace(0,360,45),True),(np.linspace(0,40,45),False),
                                    (np.zeros(45),False),(np.linspace(0,-360,45),False),
                                    (np.r_[np.linspace(0,200,25),np.linspace(200,150,20)],False)):
                records=[dict(t=i*.5,yaw_deg=float((sign*a+180)%360-180)) for i,a in enumerate(angles)]
                checks,metrics=turn_heading(records,scenario)
                with self.subTest(scenario=scenario,end=angles[-1]):self.assertEqual(all(checks.values()),accepted,metrics)

    def test_turn_heading_uses_measured_chassis_pose(self):
        from frame_harness.vehicle_motion import rigid_fit
        manifest,motion=fixture()
        chassis=manifest['chassis_nodes'];original=[manifest['nodes'][n]['position'] for n in chassis]
        for sample in motion['samples']:
            r,translation=rigid_fit(original,[sample['reference_positions'][n] for n in chassis])
            theta=-2*np.pi*sample['t']/5
            turn=Rotation.from_euler('z',theta).as_matrix()
            sample['reference_positions']={n:(((np.array(p)-translation)@r.T)@turn+[5*(1-np.cos(theta)),5*np.sin(theta),1]).tolist()
                                           for n,p in sample['reference_positions'].items()}
        left=compare(manifest,motion,'left_turn')
        self.assertTrue(left['checks']['turn_heading_requested'])
        self.assertTrue(left['checks']['turn_heading_consistent'])
        self.assertAlmostEqual(left['metrics']['requested_heading_change_deg'],360,places=7)
        right=compare(manifest,motion,'right_turn')
        self.assertFalse(right['checks']['turn_heading_requested'])

    def test_common_rack_translation_preserves_both_tie_lengths_and_reports_drift(self):
        manifest,motion=fixture(steer=.004,rack=True)
        result=compare(manifest,motion,'supported');self.assertEqual(result['status'],'passed')
        for corner in ('FL','FR'):
            self.assertLess(result['metrics'][corner+'_peak_tie_length_error_m'],1e-7)
            actual=result['samples'][-1]['corners'][corner]
            np.testing.assert_allclose(np.array(actual['ideal']['tie_inner'])-manifest['template_definition']['hardpoints'][corner]['tie_inner'],[.004,0,0],atol=1e-9)
        bad=copy.deepcopy(motion);bad['samples'][-1]['rack_target_m']=-.004
        self.assertEqual(compare(manifest,bad,'supported')['status'],'failed')
        del bad['samples'][-1]['rack_target_m']
        with self.assertRaisesRegex(ValueError,'rack actuator target'):compare(manifest,bad,'supported')

    def test_radius_rods_cannot_be_missing_or_drift_from_the_carrier(self):
        manifest,motion=fixture('radius_toe');good=compare(manifest,motion,'articulation')
        self.assertEqual(good['status'],'passed')
        for key in ('radius_upper_outer','radius_lower_outer','carrier_ball'):
            missing=copy.deepcopy(motion);missing['samples'][-1]['reference_positions'].pop('RL_'+key)
            with self.assertRaisesRegex(ValueError,'missing reference nodes'):compare(manifest,missing,'articulation')
            bad=copy.deepcopy(motion)
            for sample in bad['samples']:sample['reference_positions']['RL_'+key][2]+=.04
            result=compare(manifest,bad,'articulation')
            self.assertFalse(result['checks']['RL_body_holds_shape'])

    def test_shaft_chain_records_all_supports_and_rejects_missing_or_drifting_joints(self):
        manifest,motion=fixture();support=manifest['chassis_nodes'][:3]
        # Add an angled two-section shaft in the same rigidly moving chassis.
        positions=[[0,0,.4],[.1,.8,.5],[0,1.8,.4]];ids=['shaft_a','shaft_mid','shaft_b']
        for n,p in zip(ids,positions):manifest['nodes'][n]=dict(position=p,mass_kg=1,component='shaft')
        joints=[dict(node=n,support_nodes=support) for n in ids]
        sections=[dict(component='section_'+str(i),nodes=ids[i:i+2],plunge_m=.01,
                       length_m=float(np.linalg.norm(np.array(positions[i+1])-positions[i]))) for i in range(2)]
        manifest['shaft_chains']={'front':dict(joints=joints,segments=sections)}
        manifest['joints']=[dict(id=n+'_support',nodes=support+[n],kind='spherical') for n in ids]
        from frame_harness.vehicle_motion import rigid_fit
        for sample in motion['samples']:
            r,t=rigid_fit([manifest['nodes'][n]['position'] for n in support],[sample['reference_positions'][n] for n in support])
            sample['reference_positions'].update({n:(np.array(p)@r+t).tolist() for n,p in zip(ids,positions)})
        self.assertTrue(set(ids)<=set(reference(manifest)['nodes']))
        good=compare(manifest,motion,'supported');self.assertEqual(good['status'],'passed')
        self.assertTrue(good['checks']['section_0_shaft_length_holds'])
        missing=copy.deepcopy(motion);del missing['samples'][-1]['reference_positions']['shaft_mid']
        with self.assertRaisesRegex(ValueError,'missing reference nodes'):compare(manifest,missing,'supported')
        bad=copy.deepcopy(motion)
        for sample in bad['samples']:sample['reference_positions']['shaft_mid'][1]+=.08
        drift=compare(manifest,bad,'supported')
        self.assertFalse(drift['checks']['shaft_mid_support_attachment_holds'])
        self.assertFalse(drift['checks']['section_0_shaft_length_holds'])

    def test_fixed_rear_alignment_is_predicted_and_wrong_native_length_rejected(self):
        manifest,motion=fixture('independent_rear',rear_extension=.0004)
        result=compare(manifest,motion,'articulation')
        self.assertEqual(result['status'],'passed')
        self.assertGreater(abs(result['samples'][-1]['corners']['RL']['ideal_toe_deg']),.1)
        self.assertLess(result['metrics']['RL_peak_toe_error_deg'],1e-4)
        for target in (None,manifest['wheels']['RL']['toe_link']['reference_length_m']+.001):
            bad=copy.deepcopy(motion);bad['samples'][-1]['actuator_rest_lengths']['RL']=target
            with self.subTest(target=target),self.assertRaises(ValueError):compare(manifest,bad,'articulation')

    def test_zero_requested_steering_cannot_hide_applied_assistance(self):
        manifest,motion=fixture()
        motion['samples'][-1]['steering_applied']=.003
        result=compare(manifest,motion,'acceleration')
        self.assertTrue(result['checks']['straight_steering_command'])
        self.assertFalse(result['checks']['straight_applied_steering'])
        self.assertEqual(result['metrics']['peak_applied_steering'],.003)
        for key,value in [('steering_applied',None),('steering_applied',float('nan')),('control_filter',1),('control_source','local')]:
            bad=copy.deepcopy(motion);bad['samples'][-1][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):compare(manifest,bad,'supported')

    def test_return_through_design_pose_does_not_create_false_unreachable_travel(self):
        manifest,_=fixture();predictor=Predictor(manifest)
        for corner in ('FL','FR','RL','RR'):
            for height in (-.08,-.04,0,.04,.08,0,-.04):
                pose=predictor.solve(corner,height,0)
                self.assertAlmostEqual(pose['hub'][2]-predictor.mechanisms[corner].p['hub'][2],height,places=7)

    def test_shared_pivot_is_audited_as_part_of_each_mass_owning_body(self):
        manifest,motion=fixture();owner='FL_body';ball='FL_upper_ball'
        ids=[n for n,v in manifest['nodes'].items() if v['component']==owner]
        manifest['mass_allocations']={owner:{n:1. for n in ids}}
        manifest['nodes'][ball]['component']='other_arm'
        manifest['joints']=[dict(id='FL_ball',kind='shared_ball',nodes=[ball])]
        self.assertIn(ball,reference(manifest)['bodies'][owner])
        result=compare(manifest,motion,'articulation')
        self.assertTrue(result['checks']['FL_body_holds_shape'])
        self.assertTrue(result['checks']['FL_ball_attachment_holds'])
        for sample in motion['samples']:sample['reference_positions'][ball][2]+=.04
        self.assertFalse(compare(manifest,motion,'articulation')['checks']['FL_body_holds_shape'])

    def test_ideal_travel_and_steering_survive_global_roll_yaw_and_translation(self):
        for variant in ('primary','independent_rear','radius_toe','ball_radius_toe'):
            manifest,motion=fixture(variant,steer=.012)
            result=compare(manifest,motion,'articulation')
            self.assertEqual(result['status'],'passed',[k for k,v in result['checks'].items() if not v])
            self.assertLess(result['metrics']['FL_peak_camber_error_deg'],1e-4)
            self.assertLess(result['metrics']['RR_peak_hub_path_error_m'],1e-5)

    def test_distorted_wheel_fails_even_with_successful_vehicle_speed(self):
        manifest,motion=fixture()
        for sample in motion['samples']:
            sample['reference_positions']['FL_axis_out'][2]+=.06
        result=compare(manifest,motion,'acceleration')
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['checks']['FL_axle_length_error_m'])
        self.assertFalse(result['checks']['FL_body_holds_shape'])

    def test_perfect_linkage_still_fails_uncommanded_vehicle_drift(self):
        manifest,motion=fixture()
        result=compare(manifest,motion,'acceleration')
        self.assertFalse(result['checks']['straight_lateral_drift'])
        self.assertFalse(result['checks']['straight_heading'])
        self.assertTrue(result['checks']['FL_camber_error_deg'])

    def test_missing_points_actuator_and_sampling_gaps_are_not_qualified(self):
        manifest,motion=fixture()
        for defect in ('node','actuator','gap','version'):
            bad=copy.deepcopy(motion)
            if defect=='node':del bad['samples'][20]['reference_positions']['frame_0']
            elif defect=='actuator':bad['samples'][20]['actuator_rest_lengths']={}
            elif defect=='gap':bad['samples']=bad['samples'][:10]+bad['samples'][20:]
            else:bad.pop('motion_reference_version')
            with self.subTest(defect=defect),self.assertRaises(ValueError):compare(manifest,bad,'supported')


if __name__=='__main__':unittest.main()
