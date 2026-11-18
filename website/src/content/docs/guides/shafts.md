---
title: "Driveline graphs and shaft sections"
description: "Connect CAD-owned shaft endpoints, device ports, wheel hubs and explicit supports."
sidebar:
  order: 7
---

## Author a driveline graph

Open **Routes** in the **Driveline** workspace to follow torque from the engine through each output
to its destination. **New empty graph** starts a layout. **Convert current
layout** opens a draft with the existing ratios, CAD references, and shaft travel.

1. Assign the physical groups in **Components**. In **Devices**, add the engine,
   clutch, CVT, reductions, differentials or splitters, and driven wheel hubs.
   The controller supports one engine and one CVT. Use **Device settings** to
   set ratios and select the primary splitter output.
2. In **Routes**, choose **Connect ports** and select an available output and
   input. For example, connect a differential output to the left rear wheel.
   Choose **Direct torque connection** for a route with no physical shaft, or
   select its CAD shaft group to generate an ideal shaft.
3. For an ideal shaft, **Free** allows unrestricted axial travel. Choose
   **Bounded** and enter **Half travel in each direction (m)** for a measured
   plunge limit. The shaft follows the housing and wheel carrier. Suspension
   geometry determines the wheel path.
4. Use **Repair datum** on a route that needs a reference. In **Endpoints**,
   capture a centre and a point on its positive axis, or bind a reviewed joint.
   Logical ports can route torque without coordinates. Physical attachments
   and reaction axes need datums. A new wheel port can use its suspension hub.
5. For independently moving sections, a floating joint or a separate carrier,
   open **Detailed shaft** and author the sections and connections below.
   Existing detailed graphs retain their physical behavior.
6. **Apply driveline changes** saves the draft. **Check graph** checks the
   references and connectivity. Complete the mounting definition before frame
   calibration, generate a fresh package, and run the native motion checks.

| Connection | Meaning |
| --- | --- |
| `spherical` | Coincident joint centres with positional articulation, including floating joints between shaft sections. |
| `bearing` | A shaft endpoint supported by a separately mounted carrier body. |
| `slider` | Separate shaft bodies/members, a common axis and explicit half travel. |
| `internal` | Torque-only connection between device ports in the same housing. |
| `direct` | Explicit torque-only connection between device ports in different housings, without creating shaft geometry. |

Halfshafts use the same system. Their outer connection targets a **wheel** device
port on the corresponding suspension hub. Suspension defines hub motion;
the driveline defines torque routing and shaft articulation. Unpowered hubs
need no torque terminal.

The torque graph is a directed tree. Branching requires a differential or
splitter, and each input has one upstream connection. Physical supports remain
a separate graph. The **Topology** tab is a connectivity schematic, not CAD geometry.

### Saved and reviewed inputs

Adopting a graph writes project version 4 and preserves the exact previous
project in a versioned backup. Earlier projects and definitions remain readable.
A reviewed `vehicle_template` version 2 definition may contain a `driveline`
section containing `devices`, `endpoints`, `shafts` and `connections`. Graph
version 2 adds `representation: "ideal"` and optional `half_travel_m` to a shaft.
Its ends can reference device port endpoints directly. A shaft without a
representation field retains the detailed model used by graph version 1.
**Import reviewed graph** accepts that section or a standalone graph. Explicit
reviewed positions and axes remain supported; native CAD bindings add live
reference repair checks. Imported coordinates are not silently updated.

A new companion assembly retains the graph but requires repair of copied native
references. Later source-graph changes are reported for review; updating a
companion preserves its locally authored graph and endpoint bindings.

Devices reference housing component IDs; ports reference endpoint IDs. Shafts
reference their component/moving member and endpoint pair. Connections reference
endpoint pairs and declared behavior. Renaming items does not alter connectivity.
Private CAD references stay in the project; packaging records resolved graph
identities, coordinates, axes and settings.

Use separate component groups when sections need independently replaceable
appearance assignments. A combined custom appearance cannot replace several
moving members inside one group; their classified physical CAD meshes are retained.

### Physical model and acceptance boundary

An ideal shaft assigns half its CAD mass to each end and binds the shaft mesh
there. Coincident housing and carrier nodes can receive that mass directly.
The wheel end contributes to the moving suspension mass. A bounded beam engages
at the declared travel limits. This approximation preserves shaft mass and
omits intermediate shaft bodies and slider guides.

Detailed shaft sections use rigid structures fitted to CAD mass, centre and inertia.
Floating sections share positional joint centres. Sliding members use three
parallel numerical rails to preserve orientation and allow declared axial
travel. Their guide triangle is centred on the shaft axis to avoid an artificial
off-axis gravity torque from numerical support mass. Rail sites redistribute
existing mass; they are not inferred material
or bearings. Each mesh follows its own section/member.

Production conditioning may add numerical support mass at joints and rails.
Reports distinguish this from CAD material mass; it changes the simulated mass
and must be included when reviewing suspension loads and inertia.

Torque transmission uses ideal native devices. CV/universal connections provide
positional articulation here. Spin animation, Cardan phasing and calibrated
torsional fracture are outside this model. Graph traversal determines driven
wheels, housing reaction axes and conservative numerical coupling budgets.
These budgets are not measured shaft stiffness or damping.

Ideal spherical joints also have no rotational loss model. A bent floating
linkage released sideways can keep swinging under gravity even while its
section lengths, supports and rigid shapes remain within tolerance. Do not add
an inferred bearing or silently relax settling limits to suppress that motion.

Generation and offline regression success do not establish native acceptance.
Settle, supported-drive and articulation recordings check device connectivity,
ratios, housing reactions, shaft shape/length, support drift and plunge limits.
Rendered review and real-hardware qualification remain separate.

In a matched synthetic vehicle with the same CAD mass, hardpoints, and corner
spring and damper settings, the legacy halfshafts and graph ideal shafts passed
the numerical settle, supported-drive, and articulation checks. The detailed
sliding halfshafts exceeded the settling limit. The extra guide nodes and their
numerical support mass are part of that comparison. These headless tests cover
mechanical behavior on the fixture. See the [test procedure](/contributors/testing/).

## Earlier supported shaft chains

The earlier generator supports an ordered `shaft_chains` declaration in a
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
