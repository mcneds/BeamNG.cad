import importlib.util
import json
import math
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import patch, Mock
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
spec=importlib.util.spec_from_file_location('prepare',ROOT/'beamng.cad/FramePipeline/prepare_frame.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)

class PreparationTests(unittest.TestCase):
    def test_face_appearances_bind_to_exact_triangles_and_beamng_materials(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'colored.dae';tri=[[(0,0,0),(1,0,0),(0,1,0)],[(0,0,1),(1,0,1),(0,1,1)]]
            colors=[[.8,.1,.2,1],[.1,.3,.9,.4]]
            record=dict(Id='same_body',AppearanceGroups=[dict(StartTriangle=i,TriangleCount=1,Appearance=dict(BaseColor=color,Roughness=.3,Metallic=.7)) for i,color in enumerate(colors)])
            prepare.write_dae(path,[(record,tri)]);data=path.read_bytes();tree=ET.fromstring(data);ns={'c':prepare.NS}
            self.assertEqual(tree.find('.//c:visual_scene/c:node',ns).get('name'),'same_body')
            self.assertEqual([r.find('c:p',ns).text for r in tree.findall('.//c:triangles',ns)],['0 1 2','3 4 5'])
            definitions=prepare.dae_materials(data)
            self.assertEqual([v['Stages'][0]['baseColorFactor'] for v in definitions.values()],colors)
            for value in definitions.values():self.assertEqual(value['Stages'][0]['metallicFactor'],.7)
            self.assertTrue(list(definitions.values())[1]['translucent'])
            targets={m.get('target')[1:] for m in tree.findall('.//c:instance_material',ns)}
            self.assertEqual(targets,set(definitions))
            # Packaging can namespace every identifier. Definitions must use those final names.
            renamed=data.replace(b'cad_appearance_',b'vehicle__cad_appearance_')
            self.assertTrue(all(n.startswith('vehicle__') for n in prepare.dae_materials(renamed)))

    def test_bad_appearance_ranges_and_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for groups in ([],[dict(StartTriangle=1,TriangleCount=1,Appearance={})],
                           [dict(StartTriangle=0,TriangleCount=2,Appearance={})],
                           [dict(StartTriangle=0,TriangleCount=1,Appearance=dict(BaseColor=[float('nan'),0,0,1]))]):
                with self.assertRaises(ValueError):prepare.write_dae(Path(folder)/'bad.dae',[(dict(Id='a',AppearanceGroups=groups),[[(0,0,0),(1,0,0),(0,1,0)]])])
    def test_fixed_convention_basis_origin_and_validation(self):
        self.assertEqual(prepare.rotate((0,0,0),'X-ZY'),(0,0,0))
        self.assertEqual(prepare.rotate((1,0,0),'X-ZY'),(1,0,0))
        self.assertEqual(prepare.rotate((0,1,0),'X-ZY'),(0,0,1))
        self.assertEqual(prepare.rotate((0,0,1),'X-ZY'),(0,-1,0))
        hull=dict(Width=3,Height=5,Length=7,Offset=.01,Weld=.15,ProxyDivisor=7,Symmetry=False,
                  Orientation='X-ZY',CoordinateConvention=prepare.COORDINATE_CONVENTION)
        prepare.validate_hull(hull)
        with self.assertRaisesRegex(ValueError,'inconsistent mapping'):
            prepare.validate_hull(dict(hull,Orientation='XYZ'))
    def test_mesh_and_dae_share_coordinates_and_body_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tri=[[(1,2,3),(4,2,3),(1,6,3)]]
            prepare.write_stl(root/'frame.stl',tri)
            rotated=prepare.read_stl(root/'frame.stl','X-ZY')
            self.assertEqual(rotated,[[(1,-3,2),(4,-3,2),(1,-3,6)]])
            prepare.write_dae(root/'frame.dae',[({'Id':'instance_a'},rotated),({'Id':'instance_b'},tri)])
            tree=ET.parse(root/'frame.dae');ns={'c':prepare.NS}
            self.assertEqual([n.attrib['name'] for n in tree.findall('.//c:visual_scene/c:node',ns)],['instance_a','instance_b'])
            values=list(map(float,tree.find('.//c:float_array',ns).text.split()))
            self.assertEqual(values,[v for triangle in rotated for point in triangle for v in point])
            self.assertEqual(tree.find('.//c:unit',ns).attrib['meter'],'1')
    def test_rotations_preserve_distances_and_handedness(self):
        for mapping in ('XYZ','X-ZY','-ZYX'):
            a=prepare.rotate((1,2,3),mapping);b=prepare.rotate((4,6,3),mapping)
            self.assertAlmostEqual(math.dist(a,b),5)
            x,y,z=[prepare.rotate(v,mapping) for v in ((1,0,0),(0,1,0),(0,0,1))]
            self.assertEqual(sum(x[i]*(y[(i+1)%3]*z[(i+2)%3]-y[(i+2)%3]*z[(i+1)%3]) for i in range(3)),1)
    def test_rank_preserves_rigid_body_nullspace(self):
        # Nearly parallel directions previously became false independent constraints.
        import sys
        spec=importlib.util.spec_from_file_location('shell',ROOT/'beamng.cad/FramePipeline/generation/JBeamShellGenerator.py')
        shell=importlib.util.module_from_spec(spec);sys.modules[spec.name]=shell;spec.loader.exec_module(shell)
        points=[shell.Vec3(x,y,z) for x,y,z in ((0,0,0),(1,0,0),(0,1,0),(0,0,1),(1,1,1e-7),(1,1,1))]
        edges=[(a,b) for a in range(len(points)) for b in range(a+1,len(points))]
        report=shell.rigidity_report(points,edges)
        self.assertEqual(report['rank'],12);self.assertEqual(report['nullity'],6)
        self.assertEqual(shell.matrix_rank([[1,0,0],[1,1e-12,0],[0,0,1]],3),2)

    def test_invalid_hull_inputs(self):
        hull=dict(Width=3,Height=5,Length=7,Offset=.01,Weld=.15,ProxyDivisor=7,Symmetry=False,Orientation='XYZ')
        prepare.validate_hull(hull)
        for change in ({'Width':0},{'Symmetry':True,'Width':4},{'Weld':float('nan')},{'ProxyDivisor':0},{'Orientation':'unknown'},
                       {'ProxyOffsetRatio':0},{'ProxyOffsetRatio':float('inf')},{'SymmetryMergeDistance':-1},
                       {'SymmetryBisectFlip':'false'},{'Symmetry':1},{'Offset':True}):
            with self.assertRaises(ValueError):prepare.validate_hull(dict(hull,**change))
    def test_legacy_hull_defaults_and_explicit_advanced_values(self):
        old=dict(Width=3,Height=5,Length=7,Offset=.01,Weld=.15,ProxyDivisor=7,Symmetry=False,Orientation='XYZ')
        prepare.validate_hull(old)
        self.assertEqual((old['ProxyOffsetRatio'],old['SymmetryBisectFlip'],old['SymmetryMergeDistance']),(100,False,.0001))
        advanced=dict(old,ProxyOffsetRatio=42,SymmetryBisectFlip=True,SymmetryMergeDistance=0)
        prepare.validate_hull(advanced)
        self.assertEqual((advanced['ProxyOffsetRatio'],advanced['SymmetryBisectFlip'],advanced['SymmetryMergeDistance']),(42,True,0))

    def test_worker_passes_hull_settings_to_generator(self):
        hull=dict(Width=9,Height=8,Length=13,Offset=.025,Weld=.03,ProxyDivisor=11,
                  ProxyOffsetRatio=45,Symmetry=True,SymmetryBisectFlip=True,SymmetryMergeDistance=.002)
        with tempfile.TemporaryDirectory() as folder:
            job=Path(folder)/'job.json'
            job.write_text(json.dumps(dict(frame='selected.stl',off='preview.off',cgal='python.exe',hull=hull)))
            generator=SimpleNamespace(main=Mock())
            module_spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
            with patch.object(sys,'argv',['blender','--',str(job)]), \
                 patch('importlib.util.spec_from_file_location',return_value=module_spec), \
                 patch('importlib.util.module_from_spec',return_value=generator):
                runpy.run_path(str(ROOT/'beamng.cad/FramePipeline/alpha_worker.py'),run_name='__main__')
            generator.main.assert_called_once_with()
            for setting,constant in dict(Width='GRID_I',Height='GRID_J',Length='GRID_K',Offset='GRID_SHRINK_OFFSET',
                    Weld='GRID_WELD_DISTANCE',ProxyDivisor='PRUNING_PROXY_DIVISOR',ProxyOffsetRatio='PRUNING_PROXY_OFFSET_RATIO',
                    Symmetry='ENFORCE_X_SYMMETRY',SymmetryBisectFlip='SYMMETRY_BISECT_FLIP',SymmetryMergeDistance='SYMMETRY_MERGE_DISTANCE').items():
                self.assertEqual(getattr(generator,constant),hull[setting],setting)
    def test_stl_rejects_empty_truncated_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mesh.stl'
            for data in (b'bad',b' '*80+struct.pack('<I',1),b' '*80+struct.pack('<I',0)):
                path.write_bytes(data)
                with self.assertRaises(ValueError):prepare.read_stl(path)
            prepare.write_stl(path,[[(float('nan'),0,0),(1,0,0),(0,1,0)]])
            with self.assertRaises(ValueError):prepare.read_stl(path)

if __name__=='__main__': unittest.main()
