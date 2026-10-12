---
title: "Mounts and breakaway ownership"
description: "Capture attachment sites and distinguish fasteners from suspension joints."
sidebar:
  order: 5
---

Before starting, assign the physical owners and save the assembly. For the complete review and fastener procedure, continue to [Author joints and fasteners](/guides/joints/).

Use the **Component** selector on **Joints & mounts → CAD reference points** to switch groups without
returning to Components. Type a group name to jump to it. The point list is
filtered to that group; the component selection stays synchronized across tabs.
Pick a vertex, circular edge, reference point or **3D sketch point**, then
**Add from CAD selection**. Two points in the same CAD component (or two assembly
datums) define a midpoint. Assembly datum points belong to the group selected in
the tool; their offsets use assembly axes. Part points use the part's axes.

**Panel / accessory fasteners** creates **Non-breaking attachment** (the saved
`fixed` value) or **Breakable attachment** beams. One
mount locates a point; several separated mounts hold a part's orientation. The
generic mounting build rejects unconstrained internal motion. Ball joints and
hinges come from reviewed native motion and the selected suspension template's
hardpoint bindings. Fastener failure is configured separately from joint motion.
A template ball joint uses a shared centre node between the two structures;
their rotation remains free. A normal beam resists changes in endpoint distance
and does not supply a torsional moment by itself. See the
[BeamNG JBeam introduction](https://documentation.beamng.com/modding/vehicle/intro_jbeam/).
