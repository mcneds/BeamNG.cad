"""Snapshot and build the existing Mochi pipeline without editing its sources."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from .models import HarnessProject, ParameterSet, TestScenario

SOURCES = ("JBeamShellGenerator.py", "mochi_hull.off", "mochi_raw.jbeam", "material.json",
           "mochi.dae", "main.materials.json", "info.json", "base.pc", "info_base.json")
ASSETS = ("mochi.dae", "main.materials.json", "info.json", "base.pc", "info_base.json")


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def node_table(part):
    result = {}
    defaults = {}
    for row in part.get("nodes", [])[1:]:
        if isinstance(row, dict):
            defaults.update(row)
        elif isinstance(row, list) and len(row) >= 4:
            options = defaults | (row[4] if len(row) > 4 and isinstance(row[4], dict) else {})
            result[row[0]] = {"position": row[1:4], "mass": options.get("nodeWeight", 1), "options": options}
    return result


def beam_table(part):
    defaults = {}
    result = []
    for row in part.get("beams", [])[1:]:
        if isinstance(row, dict):
            defaults.update(row)
        elif isinstance(row, list):
            options = defaults | (row[2] if len(row)>2 and isinstance(row[2],dict) else {})
            result.append({"a": row[0], "b": row[1], "spring": options.get("beamSpring"),
                           "damp": options.get("beamDamp"), "deform": options.get("beamDeform"),
                           "strength": options.get("beamStrength")})
    return result


def validate_part(part, scenario):
    nodes = node_table(part)
    if not nodes:
        raise ValueError("JBeam contains no nodes")
    for name, node in nodes.items():
        if not all(math.isfinite(float(x)) for x in node["position"]) or not math.isfinite(node["mass"]) or node["mass"] <= 0:
            raise ValueError(f"Invalid node: {name}")
    missing = set(scenario.fixed_nodes + scenario.load_nodes) - nodes.keys()
    if missing:
        raise ValueError(f"Fixture nodes missing: {sorted(missing)}")
    for row in part.get("beams", [])[1:]:
        if isinstance(row, list) and (row[0] not in nodes or row[1] not in nodes):
            raise ValueError(f"Beam references missing node: {row[:2]}")
    from .torsion import table
    for bar in table(part):
        if len(set(bar['nodes']))!=4 or any(n not in nodes for n in bar['nodes']):raise ValueError('Torsion bar references invalid nodes')
        if any(not math.isfinite(float(bar['options'].get(k,0))) or float(bar['options'].get(k,0))<0 for k in ('spring','damp','deform','strength')):
            raise ValueError('Invalid torsion-bar properties')
    return nodes


def spring_fixture(parameters):
    # Three orthogonal springs; downward force compresses the vertical spring.
    # Cross springs contribute only O(displacement**3) restoring force in Z.
    return {"mochi": {
        "information": {"name": "Harness spring fixture", "authors": "Frame harness"},
        "slotType": "main",
        "refNodes": [["ref:", "back:", "left:", "up:"], ["a", "b", "c", "p"]],
        "nodes": [["id", "posX", "posY", "posZ"],
                  {"nodeWeight": 1, "collision": False, "selfCollision": False},
                  ["a", 0, 0, 0], ["b", 0, 1, 1], ["c", 1, 0, 1], ["p", 0, 0, 1]],
        "beams": [["id1:", "id2:"],
                  {"beamSpring": 1000 * parameters.spring_scale,
                   "beamDamp": 4 * parameters.damping_scale, "beamDeform": 1e20, "beamStrength": 1e20},
                  ["a", "p"], ["b", "p"], ["c", "p"]]}}


def build_candidate(project: HarnessProject, run: Path, parameters: ParameterSet, scenario: TestScenario, *, shared=None):
    from .generation import inputs, load_artifact
    generation = inputs(project)
    parameters.validate()
    scenario.validate()
    snapshot, work, vehicle = run / "source", run / "build", run / "vehicle"
    for path in (snapshot, work, vehicle):
        path.mkdir(parents=True)
    hashes, commands = {}, []
    shared_assets = {}
    if scenario.name.startswith("spring"):
        data = spring_fixture(parameters)
        if scenario.name != "spring":
            data['mochi']['beams'][2].append({'beamDeform':8 if scenario.name=='spring-yield' else 1e20,
                                            'beamStrength':12 if scenario.name=='spring-break' else 1e20})
    elif parameters.calibration:
        artifact = Path(parameters.calibration).resolve()
        spec, generated = load_artifact(project, artifact)
        hashes = spec['source_hashes']
        if shared is not None:
            shared.snapshot({name:project.source/name for name in generation['sources']},run/'shared-source.json')
        else:
            for name in generation['sources']:
                shutil.copy2(project.source/name,snapshot/name)
        if shared is not None:
            assets = {name:project.source/name for name in generation['assets']}
            assets.update({target:project.source/name for name,target in generation.get('runtime_assets',{}).items()})
            shared_assets = shared.snapshot(assets, run/'shared-assets.json')
        else:
            for name in generation['assets']:
                shutil.copy2(project.source/name,vehicle/name)
            from .generation import copy_runtime_assets
            copy_runtime_assets(project,vehicle)
        shutil.copy2(artifact,run/'calibration.json')
        shutil.copy2(generated,work/'calibrated.jbeam')
        data=json.loads(generated.read_text())
    else:
        raise ValueError('A calibrated artifact is required for frame recordings. Prepare and calibrate this generation first.')

    part = data["mochi" if scenario.name.startswith("spring") else generation["part"]]
    validate_part(part, scenario)
    for row in part["nodes"][1:]:
        if isinstance(row,list) and scenario.gravity == 0:
            if len(row)==4: row.append({})
            # Isolated actuator fixtures measure the frame without floor or
            # self-contact reactions. Production artifacts retain collisions.
            row[4].update(collision=False,selfCollision=False)
        if isinstance(row, list) and row[0] in scenario.fixed_nodes:
            if len(row) == 4:
                row.append({})
            row[4]["fixed"] = True
    nodes = node_table(part)
    vehicle_file = "mochi.jbeam" if scenario.name.startswith("spring") else generation["vehicle"]
    write_json(vehicle / vehicle_file, data)
    if scenario.name.startswith("spring"):
        write_json(vehicle / "base.pc", {"format": 2, "model": "mochi", "mainPartName": "mochi", "parts": {}})
        write_json(vehicle / "info.json", {"Name": "Harness fixture", "default_pc": "base"})
    expected_beams = sum(isinstance(row, list) for row in part["beams"][1:])
    manifest = {"source_hashes": hashes, "commands": commands, "parameters": asdict(parameters),
                "scenario": asdict(scenario), "nodes": nodes, "beam_count": expected_beams,
                "beams": beam_table(part),
                "vehicle_file": vehicle_file, "part": "mochi" if scenario.name.startswith("spring") else generation["part"],
                "jbeam_sha256": sha256(vehicle / vehicle_file)}
    manifest['expected_render_regions']=next((len(row[1]['regions']) for row in part.get('controller',[])[1:]
        if isinstance(row,list) and row[0]=='cadSkin'),0)
    if shared_assets: manifest['shared_assets'] = shared_assets
    write_json(run / "build_manifest.json", manifest)
    return manifest
