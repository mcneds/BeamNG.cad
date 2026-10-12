---
title: "What is beamng.cad?"
description: "What is beamng.cad? — beamng.cad documentation."
sidebar:
  order: 1
---

beamng.cad is a SolidWorks COM add-in that turns selected CAD groups into BeamNG structures and vehicle packages. It combines a C# interface inside SolidWorks with Python geometry, calibration and vehicle-generation workers.

It keeps three things separate:

| Layer | What it owns |
| --- | --- |
| CAD project | Body selections, material observations, saved references and authored joints |
| Physical model | Nodes, beams, constraints, masses, collision and powertrain |
| Appearance | Render meshes, colours and their bindings to the physical model |

That separation lets you change a vehicle's skin without silently changing its physics. A new physical design, however, needs new inputs, generation and verification.

## Choose your starting point

- **A frame:** follow [Frame preparation](/guides/frame/) to capture geometry, inspect a hull, review fixtures and calibrate a generation.
- **A complete CAD vehicle:** follow [Your first CAD vehicle](/start/first-vehicle/), beginning with ownership and a reviewed inventory.
- **A different appearance on existing physics:** read [Appearance and templates](/guides/appearance/). This tests the retained physics, even when every visible mesh changes.
- **Development:** start with [Architecture and source layout](/contributors/development/).

## Before you start

Read [Capabilities and limitations](/start/capabilities/), install the [prerequisites](/start/install/), and configure [Settings](/start/settings/).

Generation, successful recording, and physical qualification are separate outcomes. A ZIP that loads in BeamNG is an important checkpoint, but it does not establish real material, handling or crash accuracy.

