import copy,itertools,unittest
import numpy as np
from frame_harness.torsion import angle,gradient,columns,add_frame_bracing,table
from frame_harness.calibration import graph_identity,graph_response
from frame_harness.models import TestScenario


class TorsionTests(unittest.TestCase):
    def test_fixed_mount_has_local_angular_paths_without_new_nodes(self):
        xyz=list(itertools.product((-1.,1.),repeat=3))+[(.3,.3,.3),(-.3,-.3,.3),(-.3,.3,-.3),(.3,-.3,-.3)]
        part=dict(nodes=[['id','posX','posY','posZ']]+[[str(i),*p] for i,p in enumerate(xyz)],beams=[['id1:','id2:']],
                  cadMountPatches={'housing':dict(mode='direct',frame_supports=['8','9','10','11'])})
        before=copy.deepcopy(part['nodes']);report=add_frame_bracing(part)
        self.assertEqual(part['nodes'],before);self.assertEqual(report['local_mount_count'],6)
        local=[bar for bar in table(part) if set(bar['nodes'])=={'8','9','10','11'}]
        self.assertEqual(len(local),6)
        cols=columns(np.array(xyz),[[int(n) for n in bar['nodes']] for bar in local])
        self.assertGreater(np.linalg.matrix_rank(cols),1)
        for axis in np.eye(3):np.testing.assert_allclose(cols.T@np.cross(axis,xyz).ravel(),0,atol=1e-8)

    def test_known_unit_levers_have_torque_stiffness_and_rigid_nullspace(self):
        xyz=np.array([[0.,1,0],[0,0,0],[1,0,0],[1,1,0]])
        g=gradient(xyz);np.testing.assert_allclose(g.sum(axis=0),0,atol=1e-9)
        np.testing.assert_allclose(np.cross(xyz,g).sum(axis=0),0,atol=1e-9)
        # A rotation of the final unit lever about X changes theta one-for-one.
        rotated=xyz.copy();theta=.001;rotated[3]=[1,np.cos(theta),np.sin(theta)]
        self.assertAlmostEqual(angle(rotated)-angle(xyz),theta,places=10)
        self.assertAlmostEqual(g[3,2],1.,places=8)
        # The sole free normal coordinate has compliance 1/(100 Nm/rad).
        angular=columns(xyz,[[0,1,2,3]])
        stiffness=(angular*100)@angular.T
        self.assertAlmostEqual(1/stiffness[11,11],.01,places=10)
        displaced=xyz.copy();displaced[3,2]=1e-5
        self.assertAlmostEqual(float(angular[:,0]@(displaced-xyz).ravel()),angle(displaced),places=12)

    def test_degenerate_levers_rejected(self):
        xyz=np.array([[0.,0,0],[1,0,0],[2,0,0],[3,0,0]])
        with self.assertRaisesRegex(ValueError,'Degenerate'):columns(xyz,[[0,1,2,3]])

    def test_generated_bracing_is_sealed_with_native_break_paths(self):
        xyz=np.array(list(itertools.product((-1.,1.),repeat=3))+[[.2,.3,.4]])
        part=dict(nodes=[['id','posX','posY','posZ']]+[[str(i),*p] for i,p in enumerate(xyz)],beams=[['id1:','id2:']])
        report=add_frame_bracing(part);self.assertGreater(report['count'],0)
        edges={frozenset(r[:2]) for r in part['beams'][1:]}
        for bar in table(part):
            self.assertEqual(len(set(bar['nodes'])),4)
            for a,b in zip(bar['nodes'],bar['nodes'][1:]):self.assertIn(frozenset([a,b]),edges)
        altered=copy.deepcopy(part);altered['torsionbars'].pop()
        self.assertNotEqual(graph_identity(part),graph_identity(altered))
        indices=[[int(n) for n in t['nodes']] for t in table(part)]
        matrix=columns(xyz,indices)
        for shift in np.eye(3):np.testing.assert_allclose(matrix.T@np.tile(shift,len(xyz)),0,atol=1e-8)
        for axis in np.eye(3):np.testing.assert_allclose(matrix.T@np.cross(axis,xyz).ravel(),0,atol=1e-8)


if __name__=='__main__':unittest.main()
