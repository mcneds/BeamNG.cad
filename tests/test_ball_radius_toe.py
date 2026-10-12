"""Single chassis ball, arm radius rods, hinged upright and separate toe link."""
import copy
import unittest
from unittest.mock import patch
import numpy as np
from test_radius_toe import Model,recipe,Mechanism,fixture,c,generate,node_table,beam_table,frame_mount_plan


class BallRadiusToeTests(unittest.TestCase):
    def test_mirrored_travel_preserves_balls_rods_and_carrier_hinge(self):
        for track in (1.3,1.5,1.8):
            model=Model(recipe('ball_radius_toe',track=track));poses={}
            for corner in ('RL','RR'):
                mechanism=Mechanism(model,corner)
                self.assertEqual(mechanism.inspect()['degrees_of_freedom'],1)
                for height in (-.08,-.04,0,.04,.08):
                    state,pose=mechanism.solve(height);transforms=mechanism.component_transforms(state);p=mechanism.p
                    def move(role,key):return (transforms[role]@np.r_[p[key],1])[:3]
                    np.testing.assert_allclose(move('trailing_arm','trailing_ball'),p['trailing_ball'],atol=1e-8)
                    for key in ('carrier_axis_a','carrier_axis_b'):
                        np.testing.assert_allclose(move('trailing_arm',key),move('upright',key),atol=1e-8)
                    for link in ('radius_upper','radius_lower','tie'):
                        self.assertAlmostEqual(np.linalg.norm(pose[link+'_outer']-p[link+'_inner']),np.linalg.norm(p[link+'_outer']-p[link+'_inner']),places=7)
                        role='upright' if link=='tie' else 'trailing_arm'
                        np.testing.assert_allclose(move(role,link+'_outer'),pose[link+'_outer'],atol=1e-8)
                    poses[corner,height]=pose
            for height in (-.08,-.04,0,.04,.08):
                for key,p in poses['RL',height].items():np.testing.assert_allclose(p*[-1,1,1],poses['RR',height][key],atol=1e-7)

    def test_degenerate_carrier_and_redundant_radius_rod_rejected(self):
        for defect in ('hinge','rod'):
            r=recipe('ball_radius_toe');p=r['hardpoints']['RL']
            if defect=='hinge':p['carrier_axis_b']=p['carrier_axis_a']
            else:
                p['radius_lower_inner']=p['radius_upper_inner'];p['radius_lower_outer']=p['radius_upper_outer']
            with self.subTest(defect=defect),self.assertRaises(ValueError):Mechanism(Model(r),'RL').inspect()

    def test_graph_has_one_chassis_ball_two_shared_carrier_sites_and_correct_rod_owners(self):
        project,frame,spec,cad=fixture('ball_radius_toe')
        with patch.object(c,'read_geometry',side_effect=cad):graph,part,corners,checks,*_=generate(project,frame,spec)
        expected=sum(cad(v)[1][0] for v in project['Components'] if v['Id']!='frame')+sum(n['mass'] for n in node_table(frame).values())
        self.assertAlmostEqual(sum(n['mass'] for n in node_table(part).values())+sum(w['wheel_mass_kg'] for w in corners.values()),expected,places=6)
        beams=beam_table(part)
        for corner in ('RL','RR'):
            prefix=corner.lower();ids=corners[corner]['hardpoint_nodes'];arm=prefix+'_trailing_arm';upright=prefix+'_upright'
            for key in ('carrier_axis_a','carrier_axis_b'):
                self.assertIn(ids[key],graph.groups[arm]);self.assertIn(ids[key],graph.groups[upright])
            self.assertNotIn(corners[corner]['nodes']['axis_in'],graph.groups[arm])
            hinges=[j for j in graph.joints if j['kind']=='shared_hinge' and j['child']==upright]
            self.assertEqual(len(hinges),1);self.assertEqual(len(hinges[0]['nodes']),2)
            for key,suffix in [('radius_upper','upper_radius_rod'),('radius_lower','lower_radius_rod'),('tie','toe_link')]:
                owner=prefix+'_'+suffix;ends={ids[key+'_inner'],ids[key+'_outer']}
                self.assertEqual(sum({b['a'],b['b']}==ends for b in beams),1)
                outer=next(j for j in graph.joints if j['id']==owner+'_outer_ball_joint')
                self.assertEqual(outer['parent'],upright if key=='tie' else arm)
        plan=frame_mount_plan(spec,project['Components'])
        self.assertIn('RL_trailing_ball',plan);self.assertNotIn('RL_hinge_inner',plan)


if __name__=='__main__':unittest.main()
