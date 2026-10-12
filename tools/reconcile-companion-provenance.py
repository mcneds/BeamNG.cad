"""Stage or apply metadata-only reconciliation of an already merged donor review.

Native CAD and project assignments are never written. Version 4 prevents older
updaters from ignoring replacement ownership. Keep the review as the recorded
appearance source; this is not a live link to an unsaved donor document.
"""
import argparse
import copy
import datetime
import json
import os
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def scopes(component):
    result = {}
    for name, selections in [("cad", component.get("Selections")),
                             ("appearance", component.get("AppearanceSelections"))]:
        if selections:
            result[name] = [s["ComponentReference"] + "|" + s["Reference"] for s in selections]
    for piece in (component.get("AppearanceCoilover") or {}).get("Pieces", []):
        if piece.get("Selections"):
            result["coilover:" + piece["Kind"]] = [s["ComponentReference"] + "|" + s["Reference"] for s in piece["Selections"]]
    return [{"Key": k, "Value": v} for k, v in result.items()]


def stage(receipt_path, destination):
    original = receipt_path.read_bytes()
    receipt = load(receipt_path)
    assert receipt["Format"] == "beamng-association-assembly" and receipt["Status"] == "completed"
    current = load(receipt["Project"])
    definitions = {c["Id"]: c for c in current["Components"]}
    files = []
    overridden = []
    for group in receipt["Groups"]:
        if not group.get("SourceOverride"):
            continue
        source = load(group["SourceProject"])
        assert Path(group["SourceDocument"]).is_file()
        source_component = next(c for c in source["Components"] if c["Id"] == group["Id"])
        assert group["Id"] in definitions
        configuration = source_component["Configuration"]
        group["SourceConfiguration"] = configuration
        group["Scopes"] = scopes(source_component)
        assert set(k for s in group["Scopes"] for k in s["Value"]) == set(group["SourceBodies"])
        for part in group.get("Members") or [group]:
            part.update(SourceOverride=True, SourceConfiguration=configuration,
                        SourceDocument=group["SourceDocument"], SourceProject=group["SourceProject"],
                        NativePartCopy=True, AppearanceSnapshot=True)
            assert Path(part["Part"]).is_file()
            assert len(part["SourceBodies"]) == len(part["CopiedBodies"]) > 0
            assert len(set(part["CopiedBodies"])) == len(part["CopiedBodies"])
            assert all(len(k.split("|")) == 2 for k in part["SourceBodies"])
            provenance = {"Format": receipt["Format"], "Version": 4, "Status": "completed",
                          "SourceDocument": part["SourceDocument"], "SourceProject": part["SourceProject"],
                          "Configuration": configuration, "Groups": [copy.deepcopy(part)]}
            files.append((Path(part["Part"] + ".appearance-provenance.json"), provenance))
        overridden.append(group["Id"])
    assert overridden, "No reviewed replacements recorded"
    receipt["Version"] = 4
    receipt["Notes"] = [n for n in receipt.get("Notes", []) if "Legacy source-refresh does not support" not in n]
    receipt["Notes"].append(f"Reconciled {len(overridden)} reviewed replacement groups: companion-owned geometry retained during original-source updates and full refresh. Appearances use the saved review in native part coordinates. Keep that review and its dependencies.")
    files.append((receipt_path, receipt))
    destination.mkdir(parents=True, exist_ok=False)
    manifest = []
    for index, (target, value) in enumerate(files):
        staged = destination / f"{index:03d}-{target.name}"
        staged.write_text(json.dumps(value, indent=2), encoding="utf-8")
        manifest.append({"target": str(target), "staged": str(staged)})
    (destination / "receipt-before.json").write_bytes(original)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Staged {len(overridden)} replacement groups / {len(files)-1} part provenance records: {destination}")


def apply(destination):
    manifest = load(destination / "manifest.json")
    root = Path(manifest[-1]["target"])
    assert root.name == "working-assembly.json"
    assert root.read_bytes() == (destination / "receipt-before.json").read_bytes(), "Receipt changed since staging"
    backups = []
    for item in manifest:
        target = Path(item["target"])
        assert target.is_relative_to(root.parent), "Target outside companion directory"
        assert target == root or target.name.endswith(".SLDPRT.appearance-provenance.json")
        previous = target.read_bytes() if target.exists() else None
        if previous is not None:
            (destination / ("before-" + Path(item["staged"]).name)).write_bytes(previous)
        backups.append((target, previous))
    written = []
    try:
        for item, (target, previous) in zip(manifest, backups):
            assert (target.read_bytes() if target.exists() else None) == previous, "Metadata changed during apply"
            temporary = target.with_name(target.name + ".reconcile.tmp")
            temporary.write_bytes(Path(item["staged"]).read_bytes())
            os.replace(temporary, target)
            written.append((target, previous))
    except Exception:
        for target, previous in reversed(written):
            if previous is None:
                target.unlink()
            else:
                target.write_bytes(previous)
        raise
    (destination / "applied.json").write_text(json.dumps({"status": "applied", "native_files_changed": False, "project_assignments_changed": False, "files": manifest}, indent=2))
    print("Applied metadata only; native geometry, mates and project assignments unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        apply(args.destination)
    else:
        stage(args.receipt, args.destination)
