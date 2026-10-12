# Frame feedback harness

The harness launches BeamNG.drive in a dedicated profile, runs controlled fixtures and collects measurements. Frame runs consume a saved CAD calibration artifact. Spring instrument checks remain independent of frame calibration.

## Run it

Install the harness with Python 3.11 or newer using `python -m pip install -e .`. From this directory:

```powershell
python -m frame_harness doctor
python -m frame_harness run --scenario spring
python -m frame_harness calibrate --reference examples/4130-reference.json --output comparisons/4130-calibration --offline
python -m frame_harness run --scenario flex --name annealed --calibration comparisons/4130-calibration/4130-annealed/calibration.json --repeat 3
python -m frame_harness run --scenario torsion --name annealed --calibration comparisons/4130-calibration/4130-annealed/calibration.json --repeat 3
python -m frame_harness compare runs/BASELINE_1 runs/BASELINE_2 runs/CANDIDATE --output comparisons/latest
python -m frame_harness report runs/RUN_ID
```

Each run prints its result directory. Open `report.html` there for plots and replay. A batch file may list candidates with explicit `calibration` paths; each artifact fixes the calibrated masses and spring settings. Material and scale overrides are rejected for calibrated frame artifacts.

## Paths and isolation

Defaults match this workstation:

- Input scripts/assets: `H:\beamng project programs\Test Programs`
- Drive: `D:\SteamLibrary\steamapps\common\BeamNG.drive`
- Dedicated game profile: `%LOCALAPPDATA%\BeamNGCadHarness\drive`
- Experiments: `Test Harness\runs`

On this workstation, `project.local.json` now places the dedicated profile at `H:\BeamNGCadHarness\drive`. This avoids storing large duplicate telemetry files on the system drive. Drive rejected the nested project-folder profile during startup; the separate path above was verified in-game. The runner requires at least 1 GiB free on both the profile and archive volumes before recording, and checks CSV row counts against the recorder's completion counts before accepting a run. Temporary game files use the profile volume too.

Override paths in `project.local.json`, or pass `--project PATH` before the command. Relative paths resolve against the JSON file:

```json
{
  "source": "../../Test Programs",
  "game": "D:/SteamLibrary/steamapps/common/BeamNG.drive",
  "userpath": "%LOCALAPPDATA%/BeamNGCadHarness/drive",
  "runs": "runs",
  "startup_timeout": 180,
  "test_timeout": 120,
  "build_timeout": 300
}
```

Drive 0.39 mounts the `current/` child of `-userpath`. The harness stages its own unpacked mod there, uses a unique `fh_mochi` model name, and refuses an existing unmarked user folder. It preserves the normal game profile and source files. An OS lock prevents two harnesses from staging into the same profile. Only the process started by the current attempt is shut down.

Startup initializes the mod manager, including the update/Continue gate, loads Small Grid, waits for world readiness and the spawn callback, and starts recording. Failed launches get one retry with separate diagnostics. Ctrl+C cancels the current run and stops a batch.

## Scenarios

| Scenario | Fixture and loading | Duration |
| --- | --- | --- |
| `spring` | Three orthogonal 1,000 N/m springs, 1 kg per node, three fixed supports; 10 N downward on the free node; zero gravity | 1 s settle, 1 s ramp, 2 s hold, 4 s release |
| `idle` | Mochi just above Small Grid ground, ordinary gravity, no fixed supports or applied load | 15 s |
| `flex` | Fix `sp00l/r` and `sp02l/r`; **100 N total**, divided between `sp01l/r`, downward; zero gravity | 2 s settle, 1 s ramp, 3 s hold, 10 s release |
| `torsion` | Same fixed supports; 50 N downward at `sp01l`, 50 N upward at `sp01r`; zero gravity | Same timing as flex |

The spring check should approach 10 mm displacement at scale 1; a small geometric cross-spring correction is expected. It verifies force magnitude, supports, displacement and the full launch/measurement path before interpreting the frame.

## Interpreting measurements

`completed` means recording finished. It does **not** mean the frame matches steel, has adequate strength, or is a good design. The original idle/flex/torsion tests quantify stability and elastic response. The separate CAD calibration workflow below adds material and damage validation.

Reports include mass, shape change with rigid motion removed for idle, flex deflection and apparent stiffness, residual deformation, release oscillation, settling time, node speed, beam length/rest-length change, and breaks. Settling requires a full final second inside the tolerance band; `null` means settling was not demonstrated. Apparent stiffness is not an equilibrium stiffness when `hold_settled` is false. Residual motion is not automatically plastic deformation.

Physics callbacks run at the engine timestep, observed at 0.5 ms. Probe velocities and applied forces are recorded every callback; full node/beam trajectories are sampled at 200 Hz. **Node positions can be cached between graphics updates.** Timestamps describe read times, not guaranteed fresh 2 kHz positions. Use velocity for fast oscillation analysis. Beam force keeps the engine sign convention and is labelled `native_force`, not material stress in pascals.

