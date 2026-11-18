import sys,tempfile,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from compact_rigid import generate
from frame_harness.build import node_table
from test_components import box_geometry
import components


class CompactTests(unittest.TestCase):
    def test_small_body_preserves_cad_moments_and_mounts_with_nine_nodes(self):
        mass=.77;center=np.array([1.,2.,3.]);inertia=np.diag([.004,.008,.005])
        anchors=[dict(Id=str(i),Status='resolved',Position=(center+p).tolist()) for i,p in enumerate(np.array([[.04,0,0],[-.04,0,0],[0,.04,0]]))]
        part,report=generate(dict(Id='wheel',Name='Wheel',Template='bulk'),anchors,(mass,center,inertia))
        nodes=node_table(part);self.assertEqual(len(nodes),9)
        xyz=np.array([n['position'] for n in nodes.values()]);weights=np.array([n['mass'] for n in nodes.values()])
        self.assertAlmostEqual(weights.sum(),mass);np.testing.assert_allclose(weights@xyz/mass,center,atol=1e-10)
        actual=sum(m*(p@p*np.eye(3)-np.outer(p,p)) for m,p in zip(weights,xyz-center))
        np.testing.assert_allclose(actual,inertia,atol=1e-10)
        self.assertTrue(all(not n['options']['collision'] for n in nodes.values()))
        for a in anchors:np.testing.assert_allclose(nodes['wheel_mount_'+a['Id']]['position'],a['Position'])
        self.assertTrue(report['render_as_rigid_prop'])

    def test_preview_generation_uses_six_nodes_and_rigid_props_without_wrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);box_geometry(root/'cad',(.3,.2,.04),mass=.8)
            comp=dict(Id='control',Name='Control',Template='bulk',Method='rigid',GeometryDirectory=str(root/'cad'))
            part,report=components.generate_component(comp,[],root/'preview')
            self.assertEqual(report['nodes'],6);self.assertEqual(len(part['props']),2)
            self.assertEqual(len(part['triangles']),1)

    def test_panel_and_unresolved_mounts_are_rejected(self):
        moments=(1.,np.zeros(3),np.eye(3))
        with self.assertRaises(ValueError):generate(dict(Id='p',Name='Panel',Template='panel'),[],moments)
        with self.assertRaises(ValueError):generate(dict(Id='p',Name='P',Template='bulk'),[dict(Id='a',Status='missing')],moments)

    def test_thumbnail_is_portable_and_custom_image_is_preserved(self):
        from vehicle_thumbnail import ensure
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);box_geometry(root/'cad',(1.,2.,1.))
            project=dict(Identity=dict(namespace='test'),Components=[dict(Id='part',GeometryDirectory=str(root/'cad'))])
            contents={};ensure(contents,project)
            self.assertEqual(contents['vehicles/test/default.jpg'],contents['vehicles/test/base.jpg'])
            self.assertTrue(contents['vehicles/test/base.jpg'].startswith(b'\xff\xd8'))
            contents={'vehicles/test/default.jpg':b'custom'};ensure(contents,project)
            self.assertEqual(contents['vehicles/test/base.jpg'],b'custom')

if __name__=='__main__':unittest.main()
