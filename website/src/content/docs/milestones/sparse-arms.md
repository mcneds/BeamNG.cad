---
title: "11 October: sparse suspension arms"
description: "11 October: sparse suspension arms — beamng.cad documentation."
sidebar:
  order: 4
---

**Historical trial — simpler arms remained dynamically unqualified.**

Replacing dense arm moment-node representations with mechanical hardpoints reduced explicit vehicle nodes from **929 to 893**. An upper wishbone used three mechanical nodes and reused its existing chassis hinge edge.

The trial retained total CAD arm mass but approximated COM/inertia; reports explicitly separated those errors and numerical support mass. The archived CAD mass reference itself included provisional material assumptions.

Supported drivetrain and articulation passed. Reverse toe errors remained about 2.23°/2.36°, acceleration drifted, braking failed lateral deviation and in-drive settling showed zero-throttle creep. All six recordings had zero broken beams.

## Separate appearance correction

The old flexbody mapping could report `VY node not found` and hide sparse arm meshes. Rigid native props bound to three existing noncollinear nodes restored visible arms without adding physics nodes or constraints.

![Sparse-arm meshes visible during a rendered articulation recording](/assets/sparse-arms-rendered-20261011.png)

A fresh rendered articulation check preserved the physical snapshot and removed the flexbody errors. That corrected rendering; it did not qualify driving.

## Lesson for iteration

Track node count, mass/moment errors, physical identity and live motion separately. Neither a smaller graph nor a successful appearance repair proves the full mechanism accurate.

Local source: `docs/evidence/sparse-arms-native-20261011.json`. See [current mechanism representation](/concepts/mechanisms/) for maintained defaults.

