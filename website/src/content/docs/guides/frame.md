---
title: "Prepare and generate a frame"
description: "Select frame bodies, inspect the hull, review fixtures, calibrate and package a generation."
sidebar:
  order: 1
---

## Prepare, review and generate

1. Open and save the top-level assembly in the intended configuration.
2. On the **beamng.cad** CommandManager tab, open **Settings**. Check Python,
   Blender, CGAL Python, **Calibration Python** (3.11+, NumPy, SciPy, Matplotlib),
   material/settings source, build output, BeamNG installation
   and the active user profile's mods folder. Edits persist without a successful build.
3. Select frame component instances, subassemblies, or bodies in the viewport/tree.
   Open **Define Frame**, choose **Use current selection**, and confirm the resolved
   body list. A face pick selects its owning body. **Assign whole components**
   explicitly expands a pick to its owning component. Expand selection sets into
   their members before assigning them.
4. Open **Hull settings** to adjust grid resolution, surface offset, weld distance,
   proxy alpha divisor/offset ratio, and X symmetry (including source-half flip
   and seam merge distance). **Reset hull defaults** restores starting values.
   Coordinates convert automatically from SolidWorks `(x, y, z)` to BeamNG
   `(x, -z, y)`: CAD +Y is up, CAD +Z is front; BeamNG +Z is up and -Y is front.
   The assembly origin and metres are preserved. Older editable assignments
   migrate with a backup and need fresh preparation; archived generations retain
   their original convention. X symmetry is opt-in.
5. Choose **Prepare / preview frame**. Selected bodies are freshly exported into
   an external build directory. Blender and CGAL run in the background. Review
   the temporary orange wire hull in SolidWorks. **Show hull overlay** hides/shows
   it without discarding the prepared geometry. Choose **Accept hull / review fixtures**.
6. In the fixture viewport, check the up/front arrows and select support and load
   nodes. Right-drag to orbit; click nodes to toggle membership in the selected
   fixture role. Review load fractions, then **Approve orientation and fixtures**.
   Suggestions from a previous graph are spatial suggestions, never inherited approval.
7. **Calibrate CAD frame** derives targets from this generation's CAD bodies and
   their assigned SolidWorks materials. It generates the **solidworks-assigned**
   case. Use **Package calibrated mod** after the offline criteria pass.
   **Verify in BeamNG** separately launches the isolated harness, measures the
   result and reports qualification. Archived annealed/normalized studies remain readable.
   **Open generation...** resumes a saved generation; changed inputs require a new one.
8. Open **Manage Mod** to set the vehicle name, brand, author, configuration,
   description and selector image. **Capture SolidWorks viewport** uses the active
   document's current view: arrange the angle, zoom and visible components first.
   The manager hides during capture and shows the resulting thumbnail for review.
   You can also choose an image or **Use hull image** to make a thumbnail from the
   build's actual hull. **Save for future builds** persists
   these settings; **Apply to selected build** creates a new package revision
   without regenerating geometry. Then **Install selected build** installs it.
   **Choose build** switches to a previous receipt; folder buttons open its output
   or the configured mods folder. Enable **Reinstall / overwrite** to replace even
   an identical installed ZIP, with a backup. Installation does not launch BeamNG.

Calibration and verification compare each generation with its own CAD-derived
mass, inertia, stiffness and yield targets. The archived 34.789158 kg / 78-node /
435-beam Mochi result is only an unchanged-input regression fixture. New geometry
can legitimately have different mass and topology. See [calibration integration](/guides/calibration/).

## Review installation and package identity

The manager compares the selected package hash with the installed ZIP and shows
its actual selector name and whether it includes a preview. This is an on-disk
check, not confirmation of the vehicle currently spawned in BeamNG. Reopen the
vehicle selector after installing; reload the mod or restart BeamNG if necessary.
Each project has a stable package namespace. Changing its display name does not
change that identity or produce a second installed copy; the manager shows the
actual ZIP path. Importing/forking a physics template creates a new identity.
Legacy standalone packages may still be named `ak1di_mochi.zip`. Replaced ZIPs
are backed up outside the mods folder. Other projects are left alone.
Use the active BeamNG **user folder's** `mods` directory, not the Steam game
installation's `mods` directory. A common active directory is
`%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\mods`; the startup log confirms it.
An older ZIP in the Steam installation folder can therefore differ from the
three packages shown in the game's Mod Manager.

The mod profile is `%LOCALAPPDATA%\beamng.cad\mod-profile.json`, with managed JPEG
images beside it in `mod-images`. Images are normalized to 1024x576 without
distortion and included as `default.jpg` and `base.jpg`. Package revisions retain
their parent receipt; original builds and geometry remain unchanged.

## Resume and refresh saved work

**Generate Frame Mod** opens the same workflow with the saved frame assignment.
**Show Frame Selection** restores its original selection scope. The modeless frame
window leaves the assembly tree and viewport available. Closing it removes the
preview; generated geometry is never added to the assembly.
The **Selected geometry** and **Preparation log** tabs keep the assignment and
worker output accessible. Settings edits invalidate the old preview and disable
acceptance until **Prepare / preview frame** succeeds again.

Assignments and hull options are stored beside the assembly in
`<assembly-file>.truemesh-prep.json`, by configuration and role. Keep this companion
file with the assembly. Regenerate after CAD edits; missing or suppressed references
produce diagnostics and require an explicit replacement selection.

Settings live at `%LOCALAPPDATA%\beamng.cad\settings.xml`. If absent, the add-in
loads legacy `%LOCALAPPDATA%\TrueMeshExporter\settings.xml` and preserves that
original when saving the new settings. Existing build receipts remain supported.
Known local installations supply missing defaults; check them for your workstation.

Choose **Build directory** in the frame window (or Settings) to place new CAD
exports, generations, packages and worker scratch files on another drive. Existing
generations remain at their original locations. Verification writes beside the
generation being tested; regenerate on the new drive to move that work too.
