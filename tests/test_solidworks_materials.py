import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'beamng.cad/FramePipeline'), str(ROOT/'dependencies/cad-calibration/Test Harness')]
import numpy as np
from frame_harness.materials import load_snapshot
from frame_harness.calibration import mass_properties, run_calibration
from frame_harness.reference import build_frame
from frame_harness.build import SOURCES, write_json, spring_fixture
from frame_harness.models import HarnessProject, ParameterSet
from test_static_frame import fixture, pipeline


def material(identity='a', **values):
    return dict(body_id=identity, body=identity, component='frame', configuration='Default',
                name='Custom steel', assignment='body', database='custom.sldmat',
                database_sha256='a'*64, entry_sha256='b'*64, model='linear_isotropic',
                density_kg_m3=7800., young_pa=210e9, poisson=.28, shear_pa=79e9,
                yield_pa=220e6, ultimate_pa=400e6, **values)


class MaterialTests(unittest.TestCase):
    def snapshot(self, root, records):
        path=root/'material-snapshot.json'
        write_json(path, dict(format='solidworks-body-materials', version=1, units='SI', bodies=records))
        return path

    def test_exact_body_coverage_and_missing_properties(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a=material(); b=material('b')
            b.update(name='Aluminium', density_kg_m3=2700, young_pa=69e9)
            path=self.snapshot(root,[a,b]); result=load_snapshot(path,['a','b'])
            self.assertEqual(result['a']['density_kg_m3'],7800)
            self.assertEqual(result['b']['young_pa'],69e9)
            with self.assertRaisesRegex(ValueError,'exactly cover'):load_snapshot(path,['a'])
            b.pop('yield_pa'); a['error']='No SolidWorks material assigned'
            path=self.snapshot(root,[a,b])
            with self.assertRaises(ValueError) as error:load_snapshot(path)
            self.assertIn('frame / a: No SolidWorks material assigned',str(error.exception))
            self.assertIn('frame / b: missing/invalid material property yield_pa',str(error.exception))

    def test_invalid_models_properties_and_duplicate_identity_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for key,value in [('model','orthotropic'),('young_pa',float('nan')),('poisson',.5),
                              ('ultimate_pa',1),('database_sha256',''),('density_kg_m3',True)]:
                with self.subTest(key=key):
                    row=material();row[key]=value
                    with self.assertRaises(ValueError):load_snapshot(self.snapshot(Path(folder),[row]))
            with self.assertRaisesRegex(ValueError,'duplicate'):
                load_snapshot(self.snapshot(Path(folder),[material(),material()]))

    def test_mixed_density_mass_center_and_inertia(self):
        audits=[dict(volume_m3=1,center_m=[0,0,0],inertia_per_density=np.eye(3)/6),
                dict(volume_m3=1,center_m=[2,0,0],inertia_per_density=np.eye(3)/6)]
        mass,center,inertia=mass_properties(audits,[2,1])
        self.assertEqual(mass,3)
        np.testing.assert_allclose(center,[2/3,0,0])
        np.testing.assert_allclose(inertia,np.diag([.5,.5+8/3,.5+8/3]))

    def test_reference_keeps_each_members_young_and_shear_modulus(self):
        section=dict(area_m2=.01,Iy_m4=1e-5,Iz_m4=1e-5,J_m4=2e-5,radius_m=.05)
        sections={'a':dict(section,a=[0,0,0],b=[1,0,0]),'b':dict(section,a=[1,0,0],b=[2,0,0])}
        materials={'a':material(),'b':material('b')}
        materials['b'].update(young_pa=70e9,shear_pa=27e9)
        frame=build_frame(sections,materials=materials)
        self.assertEqual(len(frame['elements']),2)
        for element in frame['elements']:
            values=materials[element['member']]
            self.assertAlmostEqual(element['local'][0,0],values['young_pa']*.01)
            self.assertAlmostEqual(element['local'][3,3],values['shear_pa']*2e-5)

    def test_selected_legacy_case_is_the_only_generated_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'source';source.mkdir()
            for name in SOURCES:(source/name).write_text('asset')
            part=spring_fixture(ParameterSet())['mochi'];write_json(source/'mochi_raw.jbeam',{'mochi':part})
            report=dict(mass=dict(actual_mass_kg=1,center_error_m=0,inertia_relative_error=0),offline_accepted=False)
            body=SimpleNamespace(name='a')
            audit=dict(name='a',valid=True,volume_m3=1,center_m=[0,0,0],inertia_per_density=np.eye(3).tolist())
            with patch('frame_harness.calibration.read_bodies',return_value=[body]), \
                 patch('frame_harness.calibration.audit_body',return_value=(body,audit)), \
                 patch('frame_harness.calibration.extract_member',side_effect=ValueError('synthetic non-tube')), \
                 patch('frame_harness.calibration.make_candidate',return_value=(part,report)) as make:
                result=run_calibration(HarnessProject(source=source),ROOT/'dependencies/cad-calibration/Test Harness/examples/4130-reference.json',root/'study',live=False,case='4130-normalized')
            self.assertEqual(list(result['candidates']),['4130-normalized'])
            self.assertEqual(make.call_count,1)
            self.assertFalse((root/'study/4130-annealed').exists())

    def test_uncalibrated_builder_is_removed(self):
        self.assertFalse(hasattr(pipeline, 'build'))


    def test_native_snapshot_generates_only_assigned_case(self):
        from frame_harness.generation import inputs
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir()
            for name in SOURCES:(source/name).write_text('asset')
            part=spring_fixture(ParameterSet())['mochi'];write_json(source/'mochi_raw.jbeam',{'mochi':part})
            self.snapshot(source,[material()])
            project=HarnessProject(source=source);manifest=inputs(project)
            manifest=dict(manifest,material_snapshot='material-snapshot.json',sources=list(manifest['sources'])+['material-snapshot.json'])
            config=json.loads((ROOT/'dependencies/cad-calibration/Test Harness/examples/4130-reference.json').read_text())
            config.update(material_source='solidworks',actual_condition='assigned_in_cad')
            for name in ('young_pa','poisson','density_kg_m3'):config.pop(name,None)
            reference=source/'reference.json';write_json(reference,config)
            body=SimpleNamespace(name='a');audit=dict(name='a',valid=True,volume_m3=1,center_m=[0,0,0],inertia_per_density=np.eye(3).tolist())
            report=dict(mass=dict(actual_mass_kg=1,center_error_m=0,inertia_relative_error=0),offline_accepted=False)
            with patch('frame_harness.calibration.inputs',return_value=manifest), \
                 patch('frame_harness.calibration.read_bodies',return_value=[body]), \
                 patch('frame_harness.calibration.audit_body',return_value=(body,audit)), \
                 patch('frame_harness.calibration.extract_member',side_effect=ValueError('synthetic non-tube')), \
                 patch('frame_harness.calibration.make_candidate',return_value=(part,report)) as make:
                result=run_calibration(project,reference,root/'study',live=False)
            self.assertEqual(list(result['candidates']),['solidworks-assigned'])
            self.assertEqual(make.call_count,1)
            self.assertEqual(make.call_args.args[4]['bodies']['a']['young_pa'],210e9)
            artifact=json.loads((root/'study/solidworks-assigned/calibration.json').read_text())
            self.assertIn('material-snapshot.json',artifact['source_hashes'])


if __name__=='__main__':unittest.main()