Loaded tests cross-check mean hold displacement against integrated probe velocity. A mismatch above 2 micrometres or 1% of displacement, whichever is larger, marks the run `invalid_measurement`. This caught a coordinate-API mistake during development; affected early runs were excluded and repeated.

Torsion reports the applied couple in N·m, relative load-point rotation in radians, and torsional stiffness in N·m/rad. The plotted load-pattern displacement projects each node's motion onto its signed force fraction; opposite motions therefore add correctly. Recorded `fx/fy/fz` channels are checked against the requested pattern and force history. Older CSVs remain readable but cannot supply that additional vector check.

Fixed fixtures reference positions to a fixed support, avoiding jitter caused by independently updated vehicle origins and cached node positions. More than 5 micrometres of apparent support motion also invalidates a run. Idle analysis removes rigid translation and rotation instead.

Comparisons require the same geometry and scenario. The first candidate per scenario is baseline. A change is highlighted when it exceeds the baseline range, three sample standard deviations, 1% of the baseline mean, and a numerical floor. This is descriptive change detection, not a significance test or optimization objective. At least two baseline repeats are required; repeat candidates too to estimate their uncertainty.

Inspect the calibration report for fit errors and numerical limits before interpreting the live measurements as material response.

## Saved evidence

Each `runs/<id>/` contains:

- `source/`: untouched snapshots of scripts, raw JBeam, material settings and mesh/assets.
- `build/`, `vehicle/`, `build_manifest.json`: generated output, source hashes, commands and expected compiled properties.
- `harness_source/`, `experiment.json`: measurement implementation, scenario, parameters, interpreter and paths.
- `attempt-N/`: game logs, metadata, node/beam/probe/load CSVs, break events and completion/failure information.
- `metrics.json`, `response.png`, `deformation.png`, `report.html`: analysis and interactive replay with labelled display exaggeration.
- `result.json`: final status/reason. `telemetry_location.json` identifies the analyzed attempt.

Runtime files are also retained in the dedicated profile. Runs and comparisons are Git-ignored and are not automatically deleted. Reports use no cloud service or external browser library.

## Python API and maintenance

```python
from frame_harness import HarnessProject, ParameterSet, TestScenario
from frame_harness.runner import run_test

result = run_test(
    HarnessProject.load(), TestScenario.named("flex"),
    ParameterSet(name="annealed", calibration="comparisons/4130-calibration/4130-annealed/calibration.json"),
)
print(result.status, result.metrics, result.path)
```

`TestScenario` is editable for scripted experiments. Establish new baselines after changing geometry, fixtures, loads, timing or measurement implementation. Before autonomous tuning, run the spring instrument check, inspect failures, confirm the hold settled, and compare candidate changes against repeated-baseline variation. Never rank incomplete or invalid runs as improvements.

Offline checks, using the configured interpreter:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Native Lua interfaces are version-sensitive. Live integration was exercised on Drive **0.39.4.0**. After game updates, run `doctor`, the spring check and fresh baselines. BeamNGpy can become another runner later; it is not required now.

See [VALIDATION.md](VALIDATION.md) for historical harness validation and [CALIBRATION_RESULTS.md](CALIBRATION_RESULTS.md) for the recorded CAD-based 4130 measurements and mesh-separation defect.

## CAD-based 4130 calibration

```powershell
.\.venv\Scripts\python.exe -m frame_harness calibrate --reference examples/4130-reference.json --output comparisons/4130-calibration
# Continue interrupted work with identical source/configuration/implementation:
.\.venv\Scripts\python.exe -m frame_harness calibrate --reference examples/4130-reference.json --output comparisons/4130-calibration --resume
# Audit and generate without launching Drive:
.\.venv\Scripts\python.exe -m frame_harness calibrate --reference examples/4130-reference.json --output comparisons/4130-offline --offline
```

This generation path preserves all input node coordinates and beam endpoints. It measures each CAD body in the prepared `mochi.dae`, fits positive node masses to total mass, center of mass and inertia, and fits spring weights against an independent Timoshenko frame reference. It never uses the wrapped hull as the material volume. Frame runs require an explicit `--calibration` artifact.

The CAD audit checks closed, consistently oriented surfaces and measures signed tetrahedral volume integrals. It can weld tiny export seams, cancel exact opposite-winding duplicate facets and remove dangling export facets, but cannot fill missing faces. Every repair is recorded; changes must remain below 0.5% of the individual body's signed volume and 0.1% of total frame volume. Body volumes are summed, so overlapping bodies and unmodeled weld metal remain geometric uncertainties. Unresolved geometry cannot receive physical-calibration acceptance. Explicit `body_overrides` can supply `mass_properties` or a measured `section` when a future export cannot be resolved automatically.

The reference measures hollow circular cross sections from mesh/plane intersections, follows section centroids through bends, and infers fully joined contacts near member ends. Its load/support transfers retain the moments of offsets from CAD centerlines. It checks axial, bending and torsional cantilevers against analytical formulas within 2%. Inferred contacts and approximate curved-member sections remain modeling assumptions; the reference is not a measured frame test or a full solid-element stress analysis.

