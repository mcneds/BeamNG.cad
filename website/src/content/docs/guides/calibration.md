---
title: "Calibrate a CAD frame"
description: "Calibrate a CAD frame — beamng.cad documentation."
sidebar:
  order: 10
---

Calibration fits a generated graph to **that generation's** independent CAD-derived frame reference. Start with a saved frame assignment, supported solid members, captured materials and reviewed mounting plan.

## Capture material inputs

1. Inspect **SolidWorks materials** for every selected body. Body assignments take precedence over inherited part materials.
2. Correct missing density, elastic/shear moduli, Poisson ratio and required strength properties through the native material editor.
3. Use **Set material for current selection** or **Set material for saved frame** only when you intend to change CAD. In the picker, choose a material, **Apply**, then **Close**.
4. Save changed CAD normally. Assignment operates on shared part/configuration definitions, so other instances of that definition share the change.
5. Refresh and prepare again after changes. Export reads material data; it does not silently assign a fallback material.

Cancellation reports confirmed and remaining bodies. An in-flight native SolidWorks call cannot be interrupted safely.

## Review the generation

Prepare the frame, inspect its orange hull, and choose **Accept hull / review fixtures**. Review the orientation arrows, fixed nodes, load nodes and load fractions, then **Approve orientation and fixtures**.

The current workflow uses SolidWorks-to-BeamNG mapping `(x, y, z) → (x, -z, y)`. Prior fixture suggestions are spatial hints, not inherited approval. Include suspension pivots, carriers and release mounts before calibration.

## Fit and package

Choose **Calibrate CAD frame**. New native exports use the **solidworks-assigned** case, preserving per-body materials. Inspect geometry/reference audit failures and fit residuals rather than substituting archived Mochi targets.

Use **Package calibrated mod** after offline checks pass. The generation retains its source snapshot, review, study and test folders. Packaging checks the unchanged graph and provenance and excludes test fixture pins.

A change to geometry, materials, fixtures, mounting topology or sealed implementation requires a fresh generation. **Open generation...** resumes an unchanged saved study.

## Verify separately

Run **Verify in BeamNG** against an isolated harness profile. [Quick and Full](/guides/verification/) test different scopes. Numerical calibration, completed recordings and rendered physical qualification remain separate statuses.

If a frame cannot match its reference within its numerical resolution, report that mismatch. Increasing a numerical frequency target does not supply missing material data or establish real stiffness.

Read [Frame generation and calibration](/concepts/calibration/) for the fitting model and [Files and receipts](/reference/files/) for the saved artifacts.

