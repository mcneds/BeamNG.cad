import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_material_refresh',ROOT/'tools/refresh-native-material-inputs.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class NativeMaterialRefreshTests(unittest.TestCase):
    def fixture(self,root):
        part=root/'arm.SLDPRT';part.write_bytes(b'native saved part')
        db=root/'native.sldmat';db.write_bytes(b'captured library')
        geo=root/'old';geo.mkdir();(geo/'body.stl').write_bytes(b'unchanged mesh')
        props=[0.,0.,0.,.01,1.,.01,.001,.001,.001,0.,0.,0.]
        mesh=dict(Id='body',Body='Arm',BodyKind='solid',SourceDocument=str(part),File='body.stl',NativeUnitDensityProperties=props,MassKg=10.)
        tool.write(geo/'geometry.json',dict(Meshes=[mesh]));body=dict(body_id='body',body='Arm',component='arm',configuration='Default',name=None,error='unassigned')
        tool.write(geo/'material-snapshot.json',dict(format='solidworks-body-materials',version=1,units='SI',bodies=[body]))
        project=root/'project.json';tool.write(project,dict(Components=[dict(Id='arm',Name='Arm',GeometryDirectory=str(geo),MassPolicy='cad')]))
        catalog=root/'catalog.json';tool.write(catalog,[dict(name='Aluminum',database=str(db),database_sha256=tool.digest(db),entry_sha256='recorded-entry',model='linear_isotropic',density_kg_m3=2700.,young_pa=69e9,poisson=.33,shear_pa=26e9,yield_pa=55e6,ultimate_pa=124e6,error=None)])
        audit=root/'audit.json';tool.write(audit,[dict(path=str(part),status='saved_and_reopened_verified',after_sha256=tool.digest(part),before=[dict(body='Arm',name=None,unit_density_properties=props)],after=[dict(body='Arm',name='Aluminum',database=str(db),assignment='inherited part',unit_density_properties=props)])])
        return project,audit,catalog,geo,part

    def test_recomputes_mass_preserving_source_archive_and_mesh(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);p,a,c,g,_=self.fixture(r);before=tool.digest(g/'geometry.json')
            report=tool.refresh(p,[a],c,r/'new');new=r/'new/geometry/arm'
            self.assertEqual(tool.read(new/'geometry.json')['Meshes'][0]['MassKg'],27.)
            self.assertEqual(tool.digest(g/'geometry.json'),before)
            self.assertEqual(tool.digest(g/'body.stl'),tool.digest(new/'body.stl'))
            self.assertEqual(report['arm']['bodies'][0]['material'],'Aluminum')

    def test_rejects_changed_source_without_creating_output(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);p,a,c,_,part=self.fixture(r);part.write_bytes(b'edited after readback')
            with self.assertRaisesRegex(ValueError,'Source part changed'):tool.refresh(p,[a],c,r/'new')
            self.assertFalse((r/'new').exists())

    def test_rejects_geometry_change_without_creating_output(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);p,a,c,_,_=self.fixture(r);data=tool.read(a);data[0]['after'][0]['unit_density_properties'][3]=.02;tool.write(a,data)
            with self.assertRaisesRegex(ValueError,'Geometry changed'):tool.refresh(p,[a],c,r/'new')
            self.assertFalse((r/'new').exists())


if __name__=='__main__':unittest.main()
