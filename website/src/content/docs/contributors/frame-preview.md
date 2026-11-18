---
title: "Test the frame preview"
description: "Verify GPU approximation, software fallback and prepared-hull display without touching live CAD."
sidebar:
  order: 3
---

Build without COM registration, then run the standalone preview fixtures from
the project root:

```powershell
dotnet build beamng.cad.slnx -c Debug -p:XCadRegDll=false -p:OutputPath=bin/proxy-preview-verified/
powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-FramePreview.ps1 -Software
powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-FramePreview.ps1 -Gpu
```

The first checks the CPU fallback, actual OFF display, cancellation, stale results
and window disposal, with WPF software rendering forced. The GPU check requires
OpenGL 4.3 and fails rather than silently substituting CPU results. It exercises
compute, indirect rendering, visible framebuffer pixels, parameter updates,
invalidation and window disposal. Pixel and draw-count readback are test-only.
Interactive updates read the bounded proxy volume for background CPU topology
work, then upload projected edges for GPU drawing. Both modes test analytic cube
projection, expected grid topology, offset, weld collapse and cancellation. GPU
checks verify symmetry on/off restoration and recovery from invalid even-width
symmetry without a backend change.
Framebuffer checks also verify that the pruning-volume toggle adds/removes
visible pixels, candidate evaluation leaves the current volume untouched, and
candidate presentation regenerates boundary faces from its retained volume.
Live parameter updates preserve the toggle; prepared OFF views disable it.

Both modes also host the preview inside the same docked layout used by the frame
editor. They edit real hull controls and check input focus, renderer handle
identity, narrow/wide layout, divider resizing, tab navigation, removal and
reattachment of the cached editor, and disposal during an update. The viewport
remains parented to its frame editor throughout; parameter edits never open or
activate a separate window. Settings scroll independently of the viewport.

`tools/Test-FrameDocumentContext.ps1 -OutputDirectory '<build directory>'` uses
managed COM-interface doubles to check a disconnected document, replacement by
the same saved assembly, configuration rejection, invalidation, and the ban on
rebinding during capture. It does not launch SolidWorks or establish native-host
recovery. Restart SolidWorks after updating the registered add-in: toggling it
does not reliably unload its managed assembly.
The document-context fixture also opens Hull suggestions before capturing any
CAD in a narrow frame editor. It checks that preview capture is directly
available and Show current settings reveals the actual Hull settings tab while
preserving its values.

Pass `-FrameStl '<saved prepared frame.stl>'` for a read-only benchmark using an
existing binary STL. Its timings separate initial upload/voxelization from
resident-snapshot edits; the repeated update measurement includes proxy compute,
readback, grid pruning, projection, symmetry, welding and edge upload. It excludes
CAD capture, snapshot/tree construction, debounce and presentation. The CPU fallback comparison uses a different
approximation and is not a CGAL benchmark. Measure the authoritative hull worker
separately in a fresh output directory, preserving source files, parameters and
the dated result. Never substitute preview timings for calibrated generation or
qualification timings.

These standalone checks do not establish live SolidWorks capture, loaded-add-in
parity, high-DPI behavior or vehicle qualification. An unavailable GPU backend
must be reported as unavailable. The forced-software check establishes a
fallback path, not hardware rendering performance.

## Algorithm and ownership

The live approximation conservatively voxelizes captured display triangles,
performs separable box closing and proxy-offset dilation, and compacts boundary
faces for the optional pruning-volume display. The requested grid is pruned and
flood-filled on a background CPU worker. A cached triangle bounding-volume tree
finds nearest CAD surface points. Surface offset precedes polygon bisect/mirror,
seam snapping, representative-based spatial welding and fan triangulation.
Projected edges are uploaded and rendered directly alongside the source CAD.

The renderer uses a private OpenGL context and restores the host context after
each operation. Updates are serialized, stale revisions are hidden, and graphics
continuations run on the preview's UI thread. Snapshot conversion and topology
work run in the background; SolidWorks COM capture stays on its owning thread.
Invalid settings do not select the CPU fallback. A later valid edit restarts from
the unchanged source snapshot and proxy seeds.

The [frame guide](/guides/frame/#live-approximation-and-its-limits) describes
resolution, parameter caps and fidelity limits. The proxy is heuristic; projected
positions, triangulation and weld topology can differ from Blender/CGAL. Prepared
OFF output is displayed separately in a batched WPF mesh. Neither display path
creates SolidWorks wire bodies or supplies a physical graph.

## Sparse-hull search

Build into an isolated directory, then run:

```powershell
dotnet build beamng.cad.slnx -c Debug -p:XCadRegDll=false -p:OutputPath=bin/hull-search/
powershell -NoProfile -STA -File tools/Test-HullSearch.ps1
powershell -NoProfile -STA -File tools/Test-HullSearch.ps1 -Gpu
python -m unittest discover -s tests -p test_preview_search_worker.py
```

Pass `-FrameStl '<saved frame.stl>'` for read-only checks using real display
geometry, and `-Gpu -Check` to also run the owned Blender/CGAL candidate worker.
The full check uses a fresh temporary settings/output fixture and reads tool
locations from current settings; it does not change saved user preferences.
It prints its isolated output directory. These checks do not launch SolidWorks
or establish loaded-add-in behavior.

The fixtures cover a windowed frame, an oversized box, inward collapse, an open
seam, disconnected shells, duplicate faces, a self-intersecting folded shell and
a watertight torus with a through-hole. They verify silhouette ranking, count
limits, repeatability, proxy alias deduplication, unchanged settings and viewport
during search, candidate labels, Apply cloning, locked settings and invalidation.
They also cover a checked mesh that misses Finer's fit limit, the visible warning
and Apply anyway action, and reassessing that same mesh under Balanced without
losing its checked status, selection or current hull settings. Manual settings
application is tested for both fit and structural optimizer warnings, preserving
their rejected status and diagnostics rather than bypassing generation checks.
The Python worker tests partial failure, completed-result retention on cancel,
missing output and snapshot fingerprint changes. Full checks compare approximate
and actual mesh eligibility using the same indexed surface scorer.

Candidate scoring requires canonical indexed triangles. Preview boundary winding
is consistent before projection; triangulation retains the mesh used for topology
checks. A closed connected orientable shell must have Euler characteristic 2,
cycle-shaped vertex links, nonzero volume and no illegal triangle intersections.
Silhouettes use conservative pixel coverage on both sides of the comparison,
preventing subpixel tubes from leaving artificial gaps in the CAD reference.
The reference fills only enclosed image regions, rather than replacing the frame
by its convex hull. See the [frame guide](/guides/frame/#find-a-sparse-outer-hull)
for quality thresholds and the distinction between a snapshot check and fresh
preparation.
