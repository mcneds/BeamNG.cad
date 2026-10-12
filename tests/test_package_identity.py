import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
import zipfile

from test_static_frame import fixture, pipeline


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='identity-')
        cls.root = Path(cls.temporary.name)
        fixture(cls.root/'source')
        from test_static_frame import fixture_package
        fixture_package(cls.root/'source', cls.root/'original')

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self):
        self.folder=self.root/uuid.uuid4().hex;self.folder.mkdir()
        self.profile=self.folder/'profile.json'
        self.profile.write_text(json.dumps(dict(Name='New title',Brand='CAD',Author='Tester',Description='',Configuration='Base',PreviewImage='')))
        self.project=self.folder/'project.json'
        self.identity=dict(id=uuid.uuid4().hex,namespace='test_'+uuid.uuid4().hex[:8])
        self.project.write_text(json.dumps({'Identity':self.identity}))

    def create(self, name='export', receipt=None):
        output=self.folder/name
        result=pipeline.customize(receipt or self.root/'original/static_frame_build.json', self.profile,output,self.project)
        return output/'static_frame_build.json',result

    def test_two_projects_install_side_by_side_and_rename_replaces_only_one(self):
        first,one=self.create()
        game=self.folder/'game';game.mkdir();(game/'BeamNG.drive.exe').touch()
        mods=self.folder/'mods';mods.mkdir()
        installed=pipeline.install(first,game,mods)['installed_file']
        second_identity=dict(id=uuid.uuid4().hex,namespace='other_project')
        self.project.write_text(json.dumps({'Identity':second_identity}))
        second,two=self.create('second')
        other=pipeline.install(second,game,mods)['installed_file'];other_hash=pipeline.digest(Path(other))
        self.assertNotEqual(installed,other)
        self.project.write_text(json.dumps({'Identity':self.identity}))
        profile=json.loads(self.profile.read_text());profile['Name']='Renamed';self.profile.write_text(json.dumps(profile))
        renamed,three=self.create('renamed',first)
        result=pipeline.install(renamed,game,mods)
        self.assertEqual(result['installed_file'],installed)
        self.assertIsNotNone(result['backup_file'])
        self.assertEqual(other_hash,pipeline.digest(Path(other)))
        self.assertEqual(one['identity'],three['identity'])

    def test_namespaced_geometry_preserved_and_legacy_receipt_readable(self):
        receipt,record=self.create()
        pipeline.completed_build(receipt)
        pipeline.completed_build(self.root/'original/static_frame_build.json')
        model=self.identity['namespace']
        with zipfile.ZipFile(receipt.parent/record['zip_file']) as z:
            self.assertTrue(all(n.startswith('vehicles/'+model+'/') for n in z.namelist()))
            part=json.loads(z.read('vehicles/'+model+'/'+model+'.jbeam'))[model]
            self.assertTrue(all(r[0].startswith(model+'__') for r in part['nodes'][1:] if isinstance(r,list)))
            self.assertEqual(part['slotType'],'main')
            self.assertEqual(json.loads(z.read('vehicles/'+model+'/base.pc'))['model'],model)

    def test_project_mismatch_and_invalid_namespace_rejected(self):
        receipt,_=self.create()
        self.project.write_text(json.dumps({'Identity':dict(id=uuid.uuid4().hex,namespace='another')}))
        with self.assertRaisesRegex(ValueError,'another project'): self.create('wrong',receipt)
        self.project.write_text(json.dumps({'Identity':dict(id=uuid.uuid4().hex,namespace='../escape')}))
        with self.assertRaisesRegex(ValueError,'namespace'): self.create('escape')

    def test_original_and_export_tampering_rejected(self):
        receipt,record=self.create()
        source=receipt.parent/'identity/source.jbeam';source.write_text('{}')
        with self.assertRaisesRegex(ValueError,'Original export'): pipeline.completed_build(receipt)

    def test_component_revision_keeps_intake_assets_and_rejects_manifest_tampering(self):
        import hashlib
        receipt,record=self.create()
        with zipfile.ZipFile(receipt.parent/record['zip_file']) as z:
            contents={name:z.read(name) for name in z.namelist()}
        files={name:hashlib.sha256(data).hexdigest() for name,data in contents.items()}
        for name,data in contents.items():
            target=receipt.parent/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        model=self.identity['namespace']
        manifest=dict(kind='exported_vehicle',version=1,model=model,vehicle_directory='vehicles/'+model,config='base.pc',nodes={'fixture':{}},fixed_nodes=[],files=files)
        provenance=receipt.parent/'provenance/frame-source.jbeam';provenance.parent.mkdir();provenance.write_bytes(contents['vehicles/'+model+'/'+model+'.jbeam'])
        hashes={'provenance/frame-source.jbeam':pipeline.digest(provenance)};manifest['provenance_files']=hashes
        pipeline.write_json(receipt.parent/'manifest.json',manifest)
        record.pop('identity_export');record.update(component_files=files,component_manifest_sha256=pipeline.digest(receipt.parent/'manifest.json'),component_provenance_sha256=hashes,recording_status='completed',qualification_status='mounting_verified',mounting_verification_sha256='old')
        pipeline.write_json(receipt,record)
        updated,result=self.create('component-edit',receipt)
        from frame_harness.vehicle import intake
        intake(updated.parent/'manifest.json');pipeline.completed_build(updated)
        self.assertEqual(result['qualification_status'],'diagnostic')
        self.assertNotIn('mounting_verification_sha256',result)
        self.assertEqual(result['identity'],record['identity'])
        preserved=updated.parent/'provenance/frame-source.jbeam';original=preserved.read_bytes();preserved.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'provenance changed'):pipeline.completed_build(updated)
        preserved.write_bytes(original)
        (updated.parent/'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest changed'):pipeline.completed_build(updated)

    def test_differently_named_duplicate_internal_vehicle_rejected(self):
        receipt,record=self.create()
        game=self.folder/'game';game.mkdir();(game/'BeamNG.drive.exe').touch()
        mods=self.folder/'mods';mods.mkdir()
        shutil.copy2(receipt.parent/record['zip_file'],mods/'renamed_duplicate.zip')
        with self.assertRaisesRegex(FileExistsError,'Another package'):pipeline.install(receipt,game,mods)


if __name__=='__main__':unittest.main()
