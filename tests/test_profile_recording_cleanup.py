import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('cleanup',Path(__file__).resolve().parents[1]/'tools/clean-archived-profile-recordings.py')
cleanup=importlib.util.module_from_spec(spec);spec.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def test_requires_identity_and_identical_archive_and_preserves_failed_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profile';profile.mkdir();(profile/'.frame-harness-owned').touch()
            run=profile/'current/settings/vehicle_harness/results/job';run.mkdir(parents=True)
            archive=root/'archives/failed';archive.mkdir(parents=True)
            status=dict(job_id='job',session_id='session',done=True,success=False)
            for folder in (run,archive):
                (folder/'capture_status.json').write_text(json.dumps(status))
                (folder/'motion.json').write_text('original measurements')
            (run/'unarchived.json').write_text('keep')
            (run/'changed.json').write_text('new');(archive/'changed.json').write_text('old')
            preview=cleanup.clean(profile,archive.parent,root/'preview.json')
            self.assertEqual(preview['files'],2);self.assertTrue((run/'motion.json').exists())
            result=cleanup.clean(profile,archive.parent,root/'applied.json',True)
            self.assertEqual(result['files'],2)
            self.assertFalse((run/'motion.json').exists());self.assertTrue((archive/'motion.json').exists())
            self.assertTrue((run/'unarchived.json').exists());self.assertTrue((run/'changed.json').exists())

    def test_foreign_session_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profile';profile.mkdir();(profile/'.frame-harness-owned').touch()
            run=profile/'current/settings/vehicle_harness/results/job';run.mkdir(parents=True)
            archive=root/'archives/run';archive.mkdir(parents=True)
            for folder,session in ((run,'old'),(archive,'new')):
                (folder/'capture_status.json').write_text(json.dumps(dict(job_id='job',session_id=session)))
                (folder/'motion.json').write_text('identical')
            self.assertEqual(cleanup.clean(profile,archive.parent,root/'audit.json',True)['files'],0)
            self.assertTrue((run/'motion.json').exists())


if __name__=='__main__':unittest.main()
