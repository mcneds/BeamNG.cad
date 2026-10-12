---
title: "Configure tools and folders"
description: "Configure tools and folders — beamng.cad documentation."
sidebar:
  order: 4
---

Open **beamng.cad → Settings** before your first generation. Automatically discovered paths are conveniences; verify them on your machine.

| Setting | What to select |
| --- | --- |
| Python | An actual Python executable, not an unconfigured Store alias |
| Calibration Python | Python 3.11+ with the numerical dependencies |
| Blender | The Blender executable used for external preparation |
| CGAL Python | An interpreter with the required CGAL bindings |
| Material/settings source | The source files required by the selected generation workflow |
| Build directory | A writable location with room for geometry, reports and recordings |
| BeamNG installation | The directory containing `BeamNG.drive.exe` |
| Mods directory | The active BeamNG **user profile's** existing mods directory |
| Harness profile | A separate profile for owned verification sessions |

Use the BeamNG launcher's **Manage User Folder / Open in Explorer** action to find the active profile. Do not select a mods directory inside the game installation.

## Example local paths

These are examples to replace, not folders supplied with the project:

```powershell
$calibrationPython = 'C:\BeamNGCad\venv\Scripts\python.exe'
$game = 'D:\SteamLibrary\steamapps\common\BeamNG.drive'
$profile = 'C:\BeamNGCad\harness'
$manifest = 'C:\BeamNGCad\builds\vehicle\manifest.json'
```

Check the calibration interpreter from the project root:

```powershell
& $calibrationPython beamng.cad/FramePipeline/calibration_worker.py doctor
```

Resolve missing dependencies before preparing a frame. This check does not register the add-in or qualify a vehicle.

## Saved settings and project state

Settings live at `%LOCALAPPDATA%\beamng.cad\settings.xml`, with a backup of the preceding save. Legacy TrueMeshExporter settings are read if the new file is absent. Selected projects are tracked separately per assembly.

Keep the assembly's `.truemesh-prep.json` and `.beamng-project.json` companions with its CAD files. Build receipts and exported geometry live in the selected build directory; moving only the project JSON can leave its referenced files unavailable.

**Save full build report** is off by default. Passing runs keep compact measurements and necessary evidence; failed runs retain diagnostics. Enable it before recording when raw telemetry is needed later.

Frame verification defaults to **Quick** in the UI. Full vehicle **Verify package** is a different operation with its own repeated driving suite.

