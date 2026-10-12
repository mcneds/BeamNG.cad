import json
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Vehicle Wizard'))
from synthetic_vehicle import recipe
from synthetic_clearance import tube_wheel_clearance
from vehicle_wizard.kinematics import Mechanism


class Model:
    def __init__(self,r):
        self.r=r
        self.data={'parameters':{'travel_m':.16,'steer_degrees':28},'corners':{corner:{'template':r['templates']['front_suspension' if corner[0]=='F' else 'rear_suspension'],'links':[]} for corner in r['hardpoints']}}
    def corner_points(self,corner):return {k:np.array(v) for k,v in self.r['hardpoints'][corner].items()}


class SyntheticMechanismTests(unittest.TestCase):
    def test_both_template_sets_have_one_suspension_motion_and_reachable_travel(self):
        for variant in ('primary','independent_rear'):
            for wheelbase,track in ((1.9,1.5),(2.1,1.6),(1.5,1.3),(2.5,1.8)):
                model=Model(recipe(variant,wheelbase,track))
                for corner in model.data['corners']:
                    with self.subTest(variant=variant,corner=corner,dimensions=(wheelbase,track)):
                        check=Mechanism(model,corner).inspect()
                        self.assertEqual(check['degrees_of_freedom'],1)
                        self.assertEqual(len(check['samples']),9)
                        self.assertGreater(check['motion_ratio'],.1)
                        self.assertLess(max(abs(s['toe_deg']) for s in check['samples']),.25)
                for corner,p in model.r['hardpoints'].items():
                    if 'tie_inner' not in p:continue
                    role=corner.lower()+('_tie_rod' if corner[0]=='F' else '_toe_link')
                    shape=next(c for c in model.r['components'] if c['id']==role)['primitives'][0]
                    np.testing.assert_allclose(shape['a'],p['tie_inner']);np.testing.assert_allclose(shape['b'],p['tie_outer'])
    def test_trailing_arm_rotates_about_both_hinge_points(self):
        mechanism=Mechanism(Model(recipe()),'RL');x,pose=mechanism.solve(.08)
        _,transform=mechanism.pose(x)
        for name in ('hinge_inner','hinge_outer'):
            np.testing.assert_allclose(transform(mechanism.p[name]),mechanism.p[name],atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(pose['hub']-pose['hinge_inner']),np.linalg.norm(mechanism.p['hub']-mechanism.p['hinge_inner']))
    def test_degenerate_hinge_is_rejected(self):
        r=recipe();r['hardpoints']['RL']['hinge_outer']=r['hardpoints']['RL']['hinge_inner']
        with self.assertRaisesRegex(ValueError,'coincide'):Mechanism(Model(r),'RL').inspect()
    def test_physical_trailing_arm_clears_wheel_through_travel_and_track_range(self):
        for track in (1.3,1.5,1.8):
            r=recipe(track=track)
            for corner in ('RL','RR'):
                mechanism=Mechanism(Model(r),corner)
                shapes=next(c for c in r['components'] if c['id']==corner.lower()+'_trailing_arm')['primitives']
                for travel in np.linspace(-.08,.08,9):
                    state,pose=mechanism.solve(float(travel));_,transform=mechanism.pose(state)
                    for shape in shapes:
                        clearance=tube_wheel_clearance(shape,pose['hub'],pose['hub_axis']-pose['hub'],transform=transform)
                        self.assertGreater(clearance,.01,(track,corner,travel,shape,clearance))
                # Reproduce the original CAD error; this is a visible tube,
                # irrespective of whether constraint beams are rendered.
                old=dict(kind='tube',a=r['hardpoints'][corner]['hinge_outer'],b=r['hardpoints'][corner]['hub'],radius=.024)
                self.assertLess(tube_wheel_clearance(old,mechanism.p['hub'],mechanism.p['hub_axis']-mechanism.p['hub']),0)
    def test_recipe_identity_depends_on_geometry_and_configuration(self):
        self.assertEqual(recipe()['recipe_sha256'],recipe()['recipe_sha256'])
        self.assertNotEqual(recipe()['recipe_sha256'],recipe(wheelbase=2.1)['recipe_sha256'])
        self.assertNotEqual(recipe()['recipe_sha256'],recipe('independent_rear')['recipe_sha256'])
    def test_positive_caster_is_native_geometry_with_mirrored_reachable_linkage(self):
        r=recipe(caster_degrees=6);model=Model(r)
        self.assertNotEqual(r['recipe_sha256'],recipe()['recipe_sha256'])
        for corner in ('FL','FR'):
            p=model.corner_points(corner);axis=p['upper_ball']-p['lower_ball']
            self.assertAlmostEqual(np.degrees(np.arctan2(axis[1],axis[2])),6)
            ground=p['lower_ball']-axis*p['lower_ball'][2]/axis[2]
            self.assertLess(ground[1],p['hub'][1])
            check=Mechanism(model,corner).inspect()
            self.assertEqual(check['degrees_of_freedom'],1)
            self.assertLess(max(abs(s['toe_deg']) for s in check['samples']),.25)
            shape=next(c for c in r['components'] if c['id']==corner.lower()+'_upright')['primitives'][0]
            np.testing.assert_allclose(shape['b'],p['upper_ball'])
        for name,point in model.corner_points('FL').items():
            np.testing.assert_allclose(point*[-1,1,1],model.corner_points('FR')[name])


if __name__=='__main__':unittest.main()