Both material cases use density 7,850 kg/m³, E = 205 GPa and Poisson ratio 0.29. The [Admiral Steel typical-property table](https://www.admiralsteel.com/assets/pdf/catalog.pdf) supplies these condition-dependent assumptions:

| Case | Yield stress | Ultimate tensile stress |
| --- | ---: | ---: |
| 4130 annealed | 360.6 MPa | 560.5 MPa |
| 4130 normalized | 436.4 MPa | 668.8 MPa |

The actual heat treatment is unknown. These are representative cases, not guaranteed bounds. Stiffness, first yield and ultimate capacity are separate fits. [BeamNG's beam properties](https://documentation.beamng.com/modding/vehicle/sections/beams/) define spring stiffness, permanent-deformation and break thresholds separately. `beamStrength` values derived from UTS are **elastic capacity proxies, not validated ductile rupture predictions**. Buckling, weld defects, heat-affected zones, plastic strain to fracture and fatigue need additional evidence/models. Damping ratio 0.04 and the 350 Hz stability limit are numerical choices, not properties certified for this steel.

The study checks the 1,000 N/m instrument, 8 N yielding fixture and 12 N break fixture, then screens idle/flex/torsion for both cases. Progressive loads ramp over 12 and 24 seconds, with a 20 kN actuator ceiling. Candidates that pass the offline criteria receive three independent repeats. Missing yield/break events are reported as right-censored at the applied force ceiling; absence of breakage is not a passing strength result. First persistent rest-length change, first natural beam break and first graph separation are reported separately. Per-beam signed native forces remain distinct from the external actuator load.

Destructive recordings validate position against integrated velocity over the intact interval before damage, with a tolerance accounting for observed graphics-cadence lag. They do not apply the settled elastic hold check after a support has broken. Beam events are sampled at the physics callback rate; graph separation is detected from 200 Hz topology samples. Recorded event times and graphics capture times are distinguished.

Mesh association uses distances to triangle surfaces, per-vertex locator neighborhoods with transverse support, and paths through the existing shell graph. A globally noncollinear group is insufficient: each vertex needs usable locator angles, as described in [BeamNG's flexbody documentation](https://documentation.beamng.com/modding/vehicle/sections/flexbodies/). Engine flexbody load errors are retained and prevent acceptance. Existing shell edges whose endpoints share a CAD mesh's locator group enable mesh/triangle breaking; other edges disable it. A mesh-support edge can lie away from the CAD surface, so midpoint proximity alone is insufficient. The generator does not invent per-vertex weight controls unavailable in JBeam. Two controlled cuts sever all crossing graph edges at different longitudinal planes under a small 1 N separating load. The report records which mesh groups span disconnected components. Drive automatically saves front, side and oblique views before damage, at first yield/break, after a cut and at the end. Physics pauses while the graphics views are captured; the camera centers on the vehicle's actual bounds.

Zero-gravity actuator fixtures disable ground and self-collision in their run-local vehicle so contact reactions cannot contaminate the applied-load comparison. Their reference node spawns at 3 m, keeping free cut fixtures above the floor. Idle placement accounts for the JBeam reference-node datum and lowest node. Idle tests and exported, unfixed candidates retain ordinary collision behavior. These fixture settings never modify the source or exported node coordinates/connectivity.

Open `comparisons/<study>/index.html` for the audit, candidate artifacts, individual replay/damage reports and exact acceptance failures. Each condition has a self-contained `diagnostic-mod.zip` and an unfixed `mochi.jbeam`. Source hashes, configuration and implementation hashes make reuse explicit. To test an artifact separately:

```powershell
.\.venv\Scripts\python.exe -m frame_harness run --scenario flex --name annealed --calibration comparisons/4130-calibration/4130-annealed/calibration.json
```

Acceptance requires mass within 0.1%, COM within 5 mm, inertia within 5%, elastic response within 10%, first yield within 15%, and loading-rate sensitivity and repeat spread within 5%, plus valid independent runs and image review. The image reviewer can be the coding agent inspecting the saved PNGs; no repeated user screenshots are needed. After actually inspecting the rendered evidence, record boolean decisions for each condition and concrete observations in JSON:

```json
{"cases":{"4130-annealed":false,"4130-normalized":false},"notes":"Describe inspected damage/cut views and observed attachment, stretching or missing evidence."}
```

```powershell
.\.venv\Scripts\python.exe -m frame_harness calibration-review --output comparisons/4130-calibration --review review-decisions.json
```

The review records hashes of the captured images and recomputes acceptance without rerunning Drive. A missing, stale or failed review cannot pass. `qualified-mod.zip` is produced only after all checks pass; qualification applies to these stated equivalent-model tests, not to unmeasured real-world fracture strength. Failed fits remain diagnostic artifacts and do not qualify for export.
