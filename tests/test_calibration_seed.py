import copy,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.calibration import make_candidate,run_calibration
from frame_harness.build import SOURCES,write_json,spring_fixture
from frame_harness.models import HarnessProject,ParameterSet


class CalibrationSeedTests(unittest.TestCase):
    def test_stop_target_cannot_relax_acceptance(self):
        for target in (0,.1,float('nan'),float('inf')):
            with self.subTest(target=target),self.assertRaisesRegex(ValueError,'at most 8%'):
                make_candidate(None,None,None,None,None,dict(elastic_fit_target_error=target))

    def test_seed_is_sealed_input_and_remains_subject_to_normal_result(self):
        for name in ('mochi_raw.jbeam','not-sealed.jbeam','../outside.jbeam'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source=root/'source';source.mkdir()
                for file in SOURCES:(source/file).write_text('asset')
                part=spring_fixture(ParameterSet())['mochi'];write_json(source/'mochi_raw.jbeam',dict(mochi=part))
                config=json.loads((ROOT/'dependencies/cad-calibration/Test Harness/examples/4130-reference.json').read_text())
                config['elastic_seed_file']=name;write_json(root/'reference.json',config)
                report=dict(mass=dict(actual_mass_kg=1,center_error_m=0,inertia_relative_error=0),offline_accepted=False)
                body=SimpleNamespace(name='a');audit=dict(name='a',valid=True,volume_m3=1,center_m=[0,0,0],inertia_per_density=np.eye(3).tolist())
                with patch('frame_harness.calibration.read_bodies',return_value=[body]), \
                     patch('frame_harness.calibration.audit_body',return_value=(body,audit)), \
                     patch('frame_harness.calibration.extract_member',side_effect=ValueError('test non-tube')), \
                     patch('frame_harness.calibration.make_candidate',return_value=(part,copy.deepcopy(report))) as make:
                    if name!='mochi_raw.jbeam':
                        with self.assertRaisesRegex(ValueError,'sealed generation source'):
                            run_calibration(HarnessProject(source=source),root/'reference.json',root/'study',live=False,case='4130-annealed')
                        make.assert_not_called()
                    else:
                        result=run_calibration(HarnessProject(source=source),root/'reference.json',root/'study',live=False,case='4130-annealed')
                        self.assertEqual(make.call_args.kwargs['elastic_seed'],part)
                        self.assertFalse(result['candidates']['4130-annealed']['offline_accepted'])

if __name__=='__main__':unittest.main()
