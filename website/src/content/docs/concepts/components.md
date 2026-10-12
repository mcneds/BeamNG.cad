---
title: "Bulk parts and panels"
description: "How collision representations, positive mass fits and provisional component stiffness are generated."
sidebar:
  order: 4
---

The component estimator uses principal axes and extent ratios to suggest panel
or bulk treatment. Starting spacing is the largest principal extent divided by
six, with a 20 mm floor. These are editable starting estimates.

Bulk parts normally use a CGAL alpha wrap. Automatic mode first checks whether a
single closed CAD solid already matches its convex boundary within 0.001% volume.
If that boundary has at most 96 vertices, it is used directly with outward-facing
triangles. Surfaces, multiple bodies and cavities cannot use this shortcut.
Otherwise automatic mode tries progressively coarser alpha/offset values,
targeting at most 96 surface nodes; more than 240 is rejected.
Interior mass samples allow inertia fitting without putting all mass on the
collision boundary. The explicit convex option is available for appropriate shapes.

Panels use a grid in the principal plane and Delaunay triangles. Candidate collider
triangles are clipped against the union of projected CAD triangles, so holes are
not silently filled by a convex outline. Strongly curved panels are rejected by
the planar template. Sparse depth locators give the sheet a volumetric numerical
structure. Their mass is included in the fit, not added to the CAD total. Thin
sheet mass fitting may use a bounded 1% tensor error to avoid nearly massless nodes.
For a uniform panel with captured material properties, neighboring triangles also
receive bending hinges. The plate rigidity is `D = E t³ / (12 (1 − ν²))`; each hinge
uses `D × edge length / centroid separation`. Angular damping uses its effective
nodal inertia. A coupled stiffness/damping screen reports any numerical reduction.
This supplies bending restraint that nearly coplanar axial beams lack. It remains
a provisional plate approximation, with no calibrated plasticity or fracture law.

The generated bulk/panel graph uses tetrahedral adjacency and a rigidity-rank
check. Springs and damping have numerical caps. **These component stiffness and
failure values are provisional; a CAD mass fit is not material calibration.**
