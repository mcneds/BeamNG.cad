---
title: "Shaft sections and carriers"
description: "Prepare supported shaft chains with explicit joints, ownership and axial travel."
sidebar:
  order: 7
---

The generator supports an ordered `shaft_chains` declaration in a
`vehicle_template` version 1 definition. Each section has its own CAD owner,
endpoint pair, axis, mass contribution and mesh binding. Existing single-section
`shafts` definitions continue to work unchanged. The new chain implementation
has offline regression coverage; it has not yet passed native BeamNG acceptance.

## Prepare a two-section shaft

For a two-section front propshaft:

1. In the separate real-physics project, assign **two** groups with the
   **Front driveshaft section** role. Select only the bodies belonging to each
   section. Give them distinguishable names. Selection/list order does not define
   their physical order.
2. Assign the stationary bearing housing/bracket to **Propshaft carrier bearing /
   bracket**. It is a separate mass-owning group with reviewed frame mounts.
3. In the reviewed definition, list three ordered joint centres and two sections.
   Each joint names its mounted housing/carrier by **component ID**, not display
   name. `segments[i]` joins `joints[i]` to `joints[i+1]`. Every joint needs an
   explicit support; an unsupported intermediate joint is currently rejected.
4. Set each section's `plunge_m` explicitly: zero gives a fixed-length compliant
   rod; a positive value allows that much axial travel in **each** direction.
   No slip joint or extra gear reduction is inferred from the mesh.
5. Include carrier `fixed_mounts` before preparing/calibrating the frame, then
   regenerate the full vehicle and run settle/supported/articulation pilots.
   Adding or moving a carrier mount requires fresh frame calibration.

[`examples/shaft-chain-fragment.json`](/assets/shaft-chain-fragment.json) shows
two non-collinear synthetic sections. Merge it into a reviewed definition with
actual component IDs and measured coordinates; it is not a complete vehicle
definition and its example points must not be applied to real CAD. Remove the
replaced legacy `shafts` entry. All section owners must appear exactly once.

## How the support is represented

At the intermediate support, both sections contribute half their CAD mass to a
shared positional node. Three support beams and an angular point constraint
locate it on the separately mounted carrier. Each section binds only to its own
endpoints and their local supports. Native motion recording includes these nodes,
checks support drift, and checks length against each section's declared plunge.
The chain and its mass allocations are sealed into package provenance and remain
unchanged during appearance replacement or namespace forks.

## Limits of the model

This is an equivalent supported positional linkage, not a rotating universal-joint
simulation. It retains the existing ideal `frontPropshaft` powertrain device
(or the existing CVT-to-rear reduction for an output-shaft chain). Shaft spin
animation, Cardan phasing/angular-speed variation, shaft bending/spin inertia and
torsional fracture are not modeled. Endpoint mass lumping preserves each
section's total mass, but does not fit its full CAD inertia. The supported joint
centre is an explicit constraint, not an inferred carrier-bearing location.
BeamNG's [bounded-beam documentation](https://documentation.beamng.com/modding/vehicle/sections/beams/bounded/)
describes the axial limits; its [props documentation](https://documentation.beamng.com/modding/vehicle/sections/props/)
describes the separate local-axis animation system.
