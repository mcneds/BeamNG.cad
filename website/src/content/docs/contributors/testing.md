---
title: "Testing the application"
description: "Testing the application — beamng.cad documentation."
sidebar:
  order: 2
---

Application tests and native physics qualification serve different purposes. A unit-test pass is not acceptance of a new generated vehicle.

## Standard local regression

From the project root:

```powershell
powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-All.ps1
```

This builds an isolated GUI-check output, runs Python tests, checks command resources/cancellation and exercises real WinForms controls against isolated fixtures. Pass `-PythonExecutable 'C:\path\to\python.exe'` if automatic discovery is unsuitable.

## Numerical integration

```powershell
& $calibrationPython tools/run_calibration_tests.py
```

Set `$calibrationPython` to your configured interpreter first. The runner puts the checked-in harness/wizard ahead of editable packages from other checkouts.

Focused tests cover geometry selection, component mass, coilover assignments, joints, calibration controls and cancellation. Select the existing test associated with the changed subsystem instead of treating historical test totals as a current baseline.

## Native CAD tests

```powershell
powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-Cad.ps1
```

This requires SolidWorks and creates owned fixture documents under build output. It checks nested/overlapping selections, transforms, identity and deleted-reference behaviour. `Test-LiveAddin.ps1` additionally requires IDs from the intended live session.

Native fixture scripts can create documents, change owned fixture state and launch processes. Read each script's parameters and ownership contract before use.

## BeamNG acceptance

Use the generated manifest and dedicated profile described in [Verification](/guides/verification/). Preserve the exact build and recorder identities. Rendered review, functional driving acceptance and physical qualification remain separately reported.

The website implementation was checked independently. No fresh SolidWorks or BeamNG acceptance is implied by a documentation build.

## Speed, bump steer and recovery diagnostics

Use the sealed vehicle manifest with `tools/probe-drive-execution.py --scenario steady_speed --target-speed 5` (or `10`, `15`, in m/s). Supply `--mode null --physics-only --deterministic`, an owned `--profile`, a new `--output` directory and `--test-timeout 300`. The 55-second diagnostic ramps the target at 0.75 m/s² and controls throttle/brakes only; steering stays at zero. Each invocation starts a fresh owned vehicle session. The installed mod and exported physical properties are unchanged.

Run two recordings at each target. `tools/analyze-steady-speed.py RUN... --output REPORT.json` checks recording identities and telemetry, and compares actual toe/camber with the CAD-derived rigid-link prediction at measured travel and recorded actuator targets. Eligible windows start after 30 seconds, remain within 0.25 m/s of target and 0.15 m/s² longitudinal acceleration, and last at least five uninterrupted seconds. Missing holds are reported as `unsettled_speed`, not accepted measurements. The output separates expected toe, toe residual, chassis roll, tie loads, body deformation and path curvature. It also generates level-bump and opposite-wheel-travel reference plots. Positive toe denotes left steering; path curvature is reported positive to the right.

The reference uses the sealed CAD hardpoints and checks side labels and constant zero-input steering targets. It is not a fresh SolidWorks mate capture. Predicted toe uses observed suspension travel, so agreement alone cannot establish which force initiated a turn. A completed speed hold is not a handling or material qualification, and eliminating drift is not the acceptance criterion.

For controlled travel-stop recovery, use `tools/probe-suspension-rate.py MANIFEST --recovery-force 250 --corner FR --profile PROFILE --output RUN`, followed by 500 and 1000 N only if the preceding recording is valid. A zero-force control is also supported. This owned fixture pins the chassis, removes gravity, keeps the gearbox neutral and applies the declared preload bias. The additional hub force rises smoothly over two seconds, holds for two, and releases over two; recording continues through 24 seconds. Geometry, node masses, springs, dampers and stops stay unchanged. `tools/analyze-suspension-recovery.py RUN... --output REPORT.json` checks the native spring law, stop engagement and recovery. Provisional recovery screening requires final shock-speed RMS ≤0.01 m/s, length within 2 mm of the pre-load state, and remaining elastic stop force ≤1 N. This bounded vertical fixture does not establish safety under arbitrary node dragging or tire-ground impacts.

The focused regression commands are `python -m unittest discover -s tests -p test_steady_speed.py` and `python -m unittest discover -s tests -p test_suspension_rate.py`. Actual shock specifications and numerical mass/inertia differences remain separate qualification limitations.

## Physics-rate vibration and single-node disturbances

Add `--frequency-window 40 2 --frequency-targets --frequency-loads --frequency-velocities --frequency-wheels --frequency-carriers` to a steady-speed probe for a bounded 2 kHz capture. Run `tools/analyze-suspension-frequency.py RUN` to compare every recorded position with the CAD mechanism at measured travel and actuator target. This checks timestamp continuity, fresh physics positions, reference convergence and an intact speed hold. Ordinary driving spectra are not a measured force-input frequency response. Coherence uses at least three overlapping segments; a single segment would misleadingly report unity even for unrelated signals.

`tools/audit-node-force-balance.py RUN` checks recorded native force against mass times velocity increments with the separately established one-step timing convention. `tools/audit-upper-arm-force-response.py RUN` then decomposes sparse upper-arm deformation into transmitted force, inertia, gravity and moving-pivot contributions over the captured window. This explains an existing recording; it does not predict how tire contact forces will change after tuning. The carrier witness audit requires internally isolated witness nodes and is inapplicable when the generated upright has none.

For an unpinned disturbance on the ground:

```powershell
python tools/probe-node-perturbation.py MANIFEST --force 250 --corner FR --profile PROFILE --output RUN
python tools/analyze-node-perturbation.py RUN
```

Start with a zero-force control, then 250, 500 and 1000 N only while preceding recordings remain valid. This 18-second fixture keeps gravity, puts the gearbox in neutral and applies an alternating world-X force at 2 Hz to one outer axle node between seconds 6 and 10, fading in and out over 0.25 seconds. It preserves passive physics and geometry. The analysis rejects altered waveforms, missing/nonfinite telemetry and job identity mismatches. Recovery screening requires zero broken beams, no native instability message, upright orientation (`up_z > 0.5`) and peak relative node speed below 0.5 m/s after second 16. These are bounded numerical recovery checks, not physical suspension qualification or an emulation of the interactive grabber's displacement controller.

Run `python -m unittest discover -s tests -p test_suspension_frequency.py` and `python -m unittest discover -s tests -p test_node_perturbation.py` after changing these tools. Preserve reports and source hashes with each capture. Manufacturer spring/preload/stroke data, damper force-velocity curves and tire measurements remain necessary to judge physical accuracy; an explicit saved coefficient is not evidence that it was measured.
