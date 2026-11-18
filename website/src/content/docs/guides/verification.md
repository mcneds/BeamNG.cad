---
title: "Verify a generated package"
description: "Verify a generated package — beamng.cad documentation."
sidebar:
  order: 12
---

Keep generation, measurement and qualification separate. Run tests against the exact new manifest and use a dedicated harness profile, not your normal play profile.

## Choose the right check

| Operation | Scope | What it does not establish |
| --- | --- | --- |
| Frame Quick | Four recordings: spring instrument, idle, flex and torsion | Damage or fracture qualification |
| Frame Full | Standard one-material schedule of 22 recordings, including repeats, damage/rate checks and captures | Acceptance without required rendered review |
| Vehicle pilot | Settle, supported drivetrain and articulation | Complete driving acceptance |
| Vehicle Verify package | Eight scenarios repeated three times; stops on failure | Real material/rupture qualification beyond the model |
| Attachment verification | Mount loading, commanded release and force-driven release | Full vehicle driving acceptance |

Quick is the frame UI default. The calibration CLI defaults to Full unless `--verification quick` is supplied.

## First vehicle pilot

From the checkout root, set the four paths for your machine:

```powershell
$calibrationPython = 'C:\BeamNGCad\venv\Scripts\python.exe'
$manifest = 'C:\BeamNGCad\builds\vehicle\manifest.json'
$game = 'D:\SteamLibrary\steamapps\common\BeamNG.drive'
$profile = 'C:\BeamNGCad\harness'

& $calibrationPython tools/test-synthetic-vehicle.py $manifest --scenario settle supported articulation --game $game --profile $profile
```

Despite its historical filename, this tool consumes the supplied exported-vehicle manifest. It records `pilot-verification.json` beside that manifest and stops on failure. Its built-in workstation paths are not portable, so pass your game and profile explicitly.

Inspect resting wheel orientation, articulation, mesh loading, joint motion and the recorded outcome. Diagnose failures and generate a new revision before acceptance.

## Full driving acceptance

Use **Verify → Verify package**. It runs settle, supported drivetrain, articulation, acceleration, braking, reverse, left turn and right turn three times.

The recorder checks complete finite telemetry, compiled mass and devices, motion errors and damage. Straight tests also measure uncommanded drift/yaw. Failed repeats withdraw driving qualification; a passed pilot cannot restore it.

## Steering-wheel appearance diagnostic

For a package with a saved steering animation, run
`tools/test-steering-animation.py <manifest> --game <game-directory> --profile <owned-profile>`.
This separate diagnostic sweeps steering while stopped, then at low and moderate
speed. It records close views and compares native prop transforms with the
recorded steering angle and saved CAD visual pivot. It does not add scenarios to
full vehicle acceptance or qualify a real steering-column ratio. Missing poses,
insufficient driving speed, unreadable captures or incorrect rotation fail the
diagnostic; ordinary vehicle checks remain separate in its result.

## Low-speed bouncing

Compare stationary neutral, idle creep, controlled speed and throttle-release coasting. Use `tools/probe-drive-execution.py` with an owned profile and a fresh output directory. Its `--target-speed` is in **metres per second**: 5 mph is 2.2352 m/s. `--scenario steady_speed --deterministic --frequency-window 38 4 --frequency-wheels` records a bounded physics-rate window; `--frequency-corners FL FR RL RR` includes all four suspension corners. `--coast-after 30` releases both pedals while retaining the drivetrain gear, so that recording is not a neutral coast or a controlled speed hold.

`tools/analyze-low-speed.py <run> --output <summary.json>` registers hub motion to the chassis and reports amplitudes, spectra and wheel rotation orders. Ordinary motion snapshots cannot reliably resolve fast vibration. A spectrum or correlation alone does not identify its cause: compare isolated revisions, reject incomplete telemetry, and retain the exact source hashes. Headless fixtures that omit appearance require a separate rendered check before installation. These diagnostics do not replace driving acceptance or qualify the tire material model.

## Read evidence and recover

- Use the receipt's generation, recording and qualification fields rather than interpreting a finished progress bar as a pass.
- Missing or corrupt captures fail evidence checks. A useful image still needs visual review.
- Keep failed diagnostics and the exact manifest when investigating.
- Resume only unchanged inputs and compatible implementation/game identity.
- **Stop task** cancels the owned worker; the harness closes its owned game session.

Passing runs may compact raw CSV and optional reports. Enable **Save full build report** before recording if later raw analysis is needed. Compaction preserves measured results and provenance, but cannot recreate discarded samples.

Continue with [Package and install](/guides/install-package/) once the relevant status and limitations have been reviewed.
