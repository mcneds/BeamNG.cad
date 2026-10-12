---
title: "10 October: correcting a release test"
description: "10 October: correcting a release test — beamng.cad documentation."
sidebar:
  order: 3
---

**Historical correction — the test coordinate system changed; the vehicle physics did not.**

A detached panel reached the recorder's 100 m displacement guard during a zero-gravity force-release test. Absolute travel alone could not distinguish free flight from internal instability.

Two diagnostic recordings retained the force ramp, 500 m/s speed guard and full duration while tracking the component's centre after every incident mount broke. Both completed. In the primary fixture, internal axial spring energy fell from about 4.8 kJ to 1.05 J, and maximum internal beam extension fell from 209 mm to 3.45 mm.

![Panel speed, internal energy and extension during detached free flight](/assets/panel-free-flight-20261010.png)

## The corrected guard

Before release, displacement remains relative to the initial position. After all mounts release, the guard subtracts mass-weighted translation; rotation and deformation still contribute. Absolute travel is also retained, and nonfinite/speed guards remain active.

The analyzer requires the new guard identity. Earlier incomplete evidence cannot silently qualify under a changed test definition.

## What remained limited

This supported free flight with decaying internal motion for the observed fixtures. It did not calibrate real panel bending, plasticity, tearing or fastener strengths.

The primary completed all 12 attachment recordings but encountered a cleanup sharing violation; its interrupted batch status remained visible. The alternate completed its 12-recording batch. Passing measurements and a completed batch receipt were kept distinct.

Local sources: `docs/mvp-followup-20261010.md` and `docs/evidence/panel-free-flight-20261010.json`.

