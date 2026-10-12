import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from PIL import Image
from prepare_frame import write_dae, dae_materials, NS
from appearance_textures import dae_texture_assets, mesh_uvs


class TextureTests(unittest.TestCase):
    def test_packaged_texture_uvs_and_distinct_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'carbon with spaces.jpg'
            Image.new('RGB',(16,16),(60,70,80)).save(source)
            tri=[[(0,0,0),(.1,0,0),(0,.1,0)]]*2
            appearance=dict(BaseColor=[1,1,1,1],Roughness=.3,Metallic=0,TextureFile=str(source))
            record=dict(Id='panel',AppearanceGroups=[dict(StartTriangle=0,TriangleCount=1,Appearance=appearance),dict(StartTriangle=1,TriangleCount=1,Appearance={})])
            before=copy.deepcopy(record)
            with self.assertWarnsRegex(UserWarning,'100 mm'):write_dae(root/'panel.dae',[(record,tri)])
            self.assertEqual(record,before)
            textures=dae_texture_assets(root/'panel.dae');self.assertEqual(len(textures),1)
            data=(root/'panel.dae').read_bytes();materials=dae_materials(data,'vehicles/car')
            stages=[m['Stages'][0] for m in materials.values()]
            texture=next(v for v in stages if 'baseColorMap' in v)
            self.assertEqual(texture['baseColorMap'],'/vehicles/car/'+next(iter(textures)))
            tree=ET.fromstring(data);ns={'c':NS}
            uv=tree.find(".//c:source[@id='panel-uv']/c:float_array",ns)
            self.assertEqual(list(map(float,uv.text.split())),[0,0,1,0,0,1]*2)
            self.assertEqual(tree.find('.//c:triangles/c:p',ns).text,'0 0 1 1 2 2')
            source.unlink()  # Mod data remains usable without SolidWorks/library paths.
            self.assertEqual(dae_texture_assets(root/'panel.dae'),textures)
            self.assertNotIn(str(source).encode(),data)

    def test_missing_texture_and_malformed_uvs_fail(self):
        tri=[[(0,0,0),(1,0,0),(0,1,0)]]
        with self.assertRaises(ValueError):mesh_uvs(dict(TextureCoordinates=[[0,0]]),tri)
        with tempfile.TemporaryDirectory() as tmp:
            record=dict(Id='p',AppearanceGroups=[dict(StartTriangle=0,TriangleCount=1,Appearance=dict(TextureFile=str(Path(tmp)/'missing.jpg')))])
            with self.assertRaises(FileNotFoundError):write_dae(Path(tmp)/'p.dae',[(record,tri)])

    def test_supplied_uvs_survive_changed_mesh_coordinates(self):
        uv=[[0,0],[1,0],[0,1]]
        self.assertEqual(mesh_uvs(dict(TextureCoordinates=uv),[[(100,0,0),(101,0,0),(100,0,1)]]),uv)

    def test_different_texture_pixels_do_not_alias(self):
        from appearance_textures import texture_asset
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';Image.new('RGB',(16,16),'red').save(path)
            a=texture_asset(dict(TextureFile=str(path)))
            Image.new('RGB',(16,16),'blue').save(path)
            b=texture_asset(dict(TextureFile=str(path)))
            self.assertNotEqual(a[0],b[0])

    def test_frame_fracture_partition_interpolates_uvs_and_keeps_materials(self):
        import numpy as np
        from frame_harness.skin import partition_materials
        tri=np.array([[[-2.,0,0],[2,0,0],[0,2,0]], [[-2.,0,1],[2,0,1],[0,2,1]]])
        with tempfile.TemporaryDirectory() as tmp:
            record=dict(Id='body',TextureCoordinates=(tri[:,:,:2]*.5).reshape(-1,2).tolist(),AppearanceGroups=[dict(StartTriangle=i,TriangleCount=1,Appearance=dict(BaseColor=[i,0,0,1])) for i in range(2)])
            path=Path(tmp)/'frame.dae';write_dae(path,[(record,tri)])
            tag=lambda n:'{'+NS+'}'+n
            geo=ET.parse(path).find('.//'+tag('geometry'))
            pieces=list(partition_materials(geo,tri,np.array([[-1.,0,0],[1.,0,0]]),tag))
            self.assertEqual({p[4] for p in pieces},{'slot_0','slot_1'})
            for _,_,points,uvs,_ in pieces:np.testing.assert_allclose(uvs,points[:,:,:2]*.5)

if __name__=='__main__':unittest.main()
