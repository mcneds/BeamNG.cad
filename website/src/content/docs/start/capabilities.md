---
title: "Capabilities and limitations"
description: "Capabilities and limitations — beamng.cad documentation."
sidebar:
  order: 2
---

The documentation describes the implementation inspected in this workspace on **12 October 2026**. A dated test result belongs to its captured inputs and implementation; it is not a promise about a new vehicle.

## Available workflows

| Capability | Current boundary |
| --- | --- |
| Native frame preparation | Saved body/component selection, consistent coordinates, hull preview and fixture review |
| Frame calibration | Generation-specific CAD materials and an independent tubular-member reference |
| Component generation | Bulk and panel representations; explicit ownership and material inputs |
| Vehicle generation | Reviewed supported suspension layouts, wheels, steering and CVT drivetrains |
| Native joint authoring | Supported point, axis and compound constraints; unsupported motion is reported |
| Appearance revisions | Retain the complete packaged physical snapshot |
| Native verification | Separate frame, attachment and repeated driving checks |

Front double wishbones and supported rear trailing-arm/wishbone layouts are implemented. MacPherson strut entries describe inventory preparation for future work; they are not a supported complete-vehicle generator. Consult [Templates](/reference/templates/) before choosing a layout.

## What CAD does not supply automatically

A mesh does not establish spring rates, damper curves, tire grip, bearing strength, drivetrain losses, bolt rupture, or real crash behaviour. Surface bodies need explicit thickness and density for physical mass. A material name without captured mechanical properties is insufficient for calibration.

Saved free-space suspension pose is not necessarily loaded ride height. Automatic preload is a provisional support-load calculation. Example coordinates, numerical stiffness targets and synthetic test values are not hardware measurements.

## Current qualification limits

- Actual-vehicle development has recorded alignment, drift and settling failures. It remains diagnostic unless its exact package has passing evidence for the intended scope.
- Angular stiffness fits and rest-state numerical stability checks do not certify large-deformation response or torsion-bar damage behaviour.
- Bulk/panel stiffness, fastener failure and tire construction retain provisional parameters.
- Ideal linkage checks do not predict tire forces or complete driving dynamics.
- The frame's external collision envelope is not an exact contact model of each tube.
- Multi-section shaft chains have offline checks, with native acceptance still a separate requirement.

Use [Verification](/guides/verification/) to interpret the receipts. The [selected milestones](/milestones/overview/) illustrate both successful corrections and unresolved limitations.

