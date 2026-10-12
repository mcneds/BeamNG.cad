"""Optional spherical-joint rear layout: constraints, graph and role contracts."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from test_synthetic_mechanisms import Model
from test_vehicle_template_graph import fixture
from synthetic_vehicle import recipe
from synthetic_clearance import tube_wheel_clearance
from vehicle_wizard.kinematics import Mechanism
from vehicle_templates import generate, frame_mount_plan
from frame_harness.build import node_table, beam_table
import components as c
from mvp_inventory import configuration, inventory

ROOT=Path(__file__).resolve().parents[1]


class RadiusToeTests(unittest.TestCase):
    def test_physical_rods_and_carrier_clear_tire_through_travel(self):
        for track in (1.3,1.5,1.8):
            r=recipe('radius_toe',track=track);model=Model(r)
            for corner in ('RL','RR'):
                m=Mechanism(model,corner)
                for height in (-.08,0,.08):
                    state,pose=m.solve(height);transforms=m.component_transforms(state)
                    for role,key in [('trailing_arm','trailing_arm'),('upright','upright'),('upper_radius_rod','radius_upper'),('lower_radius_rod','radius_lower'),('toe_link','tie')]:
                        matrix=transforms[key]
                        def transform(p):return (matrix@np.r_[p,1.])[:3]
                        shapes=next(c['primitives'] for c in r['components'] if c['id']==corner.lower()+'_'+role)
                        for shape in shapes:
                            margin=tube_wheel_clearance(shape,pose['hub'],pose['hub_axis']-pose['hub'],transform=transform)
                            self.assertGreater(margin,.005,(track,corner,height,role,margin))

    def test_one_motion_and_independent_ball_carrier_through_mirrored_travel(self):
        for track in (1.3,1.5,1.8):
            model=Model(recipe('radius_toe',track=track));poses={}
            for corner in ('RL','RR'):
                mechanism=Mechanism(model,corner);check=mechanism.inspect()
                self.assertEqual(check['degrees_of_freedom'],1)
                self.assertGreater(check['minimum_locating_lever_m'],.035)
                for height in (-.08,-.04,0,.04,.08):
                    state,pose=mechanism.solve(height);transforms=mechanism.component_transforms(state)
                    arm=transforms['trailing_arm'];upright=transforms['upright'];p=mechanism.p
                    for key in ('hinge_inner','hinge_outer'):
                        np.testing.assert_allclose((arm@np.r_[p[key],1.])[:3],p[key],atol=1e-8)
                    np.testing.assert_allclose((arm@np.r_[p['carrier_ball'],1.])[:3],(upright@np.r_[p['carrier_ball'],1.])[:3],atol=1e-7)
                    for link in mechanism.locating_links:
                        self.assertAlmostEqual(np.linalg.norm(pose[link+'_outer']-pose[link+'_inner']),np.linalg.norm(p[link+'_outer']-p[link+'_inner']),places=7)
                    if height:self.assertGreater(np.linalg.norm(arm-upright),.001)
                    poses[corner,height]=pose
            for height in (-.08,-.04,0,.04,.08):
                for key,p in poses['RL',height].items():np.testing.assert_allclose(p*[-1,1,1],poses['RR',height][key],atol=1e-7)

    def test_missing_coincident_and_redundant_joint_geometry_rejected(self):
        for defect in ('missing','axis','rod','redundant'):
            r=recipe('radius_toe');p=r['hardpoints']['RL']
            if defect=='missing':p.pop('carrier_ball')
            elif defect=='axis':p['hinge_outer']=p['hinge_inner']
            elif defect=='rod':p['tie_outer']=p['tie_inner']
            else:
                p['radius_lower_inner']=p['radius_upper_inner'];p['radius_lower_outer']=p['radius_upper_outer']
            with self.subTest(defect=defect),self.assertRaises(ValueError):Mechanism(Model(r),'RL').inspect()

    def test_graph_shares_ball_centres_and_only_one_axial_beam_per_rod(self):
        project,frame,spec,cad=fixture('radius_toe')
        next(v for v in project['Components'] if v['MvpRole']=='rl_spring_damper')['CoiloverSpring']=dict(Mode='dual_rate',MainRateNPerM=6000,TenderRateNPerM=3000,CrossoverCompressionM=.02)
        with patch.object(c,'read_geometry',side_effect=cad):graph,part,corners,checks,*_=generate(project,frame,spec)
        nodes=node_table(part);beams=beam_table(part)
        # Node ownership can differ at common pivots; total component mass must
        # still be counted exactly once, including generated pressure wheels.
        expected=sum(cad(v)[1][0] for v in project['Components'] if v['Id']!='frame')+sum(n['mass'] for n in node_table(frame).values())
        self.assertAlmostEqual(sum(n['mass'] for n in nodes.values())+sum(w['wheel_mass_kg'] for w in corners.values()),expected,places=6)
        for corner in ('RL','RR'):
            prefix=corner.lower();ids=corners[corner]['hardpoint_nodes'];ball=ids['carrier_ball']
            self.assertIn(ball,graph.groups[prefix+'_trailing_arm']);self.assertIn(ball,graph.groups[prefix+'_upright'])
            self.assertNotIn(corners[corner]['nodes']['axis_in'],graph.groups[prefix+'_trailing_arm'])
            self.assertEqual(checks[corner]['degrees_of_freedom'],1)
            for key,suffix in [('radius_upper','upper_radius_rod'),('radius_lower','lower_radius_rod'),('tie','toe_link')]:
                owner=prefix+'_'+suffix;ends={ids[key+'_inner'],ids[key+'_outer']}
                self.assertEqual(sum({b['a'],b['b']}==ends for b in beams),1)
                joints=[j for j in graph.joints if j.get('child')==owner and j['kind']=='shared_ball']
                self.assertEqual(len(joints),2);self.assertTrue(all(j['kind']=='shared_ball' and len(j['nodes'])==1 for j in joints))
                self.assertEqual(set(graph.mass_allocations[owner]),ends)
                self.assertNotIn(owner,spec['fixed_mounts'])
            self.assertGreater(corners[corner]['effective_sprung_mass_kg'],0)
        self.assertEqual(len(part['hydros'])-1,2)
        self.assertEqual(corners['RL']['coilover_spring']['initial_rate_n_m'],2000)
        self.assertNotIn('coilover_spring',corners['RR'])
        plan=frame_mount_plan(spec,project['Components'])
        self.assertTrue(all(plan['RL_'+key]['mode']=='joint' for key in ('hinge_inner','hinge_outer','radius_upper_inner','radius_lower_inner','tie_inner')))

    def test_choice_adds_roles_and_correct_hardpoints_without_changing_default(self):
        catalog=json.loads((ROOT/'beamng.cad/FramePipeline/template_catalog.json').read_text())
        base=dict(Components=[]);selected,old,_=configuration(catalog,base)
        self.assertEqual(selected['rear_suspension']['id'],'trailing_arm')
        project=base|dict(MvpTemplates=[dict(Category='rear_suspension',Template='trailing_radius_toe')])
        _,active,links=configuration(catalog,project)
        for corner in ('rl','rr'):
            self.assertIn(corner+'_upper_radius_rod',active);self.assertNotIn(corner+'_upper_radius_rod',old)
            self.assertIn(corner+'_upright',active);self.assertNotIn(corner+'_upper_wishbone',active)
        roles={r['id']:r for r in inventory(project)['roles']}
        self.assertIn('carrier_joint',roles['rl_trailing_arm']['hardpoints'])
        self.assertNotIn('hub_center',roles['rl_trailing_arm']['hardpoints'])
        self.assertIn('upper_radius_joint',roles['rl_upright']['hardpoints'])
        self.assertEqual(sum(r['kind']=='ball_joint' and r['to_role'].startswith(('rl_','rr_')) for r in links),14)


if __name__=='__main__':unittest.main()
