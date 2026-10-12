from __future__ import annotations
import argparse
import json
from pathlib import Path
from .models import HarnessProject, ParameterSet, TestScenario
from .runner import doctor, run_test


def main():
    parser = argparse.ArgumentParser(description="BeamNG.drive frame feedback harness")
    parser.add_argument("--project", type=Path, help="Optional project JSON with path overrides")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local prerequisites without launching Drive")
    run = commands.add_parser("run", help="Build and measure one candidate")
    run.add_argument("--scenario", choices=("idle", "flex", "torsion", "spring", "spring-break", "spring-yield"), default="flex")
    run.add_argument("--calibration", type=str, help="Saved CAD calibration artifact")
    run.add_argument("--name", default="baseline")
    run.add_argument("--spring-scale", type=float, default=1)
    run.add_argument("--damping-scale", type=float, default=1)
    run.add_argument("--material", type=Path, help="JSON of material overrides")
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--no-report", action="store_true")
    run.add_argument("--open-report", action="store_true", help="Open the last run's local HTML report")
    batch = commands.add_parser("batch", help="Run an explicit list of candidates sequentially")
    batch.add_argument("file", type=Path)
    batch.add_argument("--output", type=Path, help="Comparison destination (default: comparisons/<first run ID>)")
    compare = commands.add_parser("compare", help="Compare repeat groups against a baseline")
    compare.add_argument("runs", nargs="+", type=Path)
    compare.add_argument("--output", type=Path, default=Path("comparisons/latest"))
    report = commands.add_parser("report", help="Regenerate plots and replay for an existing run")
    report.add_argument("run", type=Path)

    calibrate = commands.add_parser('calibrate', help='Audit CAD, fit the fixed graph, and validate damage/mesh behavior')
    calibrate.add_argument('--reference',type=Path,default=Path('examples/4130-reference.json'))
    calibrate.add_argument('--output',type=Path,default=Path('comparisons/4130-calibration'))
    calibrate.add_argument('--resume',action='store_true')
    calibrate.add_argument('--offline',action='store_true',help='Generate and audit without launching Drive')
    review = commands.add_parser('calibration-review',help='Record rendered-image review and recompute calibration acceptance')
    review.add_argument('--output',type=Path,required=True)
    review.add_argument('--review',type=Path,required=True,help='JSON containing cases (boolean per case) and notes')
    args = parser.parse_args()
    project = HarnessProject.load(args.project)
    if args.command == 'calibration-review':
        from .acceptance import review_calibration
        review=json.loads(args.review.read_text())
        result=review_calibration(args.output,review['cases'],review['notes'])
        print(json.dumps(result['acceptance'],indent=2));return 0
    if args.command == 'calibrate':
        from .calibration import run_calibration
        result=run_calibration(project,args.reference,args.output,resume=args.resume,live=not args.offline)
        return 0 if result['status'] in ('completed','completed_with_limitations','offline_complete') else 1

    if args.command == "doctor":
        result = doctor(project)
        print(json.dumps(result, indent=2)); return 0 if result["ok"] else 1
    if args.command == "report":
        from .report import create_report
        print(json.dumps(create_report(args.run.resolve()), indent=2)); return 0
    if args.command == "compare":
        from .report import compare_runs
        print(compare_runs(args.runs, args.output)); return 0
    jobs = []
    if args.command == "batch":
        specification = json.loads(args.file.read_text())
        if not isinstance(specification.get("repeats", 1), int) or specification.get("repeats", 1) < 1:
            parser.error("Batch repeats must be a positive integer")
        for candidate in specification["candidates"]:
            for scenario in specification.get("scenarios", ["idle", "flex"]):
                for _ in range(specification.get("repeats", 1)):
                    jobs.append((TestScenario.named(scenario), ParameterSet(**candidate)))
    else:
        if args.repeat < 1:
            parser.error("--repeat must be positive")
        parameters = ParameterSet(args.name, json.loads(args.material.read_text()) if args.material else {},
                                  args.spring_scale, args.damping_scale, 'none',args.calibration)
        jobs = [(TestScenario.named(args.scenario), parameters)] * args.repeat
    if not jobs:
        parser.error("No experiments requested")
    results = []
    for scenario, parameters in jobs:
        result = run_test(project, scenario, parameters, analyze=not getattr(args, "no_report", False))
        results.append(result)
        if result.status == "cancelled":
            break
    if args.command == "batch":
        from dataclasses import asdict
        from .build import write_json
        from .report import compare_runs
        output = args.output or Path("comparisons") / results[0].run_id
        write_json(output / "batch.json", {"specification": specification, "results": [asdict(r) for r in results]})
        completed = [Path(r.path) for r in results if r.status == "completed"]
        baseline_name = specification["candidates"][0].get("name", "baseline")
        baseline_scenarios = {r.scenario for r in results if r.status == "completed" and r.candidate == baseline_name}
        if not set(specification.get("scenarios", ["idle", "flex"])).issubset(baseline_scenarios):
            print("Comparison skipped: a requested scenario has no completed baseline. See batch.json for failures.")
        elif completed:
            print(f"Comparison: {compare_runs(completed, output)}")
    if getattr(args, "open_report", False):
        report_path = Path(results[-1].path) / "report.html"
        if report_path.exists():
            import webbrowser
            webbrowser.open(report_path.resolve().as_uri())
    return 0 if all(r.status == "completed" for r in results) else 1
