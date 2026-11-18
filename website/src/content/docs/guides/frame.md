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
   Open **Frame** > **Selected geometry**, choose **Use current selection**, and confirm the resolved
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
5. Choose **Live proxy preview** for tuning feedback inside the Frame workspace. It
   captures the saved frame's display triangles, then reuses that snapshot while
   you change **Hull settings**. This needs no material assignments or vehicle
   mate scan. Use **Refresh CAD** after changing the selection or assembly.
   Orange edges estimate the projected hull after grid pruning, nearest-CAD
   projection, surface offset, X bisect/mirror and welding. The grey layer shows
   captured CAD. **Pruning volume** optionally shows the coarse proxy used before
   projection. The preview sits above the settings in
   a narrow Task Pane and beside them when widened. Drag the divider to allocate
   space; changing settings keeps the viewport open and updates it in place.
   **Preview details** expands the renderer status, controls and fidelity limits.
6. Choose **Prepare actual hull** for the authoritative hull. Selected bodies
   and their assigned materials are freshly exported into an external build
   directory; Blender and CGAL run in the background. The docked preview switches
   to actual prepared hull edges, without creating SolidWorks wire bodies.
   **View prepared hull** displays that result again. The **Next step** panel above
   the preview identifies the first required CAD group that needs attention and
   opens its editor. Link the saved frame in **Components**, assign the other
   physical groups, then review the actual joints and hardpoints or load reviewed
   mounting JSON. Preparing the hull can be done before these inputs are ready.
   Choose **Accept hull / review fixtures** to run the mounting checks and create
   a generation. If a check fails, follow the panel to the relevant editor, then
   return to Frame. The prepared hull can be reused while its CAD inputs are current.
   Fixed-graph refitting also checks the existing mounting contract.
7. In the fixture viewport, check the up/front arrows and select support and load
   nodes. Right-drag to orbit; click nodes to toggle membership in the selected
   fixture role. Review load fractions, then **Approve orientation and fixtures**.
   Suggestions from a previous graph are spatial suggestions, never inherited approval.
8. In **Build / calibration**, **Calibrate CAD frame** derives targets from this generation's CAD bodies and
   their assigned SolidWorks materials. It generates the **solidworks-assigned**
   case. Use **Package calibrated mod** after the offline criteria pass.
   **Verify in BeamNG** separately launches the isolated harness, measures the
   result and reports qualification. Archived annealed/normalized studies remain readable.
   **Open generation...** resumes a saved generation; changed inputs require a new one.
9. Open **Manage Mod** to set the vehicle name, brand, author, configuration,
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

## Live approximation and its limits

The preview follows the same stage order as preparation, using a cheaper
pruning volume in place of CGAL alpha wrapping:

1. Voxelize captured triangles and approximate alpha gap closing and proxy offset
   on the GPU. This snapshot stays cached while settings change.
2. Read the bounded volume into a background CPU worker, lay out the requested
   X/Y/Z grid, retain intersecting and enclosed cells, and extract its boundary.
3. Project boundary vertices to nearest points on the captured CAD triangles,
   using a cached spatial tree. Apply surface offset here, independently of
   proxy offset.
4. Bisect projected polygons at the selection's X centre, mirror the chosen half
   when symmetry is enabled, merge the seam, then weld nearby vertices.
5. Triangulate surviving polygons and render their edges with the CAD on the GPU.

Grid density, surface offset, weld distance, symmetry, source-half flip and seam
merge now affect the displayed hull estimate. **Pruning volume** shows the
intermediate volume separately. **Preview details** exposes complete settings,
counts, limits and timing; timings include the CPU topology work and GPU readback,
and exclude capture, initial snapshot setup, debounce and presentation.
The volume belongs to the displayed GPU approximation, including a selected
search candidate. Its checkbox is disabled as **Pruning volume (not retained)**
for checked/prepared OFF results and the software view, which do not retain this
intermediate data. It does not substitute an approximate volume for CGAL's wrap.

The proxy still uses 64 cells per axis. Closing and proxy-offset radii are rounded
up to whole cells and capped at 6 cells each. Closing uses half the alpha scale as
a heuristic. Thin members, gaps and cavities can differ from CGAL's wrap; changes
smaller than a proxy voxel may not change pruning. Nearest projection uses display
tessellation. Mirror clipping, seam snapping, representative-based welding and
fan triangulation approximate Blender's modifier/topology choices, so vertex and
edge counts can differ even with identical settings. **Prepare actual hull**
remains the authoritative check. Preview edges are not final braced beam counts,
and the preview supplies no mass, stiffness or hardpoints.

Rendering happens on demand. Drag or use arrow keys to orbit, wheel or plus/minus
to zoom, and **Home** or **Fit view** to reset the camera.

Updates wait briefly after an edit, cancel superseded work and remove stale
overlays immediately. **Stop update** stops pending approximation work.
The initial display capture still needs SolidWorks COM on its UI thread, and a
single native call cannot be interrupted. The capture yields between faces and
has a 200,000-triangle budget. If display tessellation is unavailable or exceeds
that budget, reduce CAD display tessellation or use full preparation.

When GPU compute is unavailable, the labelled CPU fallback uses conservative
triangle boxes for the approximate proxy and performs the same later grid,
projection, offset, symmetry and weld steps. It can take longer; WPF displays its
edges with software rendering when necessary. Invalid parameter combinations,
such as symmetry with an even width, show a validation message without switching
the graphics backend or discarding the captured CAD. Correct the setting to
resume updates.

