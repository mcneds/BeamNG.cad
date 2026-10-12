import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('prune',Path(__file__).resolve().parents[1]/'tools/prune-diagnostics.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


class PruningTests(unittest.TestCase):
    def test_protection_requires_whole_path_ancestors(self):
        root=Path('H:/builds').absolute();protected={root/'keep',root/'file.json'}
        for path in (root/'keep',root/'keep'/'nested'/'data.csv',root/'file.json'):
            self.assertTrue(p.covered(path,protected))
        for path in (root,root/'keep-old'/'data.csv',root/'file.json.old',root/'other'):
            self.assertFalse(p.covered(path,protected))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.policy={'roots':[str(self.root)],'retain_latest_failure':False}

    def tearDown(self):self.tmp.cleanup()

    def put(self,name,data):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data));return path

    def run_fixture(self,name='run',status='completed'):
        self.put(name+'/job.json',{'scenario':'flex'})
        self.put(name+'/result.json',{'status':status,'accepted':False})
        return self.put(name+'/motion_diagnostics.json',{'history':[1,2,3]})

    def test_protection_outcomes_and_source_geometry(self):
        raw=self.run_fixture();kept=self.run_fixture('pinned')
        cad=self.put('run/geometry/geometry.json',{})
        self.policy['keep']=[str(kept.parent)]
        before=(raw.parent/'result.json').read_bytes()
        plan=p.inventory(self.policy);p.apply(plan,self.root/'audit.json',lambda:None)
        self.assertFalse(raw.exists());self.assertTrue(kept.exists());self.assertTrue(cad.exists())
        self.assertEqual(before,(raw.parent/'result.json').read_bytes())
        self.assertFalse(p.read(raw.parent/'diagnostics-pruned.json')['replay_available'])

    def test_changed_file_aborts_entire_plan(self):
        raw=self.run_fixture();plan=p.inventory(self.policy)
        raw.write_text('changed size')
        with self.assertRaisesRegex(ValueError,'changed'):p.apply(plan,self.root/'audit',lambda:None)
        self.assertTrue((raw.parent/'job.json').exists())

    def test_active_run_aborts_before_mutation(self):
        raw=self.run_fixture();plan=p.inventory(self.policy)
        def active():raise RuntimeError('Active test')
        with self.assertRaises(RuntimeError):p.apply(plan,self.root/'audit',active)
        self.assertTrue(raw.exists())

    def test_interruption_keeps_audit_and_untouched_outcomes(self):
        first=self.run_fixture('a');second=self.run_fixture('b')
        plan=p.inventory(self.policy);calls=[]
        def active():
            calls.append(1)
            if len(calls)==3:raise RuntimeError('New active test')
        audit=self.root/'audit'
        with self.assertRaises(RuntimeError):p.apply(plan,audit,active)
        self.assertTrue(Path(str(audit)+'.deleted.jsonl').exists())
        self.assertTrue((first.parent/'result.json').exists())
        self.assertTrue((second.parent/'result.json').exists())
        self.assertEqual(1,sum(r.exists() for r in (first,second)))

    def test_failed_run_budget(self):
        raw=self.run_fixture(status='unstable');self.policy['retain_latest_failure']=True
        self.assertEqual([],p.inventory(self.policy)['files'])
        self.policy['raw_budget_gib']=0
        self.assertIn(str(raw),[v['path'] for v in p.inventory(self.policy)['files']])

    def test_completed_recording_does_not_erase_failed_assessment(self):
        raw=self.run_fixture(status='failed');self.policy['retain_latest_failure']=True
        self.put('run/completion.json',{'status':'completed'})
        self.put('run/probe.json',{'status':'completed','completion':{'status':'completed'}})
        self.assertEqual([],p.inventory(self.policy)['files'])

    def test_repeated_partial_build_cleanup_preserves_its_marker(self):
        self.put('partial/diagnostics-pruned.json',{'previous_cleanup':True})
        result=self.put('partial/result.json',{'status':'failed'})
        payload=self.put('partial/payload.bin',{'disposable':True})
        self.policy['incomplete_builds']=[str(payload.parent)]
        plan=p.inventory(self.policy)
        self.assertEqual([str(payload)],[v['path'] for v in plan['files']])
        p.apply(plan,self.root/'audit.json',lambda:None)
        self.assertTrue(result.exists());self.assertTrue((payload.parent/'diagnostics-pruned.json').exists())
        self.assertEqual([],p.inventory(self.policy)['files'])

    def test_asset_hash_mismatch_prevents_all_deletion(self):
        asset=self.put('old/vehicles/a/a.dae',{})
        self.put('old/manifest.json',{'kind':'exported_vehicle','files':{'vehicles/a/a.dae':'0'*64}})
        with self.assertRaisesRegex(ValueError,'differs'):p.apply(p.inventory(self.policy),self.root/'audit',lambda:None)
        self.assertTrue(asset.exists())

    def test_paths_cannot_escape(self):
        with self.assertRaises(ValueError):p.safe(self.root.parent/'outside',self.root)
        with self.assertRaises(ValueError):p.safe(self.root,self.root)

    def test_settings_reference_protects_geometry(self):
        raw=self.run_fixture()
        project=self.put('active.json',{'Components':[{'GeometryDirectory':str(raw.parent)}]})
        settings=self.root/'settings.xml';settings.write_text('<Settings><LastProjectPath>'+str(project)+'</LastProjectPath></Settings>')
        self.policy['settings']=[str(settings)]
        self.assertEqual([],p.inventory(self.policy)['files'])

    def test_link_rejected(self):
        raw=self.run_fixture();link=self.root/'linked'
        try:link.symlink_to(raw.parent,target_is_directory=True)
        except OSError:self.skipTest('Symlink creation unavailable')
        with self.assertRaises(ValueError):p.safe(link/'job.json',self.root)
        self.assertIn(str(link),p.inventory(self.policy)['skipped_links'])


if __name__=='__main__':unittest.main()
