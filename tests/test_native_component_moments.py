import sys,unittest,tempfile,json
from unittest.mock import patch
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from components import native_moments,read_geometry

class NativeMomentsTests(unittest.TestCase):
    def test_native_sheet_mass_and_symmetric_thickness(self):
        record=dict(Id='sheet',File='sheet.stl',Body='Sheet',BodyKind='surface',DensityKgM3=2000,
                    NativeUnitDensityProperties=[0,0,0,4,8,4,4/3,4/3,8/3,0,0,0],
                    NativeAxesAssembly=np.eye(3).tolist(),NativeCenterAssembly=[0,0,0])
        triangles=np.array([[[-1,0,-1],[1,0,-1],[1,0,1]],[[-1,0,-1],[1,0,1],[-1,0,1]]])
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'geometry.json').write_text(json.dumps(dict(Meshes=[record])))
            with patch('components.read_stl',return_value=triangles):
                _,(mass,center,inertia),_=read_geometry(dict(GeometryDirectory=d,Thickness=.02))
        self.assertAlmostEqual(mass,160)
        np.testing.assert_allclose(center,0,atol=1e-12)
        np.testing.assert_allclose(inertia,np.diag([160*(1/3+.02**2/12),160*2/3,160*(1/3+.02**2/12)]))

    def test_products_rotation_and_translation(self):
        # A rod-like ellipsoid with an off-diagonal product, then rotate the
        # component and convert Y-up CAD into Z-up game coordinates.
        inertia=np.array([[3.,.2,.1],[.2,4.,.3],[.1,.3,5.]])
        r=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
        b=np.array([[1,0,0],[0,0,-1],[0,1,0]])
        record=dict(NativeUnitDensityProperties=[0,0,0,2,8,2,3,4,5,-.2,-.1,-.3],NativeAxesAssembly=r.T.tolist(),NativeCenterAssembly=[2,3,4])
        triangles=np.array([[[0,-6,1],[4,-2,1],[2,-4,5]]])
        center,tensor=native_moments(record,10,triangles)
        np.testing.assert_allclose(center,[2,-4,3]);np.testing.assert_allclose(tensor,b@r@inertia@r.T@b.T*5)
        record['NativeAxesAssembly'][0][0]=2
        with self.assertRaisesRegex(ValueError,'nonrigid'):native_moments(record,10,triangles)

    def test_rejects_misplaced_geometry_and_nonphysical_tensor(self):
        record=dict(NativeUnitDensityProperties=[0,0,0,1,6,1,1,1,1,0,0,0],NativeAxesAssembly=np.eye(3).tolist(),NativeCenterAssembly=[20,0,0])
        triangles=np.array([[[-1,-1,-1],[1,1,1],[1,-1,1]]])
        with self.assertRaisesRegex(ValueError,'coordinate'):native_moments(record,1,triangles)
        record['NativeCenterAssembly']=[0,0,0];record['NativeUnitDensityProperties'][6]=10
        with self.assertRaisesRegex(ValueError,'Nonphysical'):native_moments(record,1,triangles)

if __name__=='__main__':unittest.main()
