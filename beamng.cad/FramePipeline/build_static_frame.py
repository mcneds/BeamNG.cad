"""Validate, customize and install completed frame packages."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid
import zipfile
import re
import xml.etree.ElementTree as ET
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_identity import layout, export as export_identity, verify_export

INPUTS = ("mochi_hull.off", "mochi.dae", "material.json",
          "main.materials.json", "vehicle_info_settings.json")
PACKAGE_FILES = ("mochi.jbeam", "mochi.dae", "main.materials.json", "info.json", "base.pc", "info_base.json")

def validate_package(zipped, record=None):
    model, _, jbeam, dae = layout(record or {})
    prefix = 'vehicles/' + model + '/'
    required = {prefix+n for n in (jbeam, dae, *PACKAGE_FILES[2:])}
    allowed = required | {prefix+n for n in ('default.jpg','base.jpg','lua/controller/cadSkin.lua')}
    if prefix+dae in zipped.namelist():
        root=ET.fromstring(zipped.read(prefix+dae))
        ns={'c':'http://www.collada.org/2005/11/COLLADASchema'}
        for image in root.findall('c:library_images/c:image/c:init_from',ns):
            name=image.text or ''
            if not re.fullmatch(r'cad_texture_[0-9a-f]{24}\.color\.png',name):
                raise ValueError('Invalid packaged CAD texture reference: '+name)
            target=prefix+name;required.add(target);allowed.add(target)
            if target not in zipped.namelist() or hashlib.sha256(zipped.read(target)).hexdigest()[:24]!=name[len('cad_texture_'):-len('.color.png')]:
                raise ValueError('Missing or altered packaged CAD texture: '+name)
    if record and record.get('component_files'):
        allowed=set(record['component_files'])
        if not required<=allowed or any(not n.startswith(prefix) or '..' in Path(n).parts or '\\' in n for n in allowed):
            raise ValueError('Invalid component asset manifest')
        required=allowed
    names = zipped.namelist()
    if not required <= set(names) <= allowed or len(names) != len(set(names)) or zipped.testzip() is not None:
        raise ValueError("Invalid static-frame package")

def completed_build(receipt):
    receipt = Path(receipt).resolve()
    record = json.loads(receipt.read_text(encoding="utf-8"))
    if record.get('format') != 'truemesh-static-frame-build' or record.get('version') not in (1,2) or record.get('status') != 'succeeded':
        raise ValueError("Select a completed static-frame build")
    if record.get("zip_file") != 'work/dist/'+layout(record)[1] or (receipt.parent / "cancelled.txt").exists():
        raise ValueError("Invalid or cancelled build")
    archive = (receipt.parent / record["zip_file"]).resolve()
    if not archive.is_file() and (receipt.parent/'diagnostics-pruned.json').is_file():
        raise ValueError('This superseded build was pruned to recover disk space. Regenerate it from its saved inputs or select a retained build.')
    if receipt.parent not in archive.parents or digest(archive) != record.get("zip_sha256"):
        raise ValueError("The generated ZIP has changed since this build")
    with zipfile.ZipFile(archive) as zipped: validate_package(zipped, record)
    validate_calibration_record(record, receipt, archive)
    return record, archive


def validate_calibration_record(record, receipt, archive):
    if record.get('identity_export'):
        source = receipt.parent/'identity/source.jbeam'
        with zipfile.ZipFile(archive) as zipped:
            model, _, jbeam, _ = layout(record)
            verify_export(record, source.read_bytes(), zipped.read('vehicles/'+model+'/'+jbeam))
    elif record.get('component_files'):
        manifest=receipt.parent/'manifest.json'
        if digest(manifest)!=record.get('component_manifest_sha256'):raise ValueError('Component manifest changed')
        if json.loads(manifest.read_text())['files']!=record['component_files']:raise ValueError('Component asset manifest differs')
        provenance=record.get('component_provenance_sha256',{})
        if json.loads(manifest.read_text()).get('provenance_files',{})!=provenance:raise ValueError('Component provenance manifest differs')
        for name,expected in provenance.items():
            file=(receipt.parent/name).resolve()
            if not file.is_relative_to(receipt.parent/'provenance') or digest(file)!=expected:raise ValueError('Component provenance changed: '+name)
        with zipfile.ZipFile(archive) as zipped:
            for name,expected in record['component_files'].items():
                if hashlib.sha256(zipped.read(name)).hexdigest()!=expected:raise ValueError('Component asset changed: '+name)
    elif record.get('identity'):
        raise ValueError('Namespaced build is missing export provenance')
    if not record.get('calibration'): return
    hashes = record.get('calibration_files_sha256')
    if not hashes: raise ValueError('Calibrated build is missing its provenance files')
    for name, expected in hashes.items():
        path = (receipt.parent/name).resolve()
        if receipt.parent not in path.parents or digest(path) != expected:
            raise ValueError('Calibration provenance changed: '+name)
    with zipfile.ZipFile(archive) as zipped:
        model, _, jbeam, _ = layout(record)
        actual = hashlib.sha256(zipped.read('vehicles/'+model+'/'+jbeam)).hexdigest()
        expected = record['identity_export']['exported_sha256'] if record.get('identity') else record['calibration']['vehicle_sha256']
        if actual != expected:
            raise ValueError('Packaged JBeam differs from the calibrated artifact')

def customize(receipt, profile_path, output, project=None):
    """Create a new package revision; keep the original build and geometry intact."""
    receipt, output = Path(receipt).resolve(), Path(output).resolve()
    record, archive = completed_build(receipt)
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8-sig"))
    for key in ("Name", "Brand", "Author", "Description", "Configuration"):
        if not isinstance(profile.get(key), str) or len(profile[key]) > 2000:
            raise ValueError("Invalid mod setting: " + key)
    if not profile["Name"].strip() or not profile["Configuration"].strip():
        raise ValueError("Vehicle and configuration names are required")
    image = None
    if profile.get("PreviewImage"):
        image = Path(profile["PreviewImage"]).read_bytes()
        if len(image) > 10*1024*1024 or not image.startswith(b'\xff\xd8') or not image.endswith(b'\xff\xd9'):
            raise ValueError("Choose a valid JPEG preview under 10 MB")
    with zipfile.ZipFile(archive) as zipped:
        contents = {n: zipped.read(n) for n in zipped.namelist()}
    original = None
    if project:
        project_data = json.loads(Path(project).read_text(encoding='utf-8-sig'))
        contents, record, original = export_identity(contents, record, project_data['Identity'])
    prefix = 'vehicles/' + layout(record)[0] + '/'
    info = json.loads(contents[prefix+"info.json"])
    for key in ("Name", "Brand", "Author", "Description"): info[key] = profile[key].strip()
    config = json.loads(contents[prefix+"info_base.json"])
    config.update(Configuration=profile["Configuration"].strip(), Description=profile["Description"].strip())
    for name, data in (("info.json", info), ("info_base.json", config)):
        contents[prefix+name] = (json.dumps(data, indent=2, ensure_ascii=False)+"\n").encode("utf-8")
    for name in ("default.jpg", "base.jpg"):
        contents.pop(prefix+name, None)
        if image is not None: contents[prefix+name] = image
    output.mkdir(parents=True, exist_ok=False)
    result = dict(record, status="running", parent_receipt=str(receipt), customization=profile)
    new_receipt = output/"static_frame_build.json"
    write_json(new_receipt, result)
    try:
        if record.get('calibration'):
            shutil.copytree(receipt.parent/'calibration', output/'calibration')
        if original is not None:
            (output/'identity').mkdir()
            (output/'identity/source.jbeam').write_bytes(original)
        elif record.get('identity_export'):
            shutil.copytree(receipt.parent/'identity', output/'identity')
        if record.get('component_files'):
            if record.get('component_provenance_sha256'):shutil.copytree(receipt.parent/'provenance',output/'provenance')
            manifest=json.loads((receipt.parent/'manifest.json').read_text())
            manifest['files']={name:hashlib.sha256(data).hexdigest() for name,data in contents.items()}
            for name,data in contents.items():
                asset=output/name;asset.parent.mkdir(parents=True,exist_ok=True);asset.write_bytes(data)
            write_json(output/'manifest.json',manifest)
            result.update(component_files=manifest['files'],component_manifest_sha256=digest(output/'manifest.json'))
            # The new metadata manifest has its own identity. Prior evidence
            # remains reachable via parent_receipt, never claimed for this file.
            result.update(recording_status='not_run',qualification_status='diagnostic')
            result.pop('mounting_verification_sha256',None)
        target = output/record['zip_file']
        target.parent.mkdir(parents=True)
        with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as zipped:
            for name, data in contents.items(): zipped.writestr(name,data)
        with zipfile.ZipFile(target) as zipped: validate_package(zipped, result)
        validate_calibration_record(result, new_receipt, target)
        result.update(status="succeeded",zip_sha256=digest(target))
        # This revision contains the package only; retain provenance via parent_receipt.
        result.pop("unpacked_directory",None);result.pop("material_source",None)
        write_json(new_receipt,result)
        print("CUSTOMIZED "+str(new_receipt),flush=True)
        return result
    except BaseException as error:
        result.update(status="failed",error=str(error));write_json(new_receipt,result);raise


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_inputs(source):
    for name in INPUTS:
        if not (source / name).is_file():
            raise FileNotFoundError(f"Required prepared frame input is missing: {source / name}")
    settings = json.loads((source / "vehicle_info_settings.json").read_text(encoding="utf-8-sig"))
    # The preserved generator uses these identities throughout its JBeam and package.
    for key, expected in {"modelId": "mochi", "mainPartName": "mochi", "defaultConfig": "base",
                          "generatedJBeam": "mochi.jbeam", "generatedPartName": "mochi"}.items():
        if settings.get(key) != expected:
            raise ValueError(f"This generator requires vehicle_info_settings.json: {key}={expected!r}")




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--install", type=Path, help="Install a completed static_frame_build.json")
    parser.add_argument("--game", type=Path)
    parser.add_argument("--mods", type=Path)
    parser.add_argument("--reinstall", action="store_true", help="Replace the installed ZIP even when its hash already matches; back up the previous ZIP")
    parser.add_argument("--customize", type=Path, help="Create a named/image package revision from a completed build")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--project", type=Path, help="Project metadata supplying a stable package identity")
    args = parser.parse_args()
    if args.reinstall and not args.install: parser.error("--reinstall requires --install")
    if args.customize:
        if not args.profile or not args.output: parser.error("--customize requires --profile and --output")
        customize(args.customize,args.profile,args.output,args.project)
    elif args.install:
        if not args.game or not args.mods: parser.error("--install requires --game and --mods")
        result = install(args.install, args.game, args.mods, reinstall=args.reinstall)
        print("INSTALLED " + result["installed_file"], flush=True)
        print("INSTALL ACTION " + result["action"], flush=True)
        if result["backup_file"]: print("BACKUP " + result["backup_file"], flush=True)
    else:
        parser.error("Choose --install or --customize. Frame generation requires the calibrated pipeline.")


@contextlib.contextmanager
def install_lock(path):
    path.open("x").close()
    try:
        yield
    finally:
        path.unlink()


def install(receipt, game, mods, reinstall=False):
    receipt, game, mods = Path(receipt).resolve(), Path(game).resolve(), Path(mods).resolve()
    if not (game / "BeamNG.drive.exe").is_file():
        raise ValueError("Select the BeamNG installation folder containing BeamNG.drive.exe")
    if mods.name.lower() != "mods" or mods == game or game in mods.parents:
        raise ValueError("Select the mods folder in your BeamNG user folder, outside the game installation")
    if not mods.is_dir(): raise FileNotFoundError(f"Mods folder does not exist: {mods}")
    record, archive = completed_build(receipt)
    model, zip_name, _, _ = layout(record)
    unpacked = list((mods / 'unpacked').glob('*/vehicles/'+model))
    # A differently named ZIP can still define the same internal vehicle.
    duplicates = []
    for other in [*mods.glob('*.zip'), *(mods/'repo').glob('*.zip')]:
        if other == mods/zip_name: continue
        try:
            with zipfile.ZipFile(other) as z:
                if any(n.startswith('vehicles/'+model+'/') for n in z.namelist()): duplicates.append(other)
        except zipfile.BadZipFile: continue
    if unpacked or duplicates:
        raise FileExistsError('Another package defines vehicle '+model+'; resolve that duplicate first')
    destination = mods / zip_name
    staged = mods / (".truemesh-" + uuid.uuid4().hex + ".tmp")
    backup = None
    # Exclusive creation serializes add-in installs into this mods folder.
    lock = mods / ".truemesh-install.lock"
    with install_lock(lock):
        try:
            existed = destination.exists()
            matches = existed and digest(destination) == record["zip_sha256"]
            action = "unchanged"
            if reinstall or not matches:
                shutil.copy2(archive, staged)
                if digest(staged) != record["zip_sha256"]: raise IOError("Staged mod failed its hash check")
                if destination.exists():
                    backups = mods.parent / "TrueMeshExporter-backups"
                    backups.mkdir(exist_ok=True)
                    backup = backups / (Path(zip_name).stem + '-' + uuid.uuid4().hex + '.zip.bak')
                    shutil.copy2(destination, backup)
                    if digest(backup) != digest(destination): raise IOError("Installed mod changed during backup")
                staged.replace(destination)
                action = "reinstalled" if matches else "replaced" if existed else "installed"
            result = {"format": "truemesh-static-frame-install", "version": 1,
                      "installed_file": str(destination), "sha256": record["zip_sha256"],
                      "backup_file": str(backup) if backup else None, "game_directory": str(game),
                      "action": action, "reinstall_requested": reinstall}
        finally:
            if staged.exists(): staged.unlink()
    # This receipt is separate from the wizard's project and test manifests.
    write_json(receipt.parent / "installation.json", result)
    return result


if __name__ == "__main__":
    main()
