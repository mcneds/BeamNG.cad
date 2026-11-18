---
title: "Appearance and physics templates"
description: "Replace visible CAD while retaining packaged physics, or explicitly regenerate physical properties."
sidebar:
  order: 9
---

**Project → Vehicle layout and project tools...** determines which CAD groups are
required. The first configuration has front double wishbones, rear two-point
trailing arms, and a CVT driving the rear final drive with a geared front output.
The second has front and rear wishbones with CVT rear drive. Their inventories
differ: changing suspension configuration changes the required arms, upright and
locating-link roles. Tags outside the active configuration remain visible for repair.

1. Choose the configuration and **Start fresh from CAD**, or **Apply vehicle
   setup** in an existing fresh project. Select a required row, select CAD, and
   **Set to selected** or **Assign whole components**. Use **New tagged
   group** for an additional repeated group.
   The frame uses **Use saved frame**. Solid bodies, surface bodies, faces and body
   folders are supported; unrelated features do not silently select whole components.
2. For surfaces, choose thickness plus a SolidWorks material, or exclude their
   mass and choose a physical visual parent. Weightless skins have no independent
   collision structure or detachable mounting behavior.
3. Complete **Joints & mounts** with actual CAD points/reviewed joints, or keep
   **Reviewed template definition** and **Load template hardpoints** from a reviewed
   file. These are explicit vehicle coordinates, not guesses from mesh bounds.
   Include the resulting mounting plan before fresh frame calibration.
4. **Refresh tagged CAD**, then **Regenerate physics / package**. The worker checks
   the role inventory, mount plan, CAD properties and source hashes. A changed
   frame mounting plan requires fresh calibration.
5. **Verify package** runs the appropriate native scenarios in an owned profile.
   Full vehicle acceptance is eight scenarios repeated three times and stops on
   the first failure. Install through **Manage project mod** after reviewing its status.

The operations below deliberately have different effects:

| Operation | Physical graph | CAD properties | Appearance |
|---|---|---|---|
| Save visual assignment | Preserved | Preserved | Saves CAD references; package unchanged |
| Package saved appearances | Preserved, including runtime Lua and devices | Preserved | Exports pending saved selections and rebinds their existing owners |
| Align appearance | Preserved | Preserved | Saves a display transform for the next appearance package |
| Recalibrate properties from selection | Node positions and connectivity preserved | Refit on those nodes; impossible fits rejected | Separate replacement operation |
| Regenerate physics / package | Rebuilt from current template and CAD | Fresh inputs | Rebuilt bindings |
| Import physics template | Forked under a new project namespace | Baseline retained | Can receive replacement CAD |
| Reset to imported template | Restored from the original imported receipt; current project namespace retained | Baseline component snapshot restored | Baseline appearance restored; later edits discarded |

If you accidentally assigned bodies in **CAD assignment** while attempting an
appearance-only trial, use **Vehicle setup / MVP → Reset to imported template**
in the **Project** section at the top of the page.
It restores the original template's component list, hardpoint definition and
packaged physics, removing added groups, later appearance edits and custom
mounting-point/connection edits from the active project. It leaves CAD documents,
the project identity, mod profile and previous build folders intact.

Reset creates a fresh package before replacing the project. Worker failure or
cancellation leaves the current saved project untouched. A successful reset saves
the exact pre-reset project in `<project-file>.template-reset-backups/`; its path
appears in the status and Log. Edits made by another window during packaging block
the reset commit. Reset then opens **Components → Appearance**, where you select
an imported component and use **Save visual assignment**. Update the mod later
with **Package saved appearances**.

The setup panel shows the imported source and changes the import action to
**Continue with imported template**. Continue only navigates to Appearance;
**Reset to imported template** performs the reset. Importing into a populated
fresh-CAD project remains disabled with an explanation beside the button.

An appearance swap can contain different numbers of CAD bodies. It does not move
hardpoints, change spring lengths, apply a new material, or change wheel collision.
Every revision has a parent receipt, separate physical/appearance hashes, and a
new output directory. Property changes require new verification. Frame property
changes use the independent frame reference workflow; a generic component mass
fit cannot qualify a frame's elastic response.

## Steering-wheel animation

A rigid steering-wheel mesh can follow BeamNG's `steering` electric without adding
nodes or changing its physical mounts, mass, steering linkage or suspension.
The saved `SteeringAppearance` setting records its visual pivot, axis, neutral
orientation and captured-geometry fingerprint. It describes an animation, not a
physical steering column or a measured real-car steering ratio.

The advanced `tools/animate-steering-wheel.py` command takes a completed receipt,
`--component <component-id>` and a fresh `--output <directory>`. It fits the captured
rim plane and circle, rejects ambiguous geometry, and creates an appearance-only
revision with an identical physical snapshot. Review the neutral, left and right
poses in the game before installing. Changed geometry requires a new pivot fit;
ordinary appearance packaging and full generation retain a valid saved setting.

This uses the game's existing steering angle. Matching a real vehicle's exact
lock-to-lock travel requires a separately established steering ratio. See
[BeamNG props](https://documentation.beamng.com/modding/vehicle/sections/props/).

## Import a reviewed baseline

Choose **Import physics template** and select the source package's actual build receipt. Import creates a separate project namespace. Keep the source package directory intact because the receipt checks its package and provenance.

Replace and align appearance by component role, save visual assignments, then **Package saved appearances**. The new mesh does not supply new physical properties until an explicit property refit or regeneration. A template's passed tests describe that recorded configuration, not a newly recalibrated vehicle.

For new physical CAD, follow [Your first CAD vehicle](/start/first-vehicle/) instead. Historical synthetic packages referenced by old development notes are not bundled installation prerequisites.

## Image textures, including carbon fibre

Captured SolidWorks colour images are converted to portable RGB PNG assets,
deduplicated by content and included in the mod. Each textured material references
its image through BeamNG's `baseColorMap`; the DAE supplies per-vertex UVs. Face
colour assignments remain separate, including across frame render-region cuts.
Missing image files stop packaging with their path instead of silently producing
flat paint. Images containing alpha currently require a separate opacity export
and are rejected explicitly.

Existing STL-based CAD captures do not contain SolidWorks texture mapping. The
export therefore uses **100 mm box projection**, with a warning in the worker
log. This restores the source image but does not reproduce its original scale,
direction, seams, decals, procedural finish or bump maps. Explicit vertex UVs,
when present in the geometry record, are preserved. Changing appearance does not
change density, stiffness or any other physical material value.

For an existing packaged vehicle, `tools/refresh-textured-appearances.py` creates
an immutable appearance revision from its receipt and captured CAD. It verifies
that the physical-model hash is unchanged and that every colour map is packaged.
The source texture files must still exist when making the revision; running the
installed mod needs neither SolidWorks nor those source files.

The texture output follows BeamNG's [texture cooker naming](https://documentation.beamng.com/modding/materials/texture_cooker/)
and [PBR material format](https://documentation.beamng.com/modding/materials/vehicle/typicalmaterials/).
