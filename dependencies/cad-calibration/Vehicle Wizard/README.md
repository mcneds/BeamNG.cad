# Guided Vehicle Wizard

Open **`Launch Vehicle Wizard.cmd`** in this folder. On this workstation it opens the already imported project at `projects/mochi/project.json`, using `H:\beamng project programs\mochi blender work\mochi sep v2.blend` as the read-only CAD source.

The desktop uses PySide6 Widgets and an embedded VTK view: flat gray panels, square controls, text buttons and compact property tables. Blender runs in the background for import; BeamNG uses the existing isolated native-Lua harness. Neither a BeamNGpy license nor an interactive Blender session is required.

## First vehicle workflow

1. **Intake:** inspect the full assembly and the blue chassis graph. Confirm metres, +X left, -Y forward, +Z up and frame alignment. Use the numeric alignment controls if needed. Import is cached by source hash; reimport after changing the Blender file.
2. **Parts:** click meshes, Ctrl/Shift-select, use box selection, or select a tree collection. Name/collection matches are suggestions, not confirmed physical ownership. Assign arbitrary selections to physical components, with a role, corner and mass. A mesh has one physical owner. Overlapping selection groups remain available for convenient later selection. Explicitly assign unused bodies to `ignore`.
3. **Suspension:** place each joint center with surface/vertex picking, two-point midpoint, three-point circle center or numeric coordinates. Attach picked points to the physical component so placement edits carry them along. Mirror across X=0 if useful, then review the other side independently. Preview travel, inspect the analytical results and confirm each corner.
4. **Powertrain:** place `engine_center`, `cvt_center` and three `engine_mount_1` … `engine_mount_3` points using **Custom / powertrain point**. Enter actual engine/CVT model names, mass and available performance data. Review provisional values before accepting them.
5. **Build / test:** validate, generate, run individual scenarios or the acceptance series, then inspect the saved HTML report, telemetry plots and actual game capture. After review, install the named prototype and launch the normal game. The vehicle selector entry is **Mochi First Drive - Prototype**.

Projects save separately from Blender and source JBeam files. Undo/redo covers assignments, placement, point edits and parameter changes. Named checkpoints are JSON snapshots under `checkpoints/`; open one through the project file dialog to resume it as a branch with its own subsequent builds. Checkpoints reference the same cached geometry. Normal save/resume uses `project.json`.

Move/rotate handles operate on assigned components. Numeric controls support a pivot and local/world placement. Exploded view and suspension travel preview are display-only; reset their sliders before picking CAD points. Hide/isolate, transparency, locking and reusable selection groups help expose joint geometry. Instruction drawings animate the mechanism beside the point editor.

## Initial templates and their limits

- **Front double wishbone:** upper/lower chassis hinge pairs, upper/lower ball joints, a rigid upright, wheel bearing axis, steering tie rod and a direct coilover attached to the **lower** arm. The first steering implementation changes tie-rod length with a hydro; it does not yet model a physical translating steering rack.
- **Rear trailing arm with locating links:** a spherical chassis pivot, rigid trailing arm/upright assembly, independent constant-length locating rods and a direct coilover on the **trailing arm**. Add the actual links; the constraint check requires one remaining suspension motion. Two independent links fit this initial topology. A third nonredundant link can lock it and is rejected. A rear design with a separate articulated upright needs an additional template; do not force it into this rigid-upright variant.
- **Rear engine / mounted CVT / selectable drive:** centrifugal clutch → CVT → locked transfer case, with a disconnectable front shaft and front/rear axle differentials. The in-game drive-mode button switches RWD and mechanically coupled 4WD. Forward/reverse, service brakes and rear parking brakes use native vehicle controllers.

Starter assumptions are 10 kW at 3600 rpm, CVT 0.8–3.0, matched 8:1 final drives, open axle differentials, 1.5 Hz suspension frequency and 0.6 damping ratio. Spring rates use analytical motion ratios and an initial equal four-corner sprung-mass split. These are editable prototype assumptions, not measured hardware specifications. Engine/CVT component masses take precedence over their fallback parameter masses; wheel/tire component masses likewise replace the fallback wheel mass. Frame mass comes from the selected calibrated JBeam. Fixed accessories use a small attachment cage at the selected mesh bounds' center, a provisional center-of-mass assumption. Shafts assigned as structural components are nonrotating visual approximations in this version; the actual powertrain shafts are native logical devices.

