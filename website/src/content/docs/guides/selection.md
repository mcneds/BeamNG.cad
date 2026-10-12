---
title: "Find and assign CAD geometry"
description: "Understand physical ownership, saved selections, appearance status and unresolved references."
sidebar:
  order: 2
---

To locate a group you already assigned, open **Components / mounts → Components**,
select its row, and click **Show in SolidWorks** above the list. Double-clicking
the row performs the same action. **Zoom to group** frames the highlighted
selection; uncheck it to keep your current view.

The source defaults to **Appearance CAD** when the group has a saved appearance
assignment. This is the selection from **Save visual assignment** (formerly
**Replace appearance from selection**).
Saving a physical assignment selects **Physical CAD**; saving a visual assignment
selects **Appearance CAD**. Refreshing or saving parameters keeps that choice.
A group with physical CAD saved from this assembly and no visual assignment opens
on **Physical CAD**, even when the project began from a synthetic template.
Choose **Physical CAD** to inspect the geometry used for mass and physical
ownership instead. Imported template physics can still refer to the synthetic
assembly; the control reports that mismatch rather than selecting unrelated
geometry in your current assembly. A missing appearance assignment is shown
explicitly and does not silently substitute the physical one.

Highlighting resolves the saved persistent references and selects those bodies
or component instances using SolidWorks' native highlight. It does not export,
reassign, recalibrate or package anything. Clicking a row alone leaves your
current CAD selection intact, so you can still pick replacement geometry first.
Using **Show in SolidWorks** deliberately replaces that selection. Missing or
suppressed references produce an error without leaving a partial highlight;
use the saved configuration and resolve the affected geometry before retrying.

Geometry assignment requires solid or surface bodies. Reference-only layout
parts containing planes, axes or sketches cannot be assigned as meshes. If the
error names a component with no bodies, deselect that component or check its
configuration, then assign again. The prior saved group remains intact when
capture fails; geometry is never silently omitted from the requested group.

For a part or hardpoint you have not assigned yet, use the
[reference skeleton viewer](/guides/reference-skeleton/) to see the template's
labelled example.

For a driveshaft with multiple axes, first read [shaft sections and carrier supports](/guides/shafts/).

## Read assignment status

Each row has separate **CAD** and **Appearance** statuses. A separate appearance
assignment is optional: generation renders the physical CAD by default. These
labels describe saved assignments, not whether the last packaged ZIP is current.
Hover over a row to read its full status when the list is narrow.

| Status | Meaning |
|---|---|
| unassigned | No saved selection for that source |
| saved | Selection is saved for this assembly; this does not certify physics or guarantee that later CAD edits leave every reference resolvable |
| uses CAD | No separate appearance override; generation uses this group's physical CAD mesh |
| source CAD | Default appearance comes from CAD assigned in another assembly |
| custom (pending) | A separate appearance is saved and needs packaging |
| custom (update failed) | The appearance selection is retained, but its package update failed |
| coilover N/3 | Number of assigned moving pieces; all three are required to package split visuals |
| other assembly | References belong to another assembly, such as the imported synthetic fixture |
| unverified / unavailable | Source provenance is missing or its cached metadata cannot be read; inspect or reassign it |

**Save visual assignment** records the references and configuration immediately,
without requiring a build receipt, mesh export or material fit. You can inspect
and zoom to it immediately. **Package saved appearances** exports all pending
visual groups and applies them together to the selected physical package. A
package failure keeps the saved selections and the previous package selected;
the visible error and Log explain the failure. Alignment changes are also saved
first and applied by this package action. Physical CAD assignment similarly saves
first; **Refresh tagged CAD** performs the separate geometry/material export.

## Find groups and save frame ownership

Use **Find component (name or role)** above the group list to narrow it, for
example `body`, `panel`, `RL radius`, or a custom group name. Displayed role names
are included: `body` finds **Body panel** groups even with custom names such as
“Nose cone.” **Ctrl+F** focuses search;
**Esc** in that box clears it. Filtering does not remove or modify groups.
**New tagged group** uses a name you typed before clicking it, clears the filter,
and selects its new saved row. If you have not edited the Name field, it generates
a name from the role; an existing name gets a numeric suffix. An unwanted
empty row can be removed with **Remove component**.

For the frame, select its row or choose the **Frame** role. The component definer
shows whether a definition exists for the active SolidWorks configuration and
disables the ordinary assignment buttons. **Define / edit frame → Use current
selection** saves the frame definition; **Use saved frame** links it into the
vehicle project. The definition and hull settings live beside the assembly in
`<assembly>.truemesh-prep.json`; the linked group is stored in the selected
`.beamng-project.json`. Both reload after restarting SolidWorks, without a build
or export. Keep those files with the assembly. Definitions are configuration
specific; the UI lists other saved configurations when the active one has none.
Prepared previews and calibration results remain separate build artifacts.

## Resolve geometry and reopen projects

The geometry picker accepts solids and surfaces through bodies, faces, edges,
vertices, body folders and geometry features. Edges and vertices identify their
owning body. A feature identifies only its own body geometry; it does not expand
to an unrelated whole component. Selection feedback shows the incoming item count
and unique body count, since several faces can refer to the same body.
Lightweight components are loaded on demand. A visible tree highlight alone can
be absent from SolidWorks' actual selection list; selecting that body's geometry
directly avoids the discrepancy. No unavailable item is silently skipped.

**Open saved project** returns to an earlier project for the active assembly.
**Start fresh from CAD** never overwrites the old project. Keep the old project
and its referenced export/build directories if you still need its packages.