The authoritative hull, fixture review, calibrated generation and their saved
contracts remain separate. A successful preview is not generation success or
physical qualification.

## Find a sparse outer hull

After capturing a live preview, choose **Find sparse hull**. The **Hull suggestions**
tab also provides **Start / refresh preview** if you opened it before capturing
CAD. The preview toolbar says **Start preview** until a snapshot is captured,
then **Refresh CAD**. You can start capture from either place without returning
to settings. **Show current settings** opens the Hull settings tab even when
the narrow pane has scrolled its tab header out of view.

The **Hull suggestions**
tab offers **Coarser**, **Balanced** (default) and **Finer**. The search looks for
one closed outer shell with no through-holes, spanning openings such as windows
while preserving the main outline with few vertices. It scores silhouettes from
26 directions against a fixed CAD reference with enclosed image openings filled.
It rejects open seams, disconnected shells, pinched vertices, duplicate or
collapsed faces, inconsistent winding and self-intersections.

The search varies X/Y/Z grid dimensions, alpha divisor and weld distance. Surface
offset, proxy offset ratio, symmetry, source half and seam distance stay as set.
It reuses captured geometry and cached spatial/proxy data, trying at most 150
candidates or approximately 20 seconds after snapshot setup. Automatic grid
exploration uses 2–12 points per axis, plus the current settings as a baseline;
X stays odd under symmetry. Search results are estimates, not a global optimum.

Select a suggestion to view **Candidate—not applied**. **Show current settings**
opens Hull settings and returns to the live view. Searches and candidate previews do not change saved
hull settings or accept a prepared result. The shortlist contains up to three
different fit/vertex-count tradeoffs. If nothing meets the selected quality,
the closest attempts are shown with their rejection reason; change quality or
starting settings and retry. Fit is a silhouette score, not structural accuracy.

Choose **Check selected** to run the full Blender/CGAL algorithm on the frozen
display snapshot at half, current and double proxy offset ratio. This refinement
uses actual OFF results because whole-voxel preview rounding can make distinct
ratios look identical. Checked results are labelled **CGAL checked snapshot** and
scored with the same shell and silhouette criteria. Checks can disagree with
approximate ranking. Completed ratio checks survive a failed ratio or Stop.
Successful checking means the computation completed; it does not guarantee the
selected quality target was met. The status beside **Apply** shows the fit and
worst-view overlap against their exact limits. A checked result can therefore
remain outside tolerance. Changing Coarser/Balanced/Finer reassesses existing
suggestions and checked meshes immediately, retaining selection and requiring
no Blender/CGAL rerun. Run **Find sparse hull** again to explore different candidates.

**Apply** copies the selected candidate's settings into Hull settings and
invalidates the previous prepared result. Run **Prepare actual hull** afterward
to freshly export CAD and materials through the normal preparation contract.
Candidate checks create isolated files in the build directory; they do not
generate a physical graph, calibrate, package or install a vehicle. CAD,
configuration, selection or hull-setting changes invalidate suggestions.
Optimizer criteria are recommendations, not a restriction on your choice.
For a candidate outside the fit target or with a shell warning, the button reads
**Apply anyway** and remains available. Applying copies its settings; it does not
mark the mesh accepted or remove its diagnostics. Normal preparation and
generation validation still run. Apply is unavailable while a search/check is
running or when no candidate is selected.

Balanced requires weighted silhouette error at most 0.08 and per-view overlap
at least 0.80; Coarser uses 0.15/0.70 and Finer 0.04/0.90. Error combines 75% of
the mean view error with 25% of the worst. Among acceptable candidates, fewer
vertices win, followed by lower error and fewer edges. The raster reference has
finite resolution and cannot establish that every desired CAD detail is retained.

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

**Frame** opens the frame editor in the docked Task Pane. The older **Define Frame** shortcut routes here; **Generate Frame Mod** opens **Build**.
**Show Frame Selection** restores its original selection scope. The docked editor leaves the assembly tree and viewport available. Generated geometry is never added to the assembly; previews are removed when the editor is disposed.
The preview stays visible while the **Selected geometry**, **SolidWorks materials**,
**Build / calibration** and **Preparation log** tabs provide access to the other
frame tasks. Settings edits refresh the live approximation and disable acceptance
of the previous prepared hull until **Prepare actual hull** succeeds again.
Closing and reopening the same saved assembly replaces its native document
object. While idle, Frame restores the saved assignment for the original
configuration and clears cached results; choose **Refresh CAD** for new display
geometry. A document change during capture stops that capture. Activate the
source assembly and its original configuration before retrying.

Assignments and hull options are stored beside the assembly in
`<assembly-file>.truemesh-prep.json`, by configuration and role. Keep this companion
file with the assembly. Regenerate after CAD edits; missing or suppressed references
produce diagnostics and require an explicit replacement selection.

Settings live at `%LOCALAPPDATA%\beamng.cad\settings.xml`. If absent, the add-in
loads legacy `%LOCALAPPDATA%\TrueMeshExporter\settings.xml` and preserves that
original when saving the new settings. Existing build receipts remain supported.
Known local installations supply missing defaults; check them for your workstation.

Choose **Build directory** under **Selected geometry** (or Settings) to place new CAD
exports, generations, packages and worker scratch files on another drive. Existing
generations remain at their original locations. Verification writes beside the
generation being tested; regenerate on the new drive to move that work too.
