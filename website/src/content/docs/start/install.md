---
title: "Install and register the add-in"
description: "Install and register the add-in — beamng.cad documentation."
sidebar:
  order: 3
---

The add-in runs inside **64-bit SolidWorks on Windows**. Building the documentation website does not require SolidWorks; see [Website maintenance](/contributors/documentation/) for that separate setup.

## Prerequisites

| Tool | Purpose |
| --- | --- |
| SolidWorks | Native body selection, persistent references, materials and mates |
| .NET SDK with solution-format support and .NET Framework 4.7.2 targeting support | Build the C# 8 add-in |
| Python 3.10+ | Basic generation workers |
| Python 3.11+ with NumPy, SciPy and Matplotlib | Calibration and analysis |
| Blender and a CGAL-capable Python environment | Native hull/mesh preparation |
| BeamNG.drive | Native simulation verification and installed vehicle review |

The project targets `net472` and references Xarial.XCad.SolidWorks 0.8.0. Keep the supplied `dependencies/cad-calibration` source tree with the checkout. No BeamNG.tech or BeamNGpy installation is required for the native verification path.

## Prepare Python dependencies

For a checkout-based installation, create an environment from the project root:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e 'dependencies/cad-calibration/Test Harness' -e 'dependencies/cad-calibration/Vehicle Wizard'
& .\.venv\Scripts\python.exe -m pip install cgal
& .\.venv\Scripts\python.exe -c "from CGAL import CGAL_Alpha_wrap_3"
& .\.venv\Scripts\python.exe beamng.cad/FramePipeline/calibration_worker.py doctor
```

The local package manifests supply their numerical and wizard dependencies.
The bundled hull worker specifically needs the CGAL alpha-wrap binding; a generic
Python installation is insufficient. If the binding is unavailable for your
interpreter, configure a separate compatible **CGAL Python** environment.
Select the actual environment executable in Settings, and install/configure
Blender separately. These commands prepare dependencies; they do not test native
CAD export or game behaviour.

## Build

From the project root, run:

```powershell
dotnet build beamng.cad.slnx -c Debug -p:XCadRegDll=false
```

This compiles without machine-wide registration. Keep all dependencies and the copied `FramePipeline` directory beside `beamng.cad.dll`.

## First registration

A first installation needs the machine-wide SolidWorks add-in entry. From an administrator terminal, build without the registration override:

```powershell
dotnet build beamng.cad.slnx -c Debug
```

The add-in GUID is `CC0A1EB8-E2C8-435C-BFFE-A3A0DCBC4A60`. The build's xCAD registration creates the native entry.

For an existing installation, point this user's COM registration at the current build:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Register-CurrentUser.ps1
```

Use 64-bit Windows PowerShell. The script requires the machine-wide entry to exist and backs up prior per-user registration keys. For a different output directory, pass `-OutputDirectory 'C:\path\to\net472'`.

## Load and confirm

Save CAD work and restart SolidWorks after replacing the DLL. Toggling the add-in cannot reliably unload its managed assembly. Enable **beamng.cad** in the SolidWorks add-ins dialog, then open a saved top-level assembly.

Look for **Project**, **Components**, **Joints**, **Frame**, **Build**, **Verify**, **Delivery** and **Settings** on the beamng.cad CommandManager tab. These native SolidWorks commands select tasks in the docked beamng.cad Task Pane; they are not child windows of Define Frame. Focused review and file-selection dialogs still open separately. The previous Frame/Mod shortcuts route into the same panel.

The panel starts without selecting a project or running generation. Choose **New from CAD?** for a separate project with unassigned groups, or resume/open existing work. Set up [tool paths and output folders](/start/settings/) before preparing geometry.

If activation fails, check the effective DLL path, adjacent dependencies and [troubleshooting](/reference/troubleshooting/).
