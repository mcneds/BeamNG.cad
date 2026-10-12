import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('material_study',Path(__file__).parents[1]/'tools/prepare-material-study.py')
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)


class MaterialStudyTests(unittest.TestCase):
    def fixture(self, root):
        geometry=root/'geometry';geometry.mkdir();(geometry/'body.stl').write_bytes(b'unchanged mesh')
        database=root/'materials.sldmat';database.write_text('catalog')
        study.write(root/'catalog.json',[dict(name='Steel',database=str(database),database_sha256=study.digest(database),density_kg_m3=7850)])
        study.write(geometry/'geometry.json',dict(Meshes=[dict(Id='body',File='body.stl',BodyKind='solid',MassKg=1.,NativeUnitDensityProperties=[0,0,0,.001])]))
        study.write(geometry/'material-snapshot.json',dict(bodies=[dict(body_id='body',body='Body',component='part',configuration='Default',name=None)]))
        study.write(root/'template.json',dict(kind='vehicle_template',diagnostic_assumptions=[]))
        study.write(root/'project.json',dict(Components=[dict(Id='part',Name='Part',GeometryDirectory=str(geometry))],TemplateDefinitionPath=str(root/'template.json'),LastBuildReceipt='old'))
        study.write(root/'plan.json',dict(reason='Declared material; native assignment pending',bodies={'body':'Steel'}))
        return [root/n for n in ('project.json','plan.json','catalog.json','output')]

    def test_provenance_and_geometry_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);args=self.fixture(root)
            before={p:study.digest(p) for p in root.rglob('*') if p.is_file()}
            study.prepare(*args)
            self.assertTrue(all(study.digest(p)==value for p,value in before.items()))
            folder=root/'output/geometry/part'
            self.assertEqual(study.read(folder/'geometry.json')['Meshes'][0]['MassKg'],7.8500000000000005)
            self.assertEqual((folder/'body.stl').read_bytes(),b'unchanged mesh')
            self.assertFalse(study.read(folder/'material-snapshot.json')['bodies'][0]['native_readback_verified'])
            self.assertFalse(study.read(root/'output/material-study.json')['qualified'])
            self.assertIn('not a fully native-material-qualified',study.read(root/'output/template.json')['diagnostic_assumptions'][0])
            self.assertEqual(study.read(root/'output/project.json')['LastBuildReceipt'],'')

    def test_unknown_body_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);args=self.fixture(root)
            study.write(args[1],dict(reason='explicit',bodies={'missing':'Steel'}))
            with self.assertRaisesRegex(ValueError,'Unknown'):study.prepare(*args)
            self.assertFalse(args[-1].exists())

    def test_changed_library_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);args=self.fixture(root);(root/'materials.sldmat').write_text('changed')
            with self.assertRaisesRegex(ValueError,'library changed'):study.prepare(*args)
            self.assertFalse(args[-1].exists())


if __name__=='__main__':unittest.main()
