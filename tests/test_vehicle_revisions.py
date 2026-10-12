import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import vehicle_revisions as r
from prepare_frame import write_stl


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project={'Identity':{'id':'a'*32,'namespace':'fixture_aaaaaaaa'},'Components':[{'Id':'engine','GeometryDirectory':str(self.root/'cad')}], 'Anchors':[], 'Connections':[]}
        part={'slotType':'main','nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1,'group':['engine_structure']}] for i,p in enumerate(((0,0,0),(1,0,0),(0,1,0),(0,0,1)))],
              'beams':[['id1:','id2:'],['0','1',{'beamSpring':100}]],'triangles':[['id1:','id2:','id3:'],['0','1','2']],
              'powertrain':[['type','name','inputName','inputIndex'],['shaft','axle','dummy',0]],'flexbodies':[['mesh','[group]:','nonFlexMaterials'],['old',['engine_structure'],[]]]}
        prefix='vehicles/fixture_aaaaaaaa/'
        self.contents={prefix+'fixture_aaaaaaaa.jbeam':r.canonical({'fixture_aaaaaaaa':part}),prefix+'fixture_aaaaaaaa.dae':b'<COLLADA/>',prefix+'main.materials.json':b'{}',prefix+'base.pc':b'{}',prefix+'info.json':b'{}',prefix+'info_base.json':b'{}'}
        manifest={'kind':'exported_vehicle','version':1,'model':'fixture_aaaaaaaa','vehicle_directory':'vehicles/fixture_aaaaaaaa','component_parts':{'engine':'fixture_aaaaaaaa'},'nodes':{},'expected_dry_mass_kg':4}
        r.package_revision(self.root/'baseline',self.project,manifest,self.contents,{'recipe.json':b'{}'},'', 'Synthetic fixture physics')
        self.project['LastBuildReceipt']=str(self.root/'baseline/static_frame_build.json')
        (self.root/'cad').mkdir()
        write_stl(self.root/'cad/sheet.stl',np.array([[[0,0,0],[2,0,0],[0,2,0]]]))
        (self.root/'cad/geometry.json').write_text(json.dumps({'Meshes':[{'Id':'different_name','BodyKind':'surface','File':'sheet.stl'}]}))
    def tearDown(self):self.temp.cleanup()
    def test_texture_revision_keeps_physics_and_packages_portable_image(self):
        from PIL import Image
        image=self.root/'carbon.jpg';Image.new('RGB',(16,16),(30,40,50)).save(image)
        path=self.root/'cad/geometry.json';geo=json.loads(path.read_text())
        geo['Meshes'][0]['AppearanceGroups']=[dict(StartTriangle=0,TriangleCount=1,Appearance=dict(TextureFile=str(image)))]
        path.write_text(json.dumps(geo))
        before=r.load_baseline(self.project['LastBuildReceipt'])[3]
        r.replace_appearance(self.project,['engine'],self.root/'textured')
        _,manifest,contents,after=r.load_baseline(self.root/'textured/static_frame_build.json')
        self.assertEqual(before['sha256'],after['sha256'])
        materials=json.loads(contents['vehicles/fixture_aaaaaaaa/main.materials.json'])
        maps=[v['Stages'][0]['baseColorMap'] for v in materials.values() if 'baseColorMap' in v['Stages'][0]]
        self.assertEqual(len(maps),1);self.assertIn(maps[0].lstrip('/'),contents)
        self.assertIn('texture:'+str(image),manifest['appearance_inputs']['engine']['files'])
    def test_rigid_visual_child_uses_its_physical_parent(self):
        comp=self.project['Components'][0];comp.update(Id='panel',VisualParentId='engine',RigidAppearance=True)
        _,manifest,contents,_=r.load_baseline(self.project['LastBuildReceipt'])
        manifest.update(component_parts={'panel':'fixture_aaaaaaaa'},mass_allocations={'engine':{'0':1,'1':1,'2':1,'3':1}},render_bindings={'panel':['engine_structure']},component_meshes={'panel':['old']})
        r.package_revision(self.root/'parent',self.project,manifest,contents,{},self.project['LastBuildReceipt'],'Physical parent fixture')
        self.project['LastBuildReceipt']=str(self.root/'parent/static_frame_build.json')
        before=r.load_baseline(self.project['LastBuildReceipt'])[3]
        r.replace_appearance(self.project,['panel'],self.root/'child')
        _,_,contents,after=r.load_baseline(self.root/'child/static_frame_build.json')
        self.assertEqual(before['sha256'],after['sha256'])
        part=json.loads(contents['vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam'])['fixture_aaaaaaaa']
        self.assertEqual(len(part['props']),2)
    def test_pruned_baseline_explains_how_to_recover(self):
        receipt=self.root/'baseline/static_frame_build.json'
        record=json.loads(receipt.read_text())
        (receipt.parent/record['zip_file']).unlink()
        (receipt.parent/'diagnostics-pruned.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'pruned to recover disk space'):
            r.load_baseline(receipt)
    def test_low_disk_space_rejects_before_creating_partial_revision(self):
        from types import SimpleNamespace
        target=self.root/'missing-parent'/'revision'
        with patch.object(r.shutil,'disk_usage',return_value=SimpleNamespace(free=1024)):
            with self.assertRaisesRegex(OSError,'Not enough space to package'):
                r.package_revision(target,self.project,{},self.contents,{},'', 'test')
        self.assertFalse(target.parent.exists())
    def test_sparse_arm_refresh_uses_existing_nodes_and_preserves_physics(self):
        _,manifest,assets,before=r.load_baseline(self.project['LastBuildReceipt'])
        manifest.update(component_reports={'engine':{'allocation_method':'hardpoint_lumped'}},
                        mass_allocations={'engine':{'0':1.,'1':1.,'2':1.}},
                        component_roles={'engine':'fl_upper_wishbone'},component_meshes={'engine':['old']},
                        render_bindings={'engine':['engine_structure']})
        key='vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam'
        parts=json.loads(assets[key]);parts['fixture_aaaaaaaa']['nodes'][-1][-1]['group']=['unrelated']
        assets[key]=r.canonical(parts)
        r.package_revision(self.root/'sparse',self.project,manifest,assets,{},self.project['LastBuildReceipt'],'Sparse arm fixture')
        self.project['LastBuildReceipt']=str(self.root/'sparse/static_frame_build.json')
        before=r.load_baseline(self.project['LastBuildReceipt'])[3]
        r.replace_appearance(self.project,['engine'],self.root/'sparse-rendered')
        _,after,contents,physics=r.load_baseline(self.root/'sparse-rendered/static_frame_build.json')
        self.assertEqual(physics['sha256'],before['sha256'])
        part=json.loads(contents['vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam'])['fixture_aaaaaaaa']
        self.assertEqual(part['flexbodies'],[['mesh','[group]:','nonFlexMaterials']])
        self.assertEqual(len(part['props']),2)
        self.assertEqual(set(part['props'][1][2:5]),{'0','1','2'})
        self.assertIn('engine',after['rigid_render'])
        self.project['LastBuildReceipt']=str(self.root/'sparse-rendered/static_frame_build.json')
        r.replace_appearance(self.project,['engine'],self.root/'sparse-refreshed')
        _,_,contents,_=r.load_baseline(self.root/'sparse-refreshed/static_frame_build.json')
        part=json.loads(contents['vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam'])['fixture_aaaaaaaa']
        self.assertEqual(len(part['props']),2)
    def test_open_sheet_swap_without_material_preserves_all_physics(self):
        before=r.load_baseline(self.project['LastBuildReceipt'])[3]
        r.replace_appearance(self.project,['engine'],self.root/'changed')
        _,m,assets,after=r.load_baseline(self.root/'changed/static_frame_build.json')
        self.assertEqual(before,after)
        self.assertEqual(m['calibration_inputs_status'],'not_applied')
        self.assertEqual(m['rendered_review_status'],'required')
        self.assertIn('appearance_engine.dae',' '.join(assets))
        self.assertEqual(m['physics_origin'],'Synthetic fixture physics')
        part=json.loads(assets['vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam'])['fixture_aaaaaaaa']
        self.assertNotEqual(part['flexbodies'][1][0],'old')
    def test_cad_color_replacement_is_packaged_without_changing_physics(self):
        geometry=self.root/'cad/geometry.json';data=json.loads(geometry.read_text())
        data['Meshes'][0]['AppearanceGroups']=[dict(StartTriangle=0,TriangleCount=1,Appearance=dict(BaseColor=[.9,.1,.2,1],Roughness=.25,Metallic=.8))]
        geometry.write_text(json.dumps(data));before=r.load_baseline(self.project['LastBuildReceipt'])[3]
        r.replace_appearance(self.project,['engine'],self.root/'colored')
        _,_,assets,after=r.load_baseline(self.root/'colored/static_frame_build.json')
        self.assertEqual(before,after)
        materials=json.loads(assets['vehicles/fixture_aaaaaaaa/main.materials.json'])
        captured=[m for n,m in materials.items() if n.startswith('cad_appearance_')]
        self.assertEqual(len(captured),1);self.assertEqual(captured[0]['Stages'][0]['baseColorFactor'],[.9,.1,.2,1])
        self.assertIn(captured[0]['mapTo'].encode(),assets['vehicles/fixture_aaaaaaaa/appearance_engine.dae'])
    def test_render_alignment_cannot_move_nodes(self):
        transform=np.eye(4);transform[:3,3]=[10,20,30]
        self.project['Components'][0]['AppearanceTransform']=transform.ravel().tolist()
        r.replace_appearance(self.project,['engine'],self.root/'aligned')
        self.assertEqual(r.load_baseline(self.root/'aligned/static_frame_build.json')[3],r.load_baseline(self.project['LastBuildReceipt'])[3])
    def test_unknown_sections_and_controllers_are_physical(self):
        assets=copy.deepcopy(self.contents);key='vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam'
        before=r.physical_snapshot(assets,{})['sha256'];data=json.loads(assets[key])
        data['fixture_aaaaaaaa']['futureController']={'gain':2};assets[key]=r.canonical(data)
        self.assertNotEqual(r.physical_snapshot(assets,{})['sha256'],before)
        assets=copy.deepcopy(self.contents);assets['vehicles/fixture_aaaaaaaa/lua/controller/a.lua']=b'return {}'
        self.assertNotEqual(r.physical_snapshot(assets,{})['sha256'],before)
    def test_packaged_shaft_chain_survives_appearance_and_namespace_fork(self):
        _,manifest,contents,_=r.load_baseline(self.project['LastBuildReceipt'])
        chain={'front':dict(segments=[dict(component='engine',nodes=['0','1'],plunge_m=.01)],
                             joints=[dict(node='0',support_nodes=['1','2','3'])])}
        manifest['shaft_chains']=chain
        r.package_revision(self.root/'chain',self.project,manifest,contents,{},self.project['LastBuildReceipt'],'Shaft fixture')
        self.project['LastBuildReceipt']=str(self.root/'chain/static_frame_build.json')
        r.replace_appearance(self.project,['engine'],self.root/'chain-appearance')
        self.assertEqual(r.load_baseline(self.root/'chain-appearance/static_frame_build.json')[1]['shaft_chains'],chain)
        project=copy.deepcopy(self.project);project['Identity']={'id':'b'*32,'namespace':'fork_bbbbbbbb'}
        r.fork_baseline(project,self.project['LastBuildReceipt'],self.root/'chain-fork')
        self.assertEqual(r.load_baseline(self.root/'chain-fork/static_frame_build.json')[1]['shaft_chains'],chain)
    def test_unknown_owner_rejected_without_baseline_mutation(self):
        path=Path(self.project['LastBuildReceipt']);before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'stable physical'):r.replace_appearance(self.project,['missing'],self.root/'bad')
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'bad').exists())
    def test_tampered_baseline_rejected(self):
        archive=self.root/'baseline/work/dist/fixture_aaaaaaaa.zip';archive.write_bytes(archive.read_bytes()+b'bad')
        with self.assertRaisesRegex(ValueError,'ZIP has changed'):r.replace_appearance(self.project,['engine'],self.root/'bad')
    def test_template_fork_preserves_physical_values_under_new_identity(self):
        project=copy.deepcopy(self.project);project['Identity']={'id':'b'*32,'namespace':'my_vehicle_bbbbbbbb'}
        r.fork_baseline(project,self.project['LastBuildReceipt'],self.root/'fork')
        record,manifest,assets,snapshot=r.load_baseline(self.root/'fork/static_frame_build.json')
        self.assertEqual(record['identity'],project['Identity'])
        self.assertEqual(manifest['model'],'my_vehicle_bbbbbbbb')
        self.assertEqual(manifest['vehicle_directory'],'vehicles/my_vehicle_bbbbbbbb')
        self.assertEqual(manifest['component_parts']['engine'],'my_vehicle_bbbbbbbb')
        self.assertEqual(snapshot['value']['parts']['my_vehicle_bbbbbbbb'],r.load_baseline(self.project['LastBuildReceipt'])[3]['value']['parts']['fixture_aaaaaaaa'])
    def test_replacement_retains_other_meshes_in_a_shared_part(self):
        project=copy.deepcopy(self.project);record,manifest,assets,_=r.load_baseline(self.project['LastBuildReceipt'])
        name='vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam';parts=json.loads(assets[name]);parts['fixture_aaaaaaaa']['flexbodies'].append(['keep_me',['engine_structure'],[]]);assets[name]=r.canonical(parts)
        manifest['component_meshes']={'engine':['old']}
        r.package_revision(self.root/'shared',project,manifest,assets,{'recipe.json':b'{}'},'','fixture')
        project['LastBuildReceipt']=str(self.root/'shared/static_frame_build.json')
        r.replace_appearance(project,['engine'],self.root/'shared-replaced')
        rows=json.loads(r.load_baseline(self.root/'shared-replaced/static_frame_build.json')[2][name])['fixture_aaaaaaaa']['flexbodies']
        self.assertIn('keep_me',[row[0] for row in rows[1:]])
        self.assertNotIn('old',[row[0] for row in rows[1:]])

    def test_worker_batches_pending_and_failed_visuals_without_changing_physics(self):
        import component_worker
        project=copy.deepcopy(self.project)
        project['Components'][0]['AppearancePackageState']='pending'
        project['Components'].append(dict(Id='accessory',GeometryDirectory=str(self.root/'cad'),AppearancePackageState='failed'))
        _,manifest,contents,before=r.load_baseline(project['LastBuildReceipt'])
        manifest['component_parts']['accessory']=manifest['component_parts']['engine']
        manifest['component_meshes']={'engine':['old'],'accessory':[]}
        r.package_revision(self.root/'multi',project,manifest,contents,{},project['LastBuildReceipt'],'fixture')
        project['LastBuildReceipt']=str(self.root/'multi/static_frame_build.json')
        path=self.root/'project.json';path.write_text(json.dumps(project));original=path.read_bytes()
        with patch.object(sys,'argv',['component_worker','appearance','--project',str(path),'--output',str(self.root/'batch')]):
            component_worker.main()
        _,result,_,after=r.load_baseline(self.root/'batch/static_frame_build.json')
        self.assertEqual(before,after)
        self.assertEqual(set(result['appearance_replacements']),{'engine','accessory'})
        snapshot=json.loads((self.root/'batch/project.snapshot.json').read_text())
        self.assertTrue(all(c['AppearancePackageState']=='current' for c in snapshot['Components']))
        self.assertEqual(path.read_bytes(),original)

    def test_failed_worker_does_not_erase_saved_visual_selection(self):
        import component_worker
        self.project['Components'][0].update(AppearancePackageState='pending',AppearanceSelections=[{'Reference':'persistent-cad-selection'}],AppearanceDirectory=str(self.root/'missing'))
        path=self.root/'project.json';path.write_text(json.dumps(self.project));original=path.read_bytes()
        baseline=Path(self.project['LastBuildReceipt']);baseline_bytes=baseline.read_bytes()
        with patch.object(sys,'argv',['component_worker','appearance','--project',str(path),'--output',str(self.root/'failed')]):
            with self.assertRaises(FileNotFoundError):component_worker.main()
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(baseline.read_bytes(),baseline_bytes)
        self.assertFalse((self.root/'failed/static_frame_build.json').exists())


if __name__=='__main__':unittest.main()
