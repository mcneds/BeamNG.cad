---
title: "Suspension, wheels and drivetrain setup"
description: "Suspension, wheels and drivetrain setup — beamng.cad documentation."
sidebar:
  order: 11
---

Start with a tagged inventory and [reviewed joints](/guides/joints/). Choose a template that matches actual hardware; a similar-looking mesh is insufficient.

## Choose the topology

On **Vehicle setup / MVP**, select the front suspension, rear suspension and drivetrain, then **Apply vehicle setup**. Complete newly required groups and resolve **OUTSIDE CURRENT SETUP** tags.

Two rear layouts with radius rods have different freedoms:

- **Trailing arm + 2 radius rods + toe link:** two chassis ball centres define the arm hinge; a ball joint connects the arm and carrier.
- **Ball-pivot trailing arm + 2 radius rods + hinged upright + toe link:** one chassis ball supports the arm; the upright is hinged to the arm.

Do not substitute one for the other. Review native geometry and the requested hardpoints using the [reference skeleton](/guides/reference-skeleton/).

## Enter actual physical inputs

1. Capture pivot centres, wheel bearing axes, rack motion and spring/damper eyes.
2. Set wheel radius, width, pressure and mass model from reviewed inputs.
3. Review spring rates, damper settings and travel limits for each corner.
4. Set CVT ratio range, reductions, front output ratio/direction and reverse arrangement to match the drivetrain.
5. For multi-section shafts, declare supported joints and explicit plunge; see [Shafts and carriers](/guides/shafts/).
6. Include these mounts in a fresh frame calibration, then regenerate physics.

## Ride pose and preload

An assembly saved in free space may not show the loaded ride position. Automatic preload uses a common left/right hub height per axle by default. It solves the existing linkage there; it does not move hardpoints or change tie-rod lengths.

`front_ride_hub_height_m` and `rear_ride_hub_height_m` specify this reference in vehicle coordinates. Without them, mean captured axle height is provisional. Set `level_axle_ride_height=false` only when the individual saved poses are intentionally loaded ride positions.

Optional `front_alignment_toe_in_deg` and `rear_alignment_toe_in_deg` change link rest lengths. Positive values mean toe-in. They are explicit physical setup changes; omit them to retain captured lengths.

## Engine profile

`engine_profile: "baja_na_ch440_2026"` selects the project's sourced restricted CH440 curve. It does not determine CVT calibration, drivetrain losses, inertia or clutch hardware. Read generation warnings about missing inputs and engagement/idle conflicts. The source evidence is retained locally in `docs/evidence/baja-na-ch440-2026.json`.

## Expected result

The new manifest should identify the selected mechanism, actual inputs and remaining approximations. Run settle, supported drivetrain and articulation pilots before the full acceptance suite. A linkage solve, successful package or synthetic reference image is not proof of real-vehicle qualification.

