import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
try:
    import numpy as np
    import scipy
except ImportError:
    raise unittest.SkipTest('Use the calibration interpreter for CAD integration tests')
import calibration_worker as worker
from frame_harness.build import sha256, write_json, node_table, build_candidate, SOURCES
from frame_harness.calibration import graph_identity, fit_masses, mass_properties
from frame_harness.generation import load_artifact, inputs, scenario
from frame_harness.models import HarnessProject, ParameterSet, TestScenario
from prepare_frame import rotate
from test_static_frame import fixture, pipeline


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def make_generation(self):
        source=self.root/'prepared';fixture(source);job=self.root/'generation'
        original=worker.stage_script;calls=[]
        def stage(name,folder):calls.append(name);original(name,folder)
        with patch.object(worker,'stage_script',side_effect=stage):worker.prepare(source,job)
        self.assertEqual(calls,['JBeamShellGenerator.py','BeamNGVehicleInfoGenerator.py'])
        return job

    def make_artifact(self,job):
        part=worker.read(job/'source/mochi_raw.jbeam')
        case=job/'study/4130-annealed';case.mkdir(parents=True)
        write_json(case/'mochi.jbeam',part)
        hashes=worker.read(job/'snapshot.json')['source_sha256']
        spec=dict(version=1,source_hashes=hashes,vehicle_file='mochi.jbeam',vehicle_sha256=sha256(case/'mochi.jbeam'),
                  offline_accepted=True,geometry_valid=True,reference_config={})
        write_json(case/'calibration.json',spec);write_json(case/'report.json',{'fixture':'package integrity only, not physical acceptance'})
        state=dict(status='offline_complete',candidates={'4130-annealed':{'artifact_sha256':sha256(case/'calibration.json')}})
        write_json(job/'study/calibration-study.json',state)
        return case/'calibration.json'

    def test_textured_frame_keeps_uvs_assets_and_material_through_calibrated_packaging(self):
        from PIL import Image
        from prepare_frame import write_dae
        from frame_harness.cad import read_bodies
        import xml.etree.ElementTree as ET
        source=self.root/'textured-prepared';fixture(source)
        image=self.root/'carbon.jpg';Image.new('RGB',(16,16),(40,45,50)).save(image)
        meshes=[]
        for body in read_bodies(source/'mochi.dae'):
            triangles=body.vertices[body.faces]
            record=dict(Id=body.name,AppearanceGroups=[dict(StartTriangle=0,TriangleCount=len(triangles),Appearance=dict(TextureFile=str(image)))])
            meshes.append((record,triangles))
        write_dae(source/'mochi.dae',meshes)
        job=self.root/'textured-generation';worker.prepare(source,job);self.make_artifact(job)
        output=self.root/'textured-package';worker.package(job,'4130-annealed',output)
        with zipfile.ZipFile(output/'work/dist/ak1di_mochi.zip') as archive:
            self.assertTrue(any(n.endswith('.color.png') for n in archive.namelist()))
            root=ET.fromstring(archive.read('vehicles/mochi/mochi.dae'));ns={'c':'http://www.collada.org/2005/11/COLLADASchema'}
            primitives=root.findall('.//c:triangles',ns)
            self.assertTrue(primitives)
            self.assertTrue(all(p.find("c:input[@semantic='TEXCOORD']",ns) is not None for p in primitives))

    def test_generation_requires_review_and_rejects_changed_snapshot(self):
        job=self.make_generation()
        with self.assertRaisesRegex(ValueError,'Review and approve'):worker.calibrate(job)
        (job/'source/mochi.dae').write_text('changed')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):worker.check_snapshot(job)

    def test_bracing_is_generated_and_sealed_before_fixture_review(self):
        job=self.make_generation()
        report=worker.read(job/'source/graph-generation.json')
        part=worker.read(job/'source/mochi_raw.jbeam')['mochi']
        from frame_harness.build import beam_table
        edges={tuple(sorted((b['a'],b['b']))) for b in beam_table(part)}
        self.assertEqual(len(edges),report['final_beams'])
        self.assertEqual(report['final_beams'],report['original_beams']+len(report['added_edges']))
        self.assertTrue(all(tuple(edge) in edges for edge in report['added_edges']))
        self.assertFalse(worker.read(job/'review.json')['approved'])
        seal=worker.read(job/'snapshot.json')['source_sha256']
        self.assertEqual(seal['graph-generation.json'],sha256(job/'source/graph-generation.json'))
        (job/'source/graph-generation.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):worker.check_snapshot(job)

    def test_render_regions_preserve_physical_cad_and_have_complete_locator_edges(self):
        from frame_harness.skin import apply_skin
        from frame_harness.cad import read_bodies
        from frame_harness.build import beam_table
        job=self.make_generation();source=job/'source';binding=worker.read(source/'mesh-bindings.json')
        self.assertEqual(sha256(source/'cad_source.dae'),sha256(self.root/'prepared/mochi.dae'))
        self.assertEqual(inputs(worker.project(job))['mesh'],'cad_source.dae')
        self.assertAlmostEqual(binding['surface_area_after_m2'],binding['surface_area_before_m2'],places=9)
        self.assertEqual({b.name for b in read_bodies(source/'mochi.dae')},{r['mesh'] for r in binding['regions']})
        part=worker.read(source/'mochi_raw.jbeam')['mochi'];before=graph_identity(part)
        apply_skin(part,binding)
        self.assertEqual(graph_identity(part),before)
        self.assertEqual(len(part['flexbodies'])-1,len(binding['regions']))
        self.assertEqual(part['controller'][1][0],'cadSkin')
        self.assertEqual({r['mesh'] for r in part['controller'][1][1]['regions']},{r['mesh'] for r in binding['regions']})
        selected=binding['regions'][0]['nodes']
        part['beams']=[row for row in part['beams'] if not isinstance(row,list) or set(row[:2])!=set(selected[:2])]
        with self.assertRaisesRegex(ValueError,'supporting beam'):apply_skin(part,binding)

    def test_regeneration_reuses_physical_cad_not_render_derivative(self):
        job=self.make_generation();new=self.root/'regenerated'
        worker.prepare(job/'source',new,job)
        self.assertEqual(sha256(new/'source/cad_source.dae'),sha256(job/'source/cad_source.dae'))
        self.assertFalse(worker.read(new/'review.json')['approved'])

    def test_fixed_graph_refit_preserves_layout_and_requires_fresh_review(self):
        job=self.make_generation();source=self.root/'replacement';fixture(source)
        baseline=graph_identity(worker.read(job/'source/mochi_raw.jbeam')['mochi'])
        worker.fixed_preview(job,source)
        new=self.root/'fixed-refit';calls=[];original=worker.stage_script
        def stage(name,folder):calls.append(name);original(name,folder)
        with patch.object(worker,'stage_script',side_effect=stage):worker.prepare(source,new)
        self.assertNotIn('JBeamShellGenerator.py',calls)
        self.assertEqual(graph_identity(worker.read(new/'source/mochi_raw.jbeam')['mochi']),baseline)
        self.assertEqual(worker.read(new/'source/graph-generation.json')['mode'],'fixed_graph')
        self.assertFalse(worker.read(new/'review.json')['approved'])
        worker.check_snapshot(job);worker.check_snapshot(new)

    def test_fixed_graph_refit_rejects_new_mounts_before_capturing(self):
        job=self.make_generation();source=self.root/'replacement';fixture(source)
        write_json(source/'frame-mounts.json',{'new_mount':[1,2,3]})
        with self.assertRaisesRegex(ValueError,'Mount plan changed'):worker.fixed_preview(job,source)
        self.assertFalse((source/'fixed-graph.jbeam').exists())

    def test_render_controller_is_sealed_and_staged_in_live_and_packaged_builds(self):
        job=self.make_generation();artifact=self.make_artifact(job)
        run=self.root/'run';run.mkdir()
        build_candidate(worker.project(job),run,ParameterSet(calibration=str(artifact)),TestScenario.named('idle'))
        controller=job/'source/cadSkin.lua'
        self.assertEqual(sha256(controller),sha256(run/'vehicle/lua/controller/cadSkin.lua'))
        output=self.root/'package';worker.package(job,'4130-annealed',output)
        with zipfile.ZipFile(output/'work/dist/ak1di_mochi.zip') as z:
            self.assertEqual(z.read('vehicles/mochi/lua/controller/cadSkin.lua'),controller.read_bytes())
        controller.write_text('altered controller')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):worker.check_snapshot(job)

    def test_generation_records_fixed_coordinate_provenance(self):
        source=self.root/'prepared';fixture(source)
        write_json(source/'geometry.json',dict(Assignment=dict(Hull=dict(Orientation='X-ZY',
            CoordinateConvention='solidworks-y-up-to-beamng-z-up-v1'))))
        job=self.root/'generation';worker.prepare(source,job)
        coordinates=worker.read(job/'source/generation.json')['coordinates']
        self.assertEqual(coordinates,dict(convention='solidworks-y-up-to-beamng-z-up-v1',mapping='X-ZY',units='metres',origin='assembly'))
        self.assertEqual(worker.read(job/'snapshot.json')['source_sha256']['geometry.json'],sha256(source/'geometry.json'))

    def test_package_preserves_jbeam_and_provenance_through_customization(self):
        job=self.make_generation();artifact=self.make_artifact(job);out=self.root/'build'
        worker.package(job,'4130-annealed',out)
        original=(artifact.parent/'mochi.jbeam').read_bytes()
        with zipfile.ZipFile(out/'work/dist/ak1di_mochi.zip') as z:self.assertEqual(z.read('vehicles/mochi/mochi.jbeam'),original)
        profile=self.root/'profile.json';write_json(profile,dict(Name='New frame',Brand='CAD',Author='Test',Description='Diagnostic',Configuration='Annealed',PreviewImage=''))
        revised=self.root/'revision';pipeline.customize(out/'static_frame_build.json',profile,revised)
        a=worker.read(out/'static_frame_build.json');b=worker.read(revised/'static_frame_build.json')
        self.assertEqual(a['calibration'],b['calibration']);self.assertEqual(b['qualification_status'],'diagnostic')
        with zipfile.ZipFile(revised/'work/dist/ak1di_mochi.zip') as z:self.assertEqual(z.read('vehicles/mochi/mochi.jbeam'),original)
        (revised/'calibration/calibration.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'provenance changed'):pipeline.completed_build(revised/'static_frame_build.json')

    def test_changed_graph_suggests_spatial_fixtures_but_never_reuses_approval(self):
        first=self.make_generation();review=worker.read(first/'review.json');review['approved']=True;write_json(first/'review.json',review)
        source=self.root/'prepared';lines=(source/'mochi_hull.off').read_text().splitlines();count=int(lines[1].split()[0])
        for i in range(2,2+count):lines[i]=' '.join(str(float(v)*1.003) for v in lines[i].split())
        (source/'mochi_hull.off').write_text('\n'.join(lines)+'\n')
        second=self.root/'new-generation';worker.prepare(source,second,first);new=worker.read(second/'review.json')
        self.assertFalse(new['approved']);self.assertNotEqual(new['graph_sha256'],review['graph_sha256'])
        self.assertEqual(new['fixtures'],review['fixtures'])

    def test_qualified_receipt_retains_the_stated_qualification_scope(self):
        job=self.make_generation();self.make_artifact(job)
        state=worker.read(job/'study/calibration-study.json')
        scope='Equivalent-model tests only; heat treatment and ductile rupture remain unvalidated'
        state['acceptance']={'4130-annealed':dict(accepted=True,reasons=[],qualification_scope=scope)}
        write_json(job/'study/calibration-study.json',state)
        output=self.root/'qualified-package';worker.package(job,'4130-annealed',output)
        receipt=worker.read(output/'static_frame_build.json')
        self.assertEqual(receipt['qualification_status'],'qualified')
        self.assertEqual(receipt['limitations'],[scope])

    def test_quick_receipt_preserves_screening_without_claiming_full_qualification(self):
        job=self.make_generation();artifact=self.make_artifact(job)
        state=worker.read(job/'study/calibration-study.json')
        quick=dict(status='quick_passed',identity=dict(case='4130-annealed',artifact=sha256(artifact),calibration=state.get('identity')))
        write_json(job/'study/quick-verification.json',quick)
        output=self.root/'quick-package';worker.package(job,'4130-annealed',output)
        receipt=worker.read(output/'static_frame_build.json')
        self.assertEqual(receipt['qualification_status'],'diagnostic')
        self.assertEqual(receipt['recording_status'],'completed (quick screening)')
        self.assertEqual(worker.read(output/'calibration/quick-verification.json'),quick)

    def test_reject_modified_artifact_pins_and_changed_graph(self):
        job=self.make_generation();artifact=self.make_artifact(job);spec=worker.read(artifact)
        spec['offline_accepted']=False;write_json(artifact,spec)
        with self.assertRaisesRegex(ValueError,'artifact changed'):worker.package(job,'4130-annealed',self.root/'bad')
        vehicle=artifact.parent/'mochi.jbeam';part=worker.read(vehicle)
        row=next(r for r in part['mochi']['nodes'][1:] if isinstance(r,list));row.append({'fixed':True}) if len(row)==4 else row[4].update(fixed=True)
        write_json(vehicle,part);spec['vehicle_sha256']=sha256(vehicle);write_json(artifact,spec)
        with self.assertRaisesRegex(ValueError,'fixture pins'):load_artifact(worker.project(job),artifact)
        row[4].pop('fixed');row[1]+=.001;write_json(vehicle,part);spec['vehicle_sha256']=sha256(vehicle);write_json(artifact,spec)
        with self.assertRaisesRegex(ValueError,'changed the generation graph'):load_artifact(worker.project(job),artifact)

    def test_source_change_during_packaging_cannot_commit_a_receipt(self):
        job=self.make_generation();self.make_artifact(job);output=self.root/'partial'
        original=zipfile.ZipFile.write
        def changing(z,path,*args,**kwargs):
            result=original(z,path,*args,**kwargs)
            if Path(path).name=='info_base.json':(job/'source/mochi.dae').write_text('changed during package')
            return result
        with patch.object(zipfile.ZipFile,'write',changing),self.assertRaisesRegex(ValueError,'snapshot changed'):
            worker.package(job,'4130-annealed',output)
        self.assertFalse((output/'static_frame_build.json').exists())

    def test_each_generation_uses_its_own_mass_and_geometry(self):
        from frame_harness.cad import Body, audit_body
        from scipy.spatial import ConvexHull
        results=[]
        for scale in (1.,1.003):
            vertices=np.array([[x,y,z] for x in (-1.,1.) for y in (-2.,2.) for z in (-.5,.5)])*scale
            faces=ConvexHull(vertices).simplices.copy()
            for i,f in enumerate(faces):
                a,b,c=vertices[f]
                if np.dot(np.cross(b-a,c-a),a)<0:faces[i]=f[::-1]
            _,audit=audit_body(Body('new_frame',vertices,faces));m,c,inertia=mass_properties([audit],7850)
            # Corners and central/interior nodes can represent the volume moments.
            positions=np.vstack((vertices/np.sqrt(3),vertices*.01))
            weights,report=fit_masses(positions,m,c,inertia)
            self.assertTrue(report['accepted']);self.assertTrue(np.all(weights>0));results.append(m)
        self.assertAlmostEqual(results[1]/results[0],1.003**3)
        self.assertNotAlmostEqual(results[0],34.789158)

    def test_all_axis_mappings_are_rotations_and_map_up_and_front(self):
        for up in ('+X','-X','+Y','-Y','+Z','-Z'):
            for front in ('+X','-X','+Y','-Y','+Z','-Z'):
                if up[1]==front[1]:continue
                code=up+','+front
                matrix=np.array([rotate(v,code) for v in np.eye(3)]).T
                np.testing.assert_allclose(matrix@matrix.T,np.eye(3));self.assertAlmostEqual(np.linalg.det(matrix),1)
                def axis(a):return np.eye(3)['XYZ'.index(a[1])]*(-1 if a[0]=='-' else 1)
                np.testing.assert_equal(rotate(axis(up),code),[0,0,1]);np.testing.assert_equal(rotate(axis(front),code),[0,-1,0])
        with self.assertRaises(ValueError):rotate((0,0,0),'+Y,-Y')

    def test_archived_reference_only_matches_unchanged_inputs(self):
        base=ROOT/'dependencies/cad-calibration';source=base/'Test Programs'
        artifact=base/'Test Harness/comparisons/4130-complete-20261004/4130-annealed/calibration.json'
        spec,vehicle=load_artifact(HarnessProject(source=source),artifact)
        part=worker.read(vehicle)['mochi'];nodes=node_table(part)
        self.assertEqual(len(nodes),78);self.assertEqual(len(graph_identity(part)['beams']),435)
        self.assertAlmostEqual(sum(n['mass'] for n in nodes.values()),34.789158,places=5)
        self.assertFalse(any(n['options'].get('fixed') for n in nodes.values()))
        changed=self.root/'changed';shutil.copytree(source,changed);(changed/'mochi_hull.off').write_text('new geometry')
        with self.assertRaisesRegex(ValueError,'differs from this generation'):load_artifact(HarnessProject(source=changed),artifact)

    def test_explicit_non_mochi_part_and_fixture_identity(self):
        job=self.make_generation();artifact=self.make_artifact(job)
        source=job/'source';data=worker.read(source/'mochi_raw.jbeam');part=data.pop('mochi');data['another_frame']=part
        write_json(source/'mochi_raw.jbeam',data);write_json(artifact.parent/'mochi.jbeam',data)
        manifest=worker.read(source/'generation.json');manifest['part']='another_frame';write_json(source/'generation.json',manifest)
        spec=worker.read(artifact);spec['source_hashes']={n:sha256(source/n) for n in inputs(worker.project(job))['sources']};spec['vehicle_sha256']=sha256(artifact.parent/'mochi.jbeam');write_json(artifact,spec)
        load_artifact(worker.project(job),artifact)
        review=worker.read(job/'review.json');config={'fixtures':review['fixtures']}
        test=scenario(config,'flex');self.assertEqual(test.fixed_nodes,review['fixtures']['flex']['fixed_nodes'])
        run=self.root/'run';run.mkdir();result=build_candidate(worker.project(job),run,ParameterSet(calibration=str(artifact)),test)
        self.assertEqual(result['part'],'another_frame')
        self.assertFalse(any(n['options'].get('fixed') for n in node_table(worker.read(artifact.parent/'mochi.jbeam')['another_frame']).values()))
