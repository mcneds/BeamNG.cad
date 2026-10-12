import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from mass_motion import motion_cost,normalized_inertia_cost,coupled_motion_cost,pose_offsets


class MassMotionTests(unittest.TestCase):
    def test_operating_envelope_is_explicit_and_bounded(self):
        self.assertEqual(pose_offsets(),(-.02,-.01,0.,.01,.02))
        self.assertEqual(pose_offsets([-.08,-.04,0.,.04]),(-.08,-.04,0.,.04))
        for invalid in [[],[.01],[0.,-.02],[0.,0.],[False,0.],[0.,float('nan')],[-.16,0.]]:
            with self.assertRaises(ValueError):pose_offsets(invalid)

    def test_coupled_cost_is_invariant_to_coordinate_units_and_mixing(self):
        target=np.array([[3.,.4],[.4,1.]])
        j=np.array([[.2,1.],[1.,-.4],[.3,.7]])
        expected=np.trace(np.linalg.solve(target,j.T@j))
        self.assertAlmostEqual(normalized_inertia_cost(target,j),expected)
        basis=np.array([[1000.,.3],[0.,.01]])
        self.assertAlmostEqual(normalized_inertia_cost(basis.T@target@basis,j@basis),expected,places=9)
        self.assertAlmostEqual(normalized_inertia_cost(target,2*j),4*expected)
        for bad in [np.zeros((2,2)),np.diag([-1.,2.]),np.full((2,2),np.nan)]:
            with self.assertRaises(ValueError):normalized_inertia_cost(bad,j)

    def test_coupled_reference_hashes_ownership_and_unmapped_nodes(self):
        import tempfile,json,hashlib
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);(folder/'geometry.json').write_text('{}');digest=hashlib.sha256(b'{}').hexdigest()
            roles={f'{c}_{s}':f'{c}_{s}' for c in ['fl','fr'] for s in ['upper_wishbone','lower_wishbone','upright']}
            m=dict(template_definition={},component_roles=roles,chassis_nodes=[],alignment={},
                nodes={o:dict(position=[1.,0.,0.],mass_kg=2.) for o in roles},mass_allocations={o:{o:1.} for o in roles},
                geometry_inputs_sha256={o:{'geometry.json':digest} for o in roles},component_reports={o:dict(target_mass_kg=2.,target_com_m=[1.,0.,0.]) for o in roles})
            project=folder/'project.json';project.write_text(json.dumps({'Components':[dict(Id=o,MvpRole=r,GeometryDirectory=str(folder)) for o,r in roles.items()]}))
            class MechanismStub:
                def __init__(self,*args):self.p={'hub':np.zeros(3)}
                def constraints(self,*args):return np.zeros(1)
                def solve(self,h,e):return (h,e),{'hub':np.array([0.,0.,h])}
                def component_transforms(self,pose,e):
                    t=np.eye(4);t[:3,:3]=Rotation.from_rotvec([0,e,0]).as_matrix();t[2,3]=pose[0]
                    return dict.fromkeys(['upper_arm','lower_arm','upright'],t)
            with patch('mass_motion.TemplateModel'),patch('mass_motion.Mechanism',MechanismStub),patch('mass_motion.ride_reference',return_value=(0.,0.,'test')),patch('components.read_geometry',return_value=([],(2.,np.array([1.,0.,0.]),np.eye(3)),{})):
                costs,report=coupled_motion_cost(m,list(roles),project)
                # Each corner has three 2 kg reference bodies; each added node
                # allocates half its increment to a covered body.
                np.testing.assert_allclose(list(costs.values()),[1/12]*6,rtol=1e-7)
                self.assertEqual(report['objective'],'mean_normalized_inertia_trace')
                expanded,details=coupled_motion_cost(m,list(roles),project,travel_offsets=[-.08,0.,.04])
                np.testing.assert_allclose(list(expanded.values()),list(costs.values()),rtol=1e-7)
                self.assertEqual(details['travel_offsets_m'],[-.08,0.,.04])
                with self.assertRaisesRegex(ValueError,'No coupled'):coupled_motion_cost(m,['missing'],project)
                (folder/'geometry.json').write_text('changed')
                with self.assertRaisesRegex(ValueError,'geometry/material'):coupled_motion_cost(m,list(roles),project)

    def fixture(self,transform=None):
        world=np.eye(4) if transform is None else transform
        points={'pivot':[0.,0.,0.],'middle':[0.,.3,0.],'tip':[0.,.6,0.]}
        m=dict(template_definition={},component_roles={'arm':'fl_upper_wishbone'},chassis_nodes=['pivot'],
               nodes={n:{'position':(world@np.r_[p,1])[:3]} for n,p in points.items()},
               mass_allocations={'arm':dict.fromkeys(points,1.)},wheels={c:{'hardpoint_nodes':{}} for c in ('FL','FR')})
        class Hinge:
            def __init__(self,*args):pass
            def solve(self,h,extension):return np.arcsin(h/.6),{}
            def component_transforms(self,angle,extension):
                matrix=np.eye(4);matrix[:3,:3]=Rotation.from_rotvec([angle,0,0]).as_matrix()
                return {'upper_arm':world@matrix@np.linalg.inv(world)}
        return m,Hinge

    def calculate(self,m,hinge,names):
        with patch('mass_motion.TemplateModel',return_value=object()),patch('mass_motion.Mechanism',hinge),patch('mass_motion.ride_reference',return_value=(0.,0.,'test')):
            return motion_cost(m,names)[0]

    def test_hinge_kinetic_weight_is_square_of_motion_ratio(self):
        m,h=self.fixture();cost=self.calculate(m,h,list(m['nodes']))
        self.assertAlmostEqual(cost['pivot'],0.);self.assertAlmostEqual(cost['middle'],.25,places=8);self.assertAlmostEqual(cost['tip'],1.,places=8)

    def test_world_rotation_and_translation_do_not_change_kinetic_cost(self):
        world=np.eye(4);world[:3,:3]=Rotation.from_rotvec([.4,-.2,.7]).as_matrix();world[:3,3]=[2,-3,1]
        m,h=self.fixture(world);cost=self.calculate(m,h,list(m['nodes']))
        np.testing.assert_allclose([cost[n] for n in ('pivot','middle','tip')],[0.,.25,1.],atol=1e-8)

    def test_unmapped_or_moving_chassis_nodes_are_rejected(self):
        m,h=self.fixture()
        with self.assertRaisesRegex(ValueError,'No kinematic'):self.calculate(m,h,['unknown'])
        m['chassis_nodes'].append('tip')
        with self.assertRaisesRegex(ValueError,'Chassis node moves'):self.calculate(m,h,['tip'])


if __name__=='__main__':unittest.main()
