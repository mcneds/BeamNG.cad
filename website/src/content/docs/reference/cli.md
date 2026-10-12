---
title: "Command-line tools"
description: "Command-line tools — beamng.cad documentation."
sidebar:
  order: 3
---

Run these commands from the **project root**, using the configured calibration interpreter. Paths below are examples to replace. CLI tools operate on explicit saved artifacts; they do not refresh your current SolidWorks selection unless the specific tool says so.

## Calibration worker

```powershell
$calibrationPython = 'C:\BeamNGCad\venv\Scripts\python.exe'
$generation = 'C:\BeamNGCad\builds\generation'
$game = 'D:\SteamLibrary\steamapps\common\BeamNG.drive'
$profile = 'C:\BeamNGCad\harness'

& $calibrationPython beamng.cad/FramePipeline/calibration_worker.py doctor
& $calibrationPython beamng.cad/FramePipeline/calibration_worker.py calibrate --job $generation
& $calibrationPython beamng.cad/FramePipeline/calibration_worker.py verify --job $generation --game $game --profile $profile --verification quick
```

Actions include `doctor`, `prepare`, `calibrate`, `package`, `verify` and `fixed-preview`. Read `--help` before composing non-UI jobs. Verification defaults to Full; `--resume` requires unchanged compatible inputs and `--save-report` keeps full successful-run diagnostics.

## Offline inventory

```powershell
& $calibrationPython beamng.cad/FramePipeline/component_worker.py inventory --project 'C:\CAD\vehicle.beamng-project.json' --output 'C:\BeamNGCad\inventory.json'
```

This regenerates inventory from saved exports. Use **Refresh tagged CAD** inside SolidWorks after changing CAD.

## Vehicle pilot

```powershell
& $calibrationPython tools/test-synthetic-vehicle.py 'C:\BeamNGCad\builds\vehicle\manifest.json' --scenario settle supported articulation --game $game --profile $profile
```

The historical filename does not restrict it to synthetic vehicles. See [Verification](/guides/verification/) for pilot scope.

## Focused diagnostics

| Tool | Purpose |
| --- | --- |
| `tools/verify-dual-rate-spring.py` | Isolated two-stage spring response |
| `tools/verify-coilover-visuals.py` | Split shock rendering and motion |
| `tools/publish-reference-skeleton.py` | Build local illustration assets from verified source meshes |
| `tools/probe-drive-execution.py` | Controlled alternate execution-mode experiments |
| `tools/prune-diagnostics.py` | Audited retention of local development recordings |

These are specialist tools, not prerequisites for normal CAD use. Some retain workstation-specific defaults and require existing jobs, profiles or policies; inspect their help and source first. Benchmark outputs never create driving acceptance or installation receipts.

Multi-car experiments remain disabled by default after memory-growth and equivalence issues. Use normal independent recordings for acceptance.

