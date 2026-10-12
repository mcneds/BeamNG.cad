---
title: "Development setup and source layout"
description: "Development setup and source layout — beamng.cad documentation."
sidebar:
  order: 1
---

The application is a Windows SolidWorks add-in with external Python workers. The documentation is an independent static website.

## Application layout

| Area | Responsibility |
| --- | --- |
| `beamng.cad/MainSwAddIn.cs` | Native commands and add-in entry point |
| `beamng.cad/UI/` | WinForms workflow, selection, materials, joints and mod management |
| `beamng.cad/Preparation/` | Persistent CAD state, native mates, appearance and companion assembly handling |
| `beamng.cad/FramePipeline/` | Worker orchestration, geometry, templates, packaging and numerical models |
| `dependencies/cad-calibration/` | Integrated Test Harness and Vehicle Wizard sources |
| `tests/`, `tools/` | Regression tests, native fixtures, diagnostics and maintenance helpers |
| `website/` | Maintained handbook, selected public assets and website tooling |

The add-in targets .NET Framework 4.7.2, C# 8 and xCAD 0.8.0. Follow [installation](/start/install/) for build and registration. Refresh registration only when appropriate, and restart the native host after replacing managed assemblies.

## Python environment

Use Python 3.11+ for the harness and numerical workers. From the project root:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e 'dependencies/cad-calibration/Test Harness' -e 'dependencies/cad-calibration/Vehicle Wizard'
& .\.venv\Scripts\python.exe beamng.cad/FramePipeline/calibration_worker.py doctor
```

CGAL bindings and Blender are separate preparation requirements; configure their paths in Settings. Do not assume that installing the numerical harness supplies either.

## Boundaries to preserve

Native references and assembly-space capture belong to the CAD thread. Python workers consume saved snapshots. Ownership must be explicit, and independent moving parts need independent physical owners.

Preserve sealed calibration and package provenance. Changes to physical inputs need fresh generations; appearance revisions must leave the full physical snapshot unchanged.

Use [Testing](/contributors/testing/) to choose checks that match the changed subsystem. Updating website prose alone does not require launching SolidWorks or the game.

