---
title: "Supported templates"
description: "Supported templates — beamng.cad documentation."
sidebar:
  order: 1
---

The source of truth for role inventory is `beamng.cad/FramePipeline/template_catalog.json`. Physical generation also validates the reviewed definition; a catalog entry alone does not mean a complete vehicle can be generated.

| Template | Required review |
| --- | --- |
| Front double wishbone | Upper/lower arm pivots, upright ball centres, steering links, shock eyes and wheel axes |
| Rear trailing arm | Actual chassis hinge and wheel support geometry |
| Rear double wishbone | Both arms, upright, locating links, shock and wheel axes |
| Trailing arm + radius rods + toe link | Two chassis ball centres, separate ball carrier and all three rods |
| Ball-pivot trailing arm + radius rods + hinged upright + toe link | One chassis ball, arm/upright hinge and explicit rod topology |
| MacPherson strut | Inventory schema for future work; not supported full-vehicle generation |
| CVT rear drive | Engine/clutch/CVT, rear reduction/differential and actual ratios |
| CVT rear drive with geared front output | Additional front output gearing, propshaft and front differential |

## Role ownership

Each physical body belongs to one owner. Independently moving arms, racks, coilover members, carriers and wheels must not be treated as one rigid object. Repeated panels and shaft sections are allowed; unique required roles cannot be duplicated.

Changing setup preserves saved selections and marks irrelevant tags **OUTSIDE CURRENT SETUP**. Resolve those entries, missing roles and duplicate ownership before packaging.

## Hardpoints

Hardpoints are coordinates or directed axes captured from CAD or supplied in an explicitly reviewed definition. A `hub_axis` record is a second point, not a free direction vector. FL/FR and RL/RR refer to vehicle left/right as seated facing forward.

Example skeletons illustrate requests; they never assign real hardpoints. Frame mount plans must be recalibrated when the physical topology changes.

See [Suspension setup](/guides/suspension/) and [Joint authoring](/guides/joints/) for the procedures.