New mount nodes borrow a small amount of mass from the existing frame nodes. Original chassis node positions, beam connections and beam properties are retained. New numerical stiffeners are limited according to incident node mass; this is stability tuning, not material calibration. Wheels use generated pressure-wheel rings with total wheel mass allocated across their nodes. Native compiled graph checks therefore allow these additional nodes/beams instead of comparing against an explicit-only node count.

Each CAD mesh exports with a stable namespaced ID. Ownership determines its flexbody node group. Blender 5 has no COLLADA exporter, so the wizard writes geometry-only DAE and a neutral material from cached triangles. Imported CAD materials/textures are not yet reproduced. Frame fracture, flexbody tearing, detailed contact/clearance, accurate joint compliance, thermal behavior and real 4130 rupture remain unqualified. A first-drive pass does not establish damage realism.

## Repeatable tests

The native runner loads Smallgrid, spawns the manifest's vehicle/config, applies inputs, records telemetry and screenshots, then closes only its own game process. It uses `Test Harness/project.local.json` and the harness-owned test profile. Continue/mod-update handling is automatic. Normal player mods are untouched until **Install named prototype mod** is clicked; replacing that named ZIP preserves a `.zip.previous` copy.

Tests cover 30-second settling, supported RWD/4WD and CVT operation, per-corner articulation, acceleration to 20 km/h within 20 seconds, braking below 1 km/h within 10 m, reverse travel and left/right low-speed turns. Acceptance repeats the entire set three times and stops at the first failure. Supported/articulation runs pin chassis nodes only in a separately archived staged fixture; the exported build has no pins. Reports identify missing/incomplete telemetry, unexpected damage, wrong mass, unavailable captures and failed criteria. The fixture verifies a mechanism, not whether a picked CAD point is the real joint center.

The work in `runtime/native-fixture` is explicitly synthetic test geometry. Its game results exercise the generator and harness. It is **not** your measured Mochi vehicle and is not installed in the normal game profile.

## CLI and API

From this folder, with its configured environment:

```powershell
.\.venv\Scripts\python.exe -m vehicle_wizard gui projects\mochi\project.json
.\.venv\Scripts\python.exe -m vehicle_wizard create projects\new\project.json --assembly C:\models\assembly.blend
.\.venv\Scripts\python.exe -m vehicle_wizard import projects\new\project.json
.\.venv\Scripts\python.exe -m vehicle_wizard validate projects\new\project.json
.\.venv\Scripts\python.exe -m vehicle_wizard build projects\new\project.json
.\.venv\Scripts\python.exe -m vehicle_wizard test <build-manifest.json> --scenario acceptance
.\.venv\Scripts\python.exe -m vehicle_wizard install <build-manifest.json> --mods <normal-profile-mods-folder>
```

GUI-free APIs: `VehicleProject`, `import_assembly`, `Mechanism`, `build_vehicle`, `install_build`, and `frame_harness.vehicle.intake/run_vehicle/run_acceptance`. The generic runner consumes a versioned `exported_vehicle` manifest independently of the conversion UI. Legacy frame calibration commands remain separate.

An immutable build directory contains the namespaced mod, source/config snapshot, analytical travel results, source hashes and file hashes. Parameter/source changes or generator changes create a new build identity. Runtime tests preserve their own job, build manifest, compiled graph, staged fixture where applicable, telemetry, logs, screenshot, scorecard and report.

## Development checks

Run `Setup Vehicle Wizard.ps1` on a new workstation with Python 3.14 installed. Blender 5.0 or later is needed for this specific assembly. For development in PyCharm, configure this folder's `.venv` as the module SDK.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\smoke_gui.py
```

The GUI smoke test uses a disposable copy of the real project and verifies loading all 1,935 meshes, selection, assignment, point motion, undo/redo and save/resume. It writes a native VTK viewport capture as well as a Qt window capture; Windows' Qt capture can show the native OpenGL region as black even though the separate VTK capture and onscreen rendering work.
