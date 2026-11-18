import copy,sys,unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from steering_visuals import fit,transform,fingerprint
from rigid_visuals import render

def rim():
    angles=np.linspace(0,2*np.pi,96,endpoint=False);triangles=[]
    for i,a in enumerate(angles):
        b=angles[(i+1)%len(angles)]
        for z in [-.008,.008]:
            p=lambda r,t:[r*np.cos(t),r*np.sin(t),z]
            triangles.extend([[p(.15,a),p(.15,b),p(.13,a)],[p(.13,a),p(.15,b),p(.13,b)]])
    basis=Rotation.from_euler('xyz',[70,0,10],degrees=True).as_matrix()
    return [(dict(Id='wheel'),np.array(triangles)@basis.T+[.1,.5,.7])]

class SteeringVisualTests(unittest.TestCase):
    def test_visual_diagnostic_does_not_expand_full_driving_acceptance(self):
        from frame_harness.vehicle import SCENARIOS,DIAGNOSTIC_SCENARIOS
        self.assertEqual(len(SCENARIOS)*3,24)
        self.assertNotIn('steering_visual',SCENARIOS)
        self.assertIn('steering_visual',DIAGNOSTIC_SCENARIOS)
    def test_fit_preserves_neutral_pose_and_rotates_about_pivot(self):
        meshes=rim();s=fit(meshes);p,b,r=transform(s,meshes)
        np.testing.assert_allclose(p,[.1,.5,.7],atol=1e-8)
        np.testing.assert_allclose(Rotation.from_euler('YZX',[r['y'],r['z'],r['x']],degrees=True).as_matrix(),b,atol=1e-12)
        local=(meshes[0][1]-p)@b
        np.testing.assert_allclose(local@b.T+p,meshes[0][1],atol=1e-12)
        rotated=local@Rotation.from_euler('z',-90,degrees=True).as_matrix().T@b.T+p
        np.testing.assert_allclose(np.linalg.norm(rotated-p,axis=2),np.linalg.norm(meshes[0][1]-p,axis=2),atol=1e-12)

    def test_animation_changes_only_props_and_retains_all_meshes(self):
        meshes=rim();s=fit(meshes)
        part=dict(nodes=[['id','posX','posY','posZ'],['a',0,0,0,dict(nodeWeight=1)],['b',1,0,0,dict(nodeWeight=1)],['c',0,1,0,dict(nodeWeight=1)]],beams=[['id1:','id2:'],['a','b',dict(beamSpring=100)]])
        before=copy.deepcopy(part)
        _,report=render('wheel',part,dict(wheel=dict(a=1,b=1,c=1)),meshes,['wheel'],s)
        self.assertEqual(part['nodes'],before['nodes']);self.assertEqual(part['beams'],before['beams'])
        self.assertEqual(part['props'][1][0],'steering');self.assertEqual(report['steering']['electric'],'steering')
        self.assertEqual(part['props'][1][6],dict(x=0,y=0,z=1))

    def test_stale_and_degenerate_contracts_fail_closed(self):
        meshes=rim();s=fit(meshes)
        with self.assertRaisesRegex(ValueError,'changed'):transform(s,[(meshes[0][0],meshes[0][1]+.01)])
        s['Axis']=[0,0,0]
        with self.assertRaisesRegex(ValueError,'axis'):transform(s,meshes)
        points=np.random.default_rng(1).normal(size=(100,3,3))
        with self.assertRaisesRegex(ValueError,'plane'):fit([({},points)])

    def test_native_probe_detects_wrong_sign_and_orbit(self):
        from steering_visual_probe import pose_error
        rest=np.array([[0.,0,0],[1,0,0],[0,1,0]])
        manifest=dict(nodes={n:dict(position=p.tolist()) for n,p in zip('abc',rest)})
        s=fit(rim());pivot,basis,_=transform(s,rim());s['basis']=basis.tolist()
        binding=dict(nodes=list('abc'),steering=s)
        body=Rotation.from_euler('xyz',[.2,.1,.3]).as_matrix();translation=np.array([10.,20.,1.])
        actual=body@basis@Rotation.from_euler('z',45,degrees=True).as_matrix()
        columns=np.vstack((actual.T,body@pivot+translation))
        snapshot=dict(reference_nodes={n:(body@p+translation).tolist() for n,p in zip('abc',rest)},columns=columns.tolist(),steering_degrees=45)
        error=pose_error(binding,manifest,snapshot)
        self.assertLess(error['angle_error_deg'],1e-7);self.assertLess(error['pivot_error_m'],1e-10)
        snapshot['steering_degrees']=-45
        self.assertAlmostEqual(pose_error(binding,manifest,snapshot)['angle_error_deg'],90)
        columns[-1,0]+=.1;snapshot['columns']=columns.tolist()
        self.assertAlmostEqual(pose_error(binding,manifest,snapshot)['pivot_error_m'],.1)

if __name__=='__main__':unittest.main()
