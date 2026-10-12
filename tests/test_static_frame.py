"""Dependency-free package fixtures for installer and customization checks."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("static_frame", ROOT / "beamng.cad/FramePipeline/build_static_frame.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def fixture(folder):
    folder.mkdir()
    vertices = [(-1, -2, 0), (1, -2, 0), (1, 2, 0), (-1, 2, 0),
                (-1, -2, 1), (1, -2, 1), (1, 2, 1), (-1, 2, 1)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    (folder / "mochi_hull.off").write_text("OFF\n8 12 0\n" + "\n".join(" ".join(map(str, p)) for p in vertices)
        + "\n" + "\n".join("3 " + " ".join(map(str, f)) for f in faces) + "\n")
    positions = " ".join(str(c) for vertex in vertices for c in vertex)
    indices = " ".join(str(i) for face in faces for i in face)
    (folder / "mochi.dae").write_text(f'''<?xml version="1.0"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit name="metre" meter="1"/><up_axis>Z_UP</up_axis></asset>
<library_geometries><geometry id="frame" name="frame"><mesh>
<source id="positions"><float_array id="positions-array" count="24">{positions}</float_array>
<technique_common><accessor source="#positions-array" count="8" stride="3">
<param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
</accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles count="12"><input semantic="VERTEX" source="#vertices" offset="0"/><p>{indices}</p></triangles>
</mesh></geometry></library_geometries><library_visual_scenes><visual_scene id="scene">
<node id="fixture_frame" name="fixture_frame"><instance_geometry url="#frame"/></node>
</visual_scene></library_visual_scenes><scene><instance_visual_scene url="#scene"/></scene></COLLADA>''')
    material = {"name": "Synthetic fixture material", "geometryMode": "shell", "thickness": 0.003,
                "density": 7850., "bulkModulus": 160e9, "shearModulus": 79e9, "yieldStrength": 250e6,
                "ultimateStrength": 450e6, "fractureStrain": .2, "damageProjection": "physicalForce",
                "dampingRatio": .02, "dampingReferenceHz": 25., "maximumLocalFrequencyHz": 350.,
                "minimumNodeWeight": .01, "massFitIterations": 20, "stiffnessFitIterations": 20,
                "massRegularization": 1e-8, "stiffnessRegularization": 1e-8}
    settings = {"modelId": "mochi", "name": "Synthetic frame", "brand": "Fixture", "author": "Test",
                "country": "Other", "description": "Synthetic test, not a physical calibration",
                "bodyStyle": "Other", "type": "Prop", "defaultConfig": "base", "mainPartName": "mochi",
                "generatedJBeam": "mochi.jbeam", "generatedPartName": "mochi", "defaultPaintName1": "Test",
                "paints": {"Test": {"baseColor": [.2, .2, .2, 1.], "metallic": 0., "roughness": .5,
                                    "clearcoat": 0., "clearcoatRoughness": .5}},
                "years": {"min": 2026, "max": 2026}, "configuration": {"name": "Static fixture"}}
    for name, value in (("material.json", material), ("vehicle_info_settings.json", settings),
                        ("main.materials.json", {})):
        (folder / name).write_text(json.dumps(value))
    return vertices


def fixture_package(source, output):
    """Minimal package fixture for installer/identity tests, without a retired generator."""
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    work = output/'work'; work.mkdir()
    (work/'mochi_hull.off').write_bytes((source/'mochi_hull.off').read_bytes())
    vertices = [(-1,-2,0),(1,-2,0),(1,2,0),(-1,2,0),(-1,-2,1),(1,-2,1),(1,2,1),(-1,2,1)]
    part = dict(slotType='main', nodes=[['id','posX','posY','posZ']]+[[f'sh{i}',*p] for i,p in enumerate(vertices)],
                beams=[['id1:','id2:']]+[[f'sh{i}',f'sh{(i+1)%8}'] for i in range(8)],
                flexbodies=[['mesh','[group]:','nonFlexMaterials'],['fixture_frame',['mochi_shell']]],
                refNodes=[['ref:','back:','left:','up:'],['sh0','sh1','sh2','sh4']])
    data={'mochi.jbeam':json.dumps({'mochi':part}).encode(), 'mochi.dae':(source/'mochi.dae').read_bytes(),
          'main.materials.json':b'{}', 'info.json':b'{"Name":"Fixture"}',
          'base.pc':b'{"model":"mochi","parts":{"main":"mochi"}}', 'info_base.json':b'{"Configuration":"Fixture"}'}
    target=work/'dist/ak1di_mochi.zip';target.parent.mkdir()
    with zipfile.ZipFile(target,'w') as z:
        for name,raw in data.items():z.writestr('vehicles/mochi/'+name,raw)
    result=dict(format='truemesh-static-frame-build',version=2,status='succeeded',zip_file='work/dist/ak1di_mochi.zip',zip_sha256=pipeline.digest(target))
    pipeline.write_json(output/'static_frame_build.json',result)
    return result


class StaticFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="truemesh frame ü ")
        self.root = Path(self.temp.name)
        self.source = self.root / "prepared inputs"
        self.vertices = fixture(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, name="result"):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return fixture_package(self.source, self.root / name)


    def install_fixture(self):
        self.build()
        game = self.root / "game"
        game.mkdir(); (game / "BeamNG.drive.exe").write_text("Not an executable; test fixture")
        mods = self.root / "user" / "mods"
        mods.mkdir(parents=True)
        return self.root / "result/static_frame_build.json", game, mods

    def test_install_is_idempotent_and_replacement_backs_up(self):
        receipt, game, mods = self.install_fixture()
        unrelated = mods / "other.zip"; unrelated.write_bytes(b"unrelated mod")
        first = pipeline.install(receipt, game, mods)
        self.assertEqual(pipeline.digest(Path(first["installed_file"])), first["sha256"])
        self.assertIsNone(pipeline.install(receipt, game, mods)["backup_file"])
        (mods / "ak1di_mochi.zip").write_bytes(b"older mod")
        replacement = pipeline.install(receipt, game, mods)
        self.assertEqual(Path(replacement["backup_file"]).read_bytes(), b"older mod")
        self.assertNotIn(mods, Path(replacement["backup_file"]).parents)
        self.assertEqual(unrelated.read_bytes(), b"unrelated mod")
        self.assertEqual([p.name for p in game.iterdir()], ["BeamNG.drive.exe"])
        self.assertFalse((mods / ".truemesh-install.lock").exists())

    def test_install_rejects_modified_zip_and_game_folder(self):
        receipt, game, mods = self.install_fixture()
        wrong_mods = game / "mods"; wrong_mods.mkdir()
        with self.assertRaises(ValueError): pipeline.install(receipt, game, wrong_mods)
        with (self.root / "result/work/dist/ak1di_mochi.zip").open("ab") as stream: stream.write(b"changed")
        with self.assertRaises(ValueError): pipeline.install(receipt, game, mods)
        self.assertFalse((mods / "ak1di_mochi.zip").exists())

    def test_explicit_reinstall_replaces_matching_zip_and_backs_up(self):
        receipt, game, mods = self.install_fixture()
        first = pipeline.install(receipt, game, mods)
        destination = Path(first['installed_file'])
        before = destination.read_bytes()
        with patch.object(pipeline.shutil, 'copy2', wraps=pipeline.shutil.copy2) as copying:
            result = pipeline.install(receipt, game, mods, reinstall=True)
            self.assertEqual(copying.call_count, 2)  # stage package and back up installed ZIP
        self.assertEqual(result['action'], 'reinstalled')
        self.assertEqual(Path(result['backup_file']).read_bytes(), before)
        self.assertEqual(destination.read_bytes(), before)
        self.assertEqual(pipeline.install(receipt, game, mods)['action'], 'unchanged')

    def test_reinstall_failure_preserves_installed_zip(self):
        receipt, game, mods = self.install_fixture()
        first = pipeline.install(receipt, game, mods)
        destination = Path(first['installed_file']);before = destination.read_bytes()
        original_replace = Path.replace
        def locked(path, target):
            if Path(target) == destination: raise PermissionError('fixture: game holds ZIP open')
            return original_replace(path,target)
        with patch.object(Path,'replace',locked):
            with self.assertRaises(PermissionError):pipeline.install(receipt,game,mods,reinstall=True)
        self.assertEqual(destination.read_bytes(),before)
        self.assertFalse((mods/'.truemesh-install.lock').exists())
        self.assertFalse(list(mods.glob('*.tmp')))

    def test_install_does_not_duplicate_unpacked_mod(self):
        receipt, game, mods = self.install_fixture()
        (mods / "unpacked/old_version/vehicles/mochi").mkdir(parents=True)
        with self.assertRaises(FileExistsError): pipeline.install(receipt, game, mods)
        self.assertFalse((mods / "ak1di_mochi.zip").exists())

    def test_failed_install_preserves_existing_mod_and_releases_lock(self):
        receipt, game, mods = self.install_fixture()
        destination = mods / "ak1di_mochi.zip"; destination.write_bytes(b"original mod")
        with patch.object(pipeline.shutil, "copy2", side_effect=OSError("fixture disk error")):
            with self.assertRaises(OSError): pipeline.install(receipt, game, mods)
        self.assertEqual(destination.read_bytes(), b"original mod")
        self.assertFalse((mods / ".truemesh-install.lock").exists())
        self.assertEqual(list(mods.glob("*.tmp")), [])

    def test_customization_preserves_geometry_and_original_and_installs(self):
        receipt, game, mods = self.install_fixture()
        before = receipt.read_bytes()
        original = self.root / "result/work/dist/ak1di_mochi.zip"
        original_hash = pipeline.digest(original)
        # Package-level test; image decoding/normalization is exercised by the UI test.
        image = self.root / "preview.jpg"; image.write_bytes(b'\xff\xd8fixture\xff\xd9')
        profile = self.root / "profile.json"
        profile.write_text(json.dumps(dict(Name='Frame ü',Brand='Mochi',Author='Test',Description='A frame',Configuration='CAD',PreviewImage=str(image))))
        with contextlib.redirect_stdout(io.StringIO()): result = pipeline.customize(receipt,profile,self.root/'named')
        self.assertEqual(receipt.read_bytes(),before)
        self.assertEqual(pipeline.digest(original),original_hash)
        with zipfile.ZipFile(original) as old, zipfile.ZipFile(self.root/'named'/result['zip_file']) as new:
            for name in ('mochi.jbeam','mochi.dae','base.pc','main.materials.json'):
                self.assertEqual(old.read('vehicles/mochi/'+name),new.read('vehicles/mochi/'+name))
            self.assertEqual(json.loads(new.read('vehicles/mochi/info.json'))['Name'],'Frame ü')
            self.assertEqual(json.loads(new.read('vehicles/mochi/info_base.json'))['Configuration'],'CAD')
            self.assertEqual(new.read('vehicles/mochi/default.jpg'),image.read_bytes())
            self.assertEqual(new.read('vehicles/mochi/base.jpg'),image.read_bytes())
        installed=pipeline.install(self.root/'named/static_frame_build.json',game,mods)
        self.assertEqual(installed['sha256'],result['zip_sha256'])

    def test_customization_rejects_bad_image_and_modified_build(self):
        receipt, _, _ = self.install_fixture()
        profile=self.root/'profile.json';image=self.root/'fake.jpg';image.write_bytes(b'not an image')
        profile.write_text(json.dumps(dict(Name='Frame',Brand='',Author='',Description='',Configuration='CAD',PreviewImage=str(image))))
        with self.assertRaises(ValueError):pipeline.customize(receipt,profile,self.root/'invalid')
        self.assertFalse((self.root/'invalid').exists())
        with (self.root/'result/work/dist/ak1di_mochi.zip').open('ab') as stream:stream.write(b'changed')
        with self.assertRaises(ValueError):pipeline.customize(receipt,profile,self.root/'changed')

    def test_customization_can_remove_preview(self):
        receipt, _, _ = self.install_fixture()
        profile=self.root/'profile.json';image=self.root/'image.jpg';image.write_bytes(b'\xff\xd8fixture\xff\xd9')
        data=dict(Name='Frame',Brand='',Author='',Description='',Configuration='CAD',PreviewImage=str(image))
        profile.write_text(json.dumps(data))
        with contextlib.redirect_stdout(io.StringIO()):pipeline.customize(receipt,profile,self.root/'first')
        data['PreviewImage']='';profile.write_text(json.dumps(data))
        with contextlib.redirect_stdout(io.StringIO()):pipeline.customize(self.root/'first/static_frame_build.json',profile,self.root/'removed')
        with zipfile.ZipFile(self.root/'removed/work/dist/ak1di_mochi.zip') as archive:
            self.assertEqual(set(archive.namelist()),{f'vehicles/mochi/{n}' for n in pipeline.PACKAGE_FILES})


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--make-fixture":
        fixture(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--make-package":
        fixture_package(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
