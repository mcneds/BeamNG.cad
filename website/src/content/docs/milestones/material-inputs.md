---
title: "12 October: missing material inputs"
description: "12 October: missing material inputs — beamng.cad documentation."
sidebar:
  order: 5
---

**Historical input audit — a physical elastic reference was unavailable.**

Read-only inspection of the four front wishbones found no captured elastic material properties. Surface bodies used a provisional **3 mm** thickness with steel-density assumptions; some solid bodies retained a **1000 kg/m³** default density.

The archived vehicle mass reference of roughly **175.853 kg** therefore was not a measured vehicle mass.

## Why this matters

A numerical rigid-member fit can make an approximate graph resist deformation. It cannot establish the real arm's elasticity or strength without physical material and wall-thickness inputs.

Likewise, matching a recorded mechanism's geometry preserves joint motion but does not validate its mass or constitutive behaviour.

## Action for a new project

Confirm materials and thicknesses in CAD, refresh the exported properties, and create a new physical generation. Keep the old audit attached to its old inputs; do not relabel it as evidence for a corrected build.

Local source: `docs/evidence/wishbone-material-input-audit-20261012.json`. Follow [Components and materials](/guides/components/) and [Frame calibration](/guides/calibration/) for current procedures.

