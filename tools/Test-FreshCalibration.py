"""Verify fresh geometry calibration without altering or installing its baseline."""
import argparse
import math
import os
from pathlib import Path
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "beamng.cad/FramePipeline"))
import calibration_worker as worker
from frame_harness.build import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation", type=Path, required=True,
                        help="Existing generation with an accepted offline material candidate")
    parser.add_argument("--case", help="Candidate to verify; defaults to the first captured candidate")
    parser.add_argument("--scale", type=float, default=1.003)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0 or args.scale == 1:
        parser.error("--scale must be positive, finite, and different from one")
    base = args.generation.resolve()
    worker.check_snapshot(base)
    baseline = {}
    available=worker.read(base/'study/calibration-study.json')['candidates']
    selected=args.case or next(iter(available))
    if selected not in available:parser.error('Candidate is not in the selected generation')
    for case in (selected,):
        report = worker.read(base / "study" / case / "report.json")
        if not report["offline_accepted"]:
            raise ValueError("Baseline offline reference is not accepted: " + case)
        baseline[case] = report["mass"]["target_mass_kg"]
    destination = (args.output or root / "beamng.cad/bin/cad-calibration" /
                   ("fresh-calibration-" + uuid.uuid4().hex[:8])).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    prepared, job = destination / "prepared", destination / "generation"
    shutil.copytree(base / "source", prepared)
    manifest = worker.read(prepared / "generation.json")
    physical = manifest["mesh"]
    if Path(physical).name != physical:
        raise ValueError("Invalid physical CAD source")
    tree = ET.parse(prepared / physical)
    namespace = tree.getroot().tag.split("}")[0][1:]
    ET.register_namespace("", namespace)
    unit = tree.find("{%s}asset/{%s}unit" % (namespace, namespace))
    if unit is None:
        raise ValueError("Baseline CAD must declare its physical unit")
    unit.set("meter", str(float(unit.get("meter", "1")) * args.scale))
    tree.write(prepared / physical, encoding="utf-8", xml_declaration=True)
    hull = prepared / "mochi_hull.off"
    lines = hull.read_text().splitlines()
    count = int(lines[1].split()[0])
    for index in range(2, 2 + count):
        lines[index] = " ".join(str(float(value) * args.scale) for value in lines[index].split())
    hull.write_text("\n".join(lines) + "\n")
    worker.preflight()
    worker.prepare(prepared, job, base)
    review, previous = worker.read(job / "review.json"), worker.read(base / "review.json")
    assert not review["approved"], "Fixture approval must not survive regeneration"
    assert review["graph_sha256"] != previous["graph_sha256"], "Graph must change"
    assert review["fixtures"] == previous["fixtures"], "Fixture correspondence changed"
    assert review["cut_fixture"] == previous["cut_fixture"], "Cut fixture correspondence changed"
    review.update(approved=True, approval=dict(
        kind="automated regression fixture",
        basis="Uniform synthetic scaling with corresponding fixture identifiers; not a new CAD export"))
    write_json(job / "review.json", review)
    worker.calibrate(job,case=selected)
    cases = {}
    for case, mass in baseline.items():
        report = worker.read(job / "study" / case / "report.json")
        actual, expected = report["mass"]["actual_mass_kg"], mass * args.scale ** 3
        assert report["offline_accepted"], report["responses"]
        assert math.isclose(actual, expected, rel_tol=1e-8), (actual, expected)
        worker.package(job, case, destination / ("package-" + case))
        cases[case] = dict(actual_mass_kg=actual, expected_mass_kg=expected)
        print(f"PASS {case}: changed CAD mass {actual:.9f} kg", flush=True)
    write_json(destination / "fresh-verification.json", dict(
        status="passed", scale=args.scale, baseline=str(base), generation=str(job), cases=cases,
        scope="Synthetic geometry variation; fresh offline calibration and package integrity only"))
    print("FRESH_VERIFICATION=" + str(destination), flush=True)


if __name__ == "__main__":
    main()
