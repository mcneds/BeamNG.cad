---
title: "Package, customize and install"
description: "Package, customize and install — beamng.cad documentation."
sidebar:
  order: 13
---

A package is a reproducible artifact with an identity and receipt. Installing it is separate from building or verifying it.

## Select the right operation

| Action | Use when |
| --- | --- |
| Package calibrated mod | The frame has passed offline calibration checks |
| Regenerate physics / package | CAD properties, joints, physical parameters or template have changed |
| Package saved appearances | Only saved visual assignments/alignment need to change |
| Apply to selected build | Update selector metadata/image while retaining physical content |

A mounting-plan change needs fresh frame preparation/calibration before the full vehicle build. Appearance packaging must preserve the complete physical snapshot.

## Customize the selector entry

Open **Manage Mod** for a frame or **Manage project mod** for a vehicle. Review the name, brand, author, configuration and description.

Use **Capture SolidWorks viewport**, choose an existing image, or **Use hull image**. Arrange the CAD view first. Managed selector images are normalized to 1024×576 without distortion.

**Save for future builds** stores defaults. **Apply to selected build** creates a package revision with the parent receipt retained.

## Install

1. Confirm the active user's mods folder in Settings.
2. Select the intended build receipt and review its hash/status and limitations.
3. Choose **Install selected build**.
4. Reopen the BeamNG selector or restart/reload if an old package is already loaded.

The installer verifies package integrity and provenance before replacing the project's ZIP. Prior ZIPs are backed up outside the mods folder. Identical installs normally do nothing unless explicit reinstall/overwrite is selected. Conflicting unpacked or repository copies require resolution.

Changing a display name keeps the project namespace; importing/forking physics creates a distinct identity. The manager shows the actual package path.

## Expected result

The selected and installed ZIP hashes agree. This confirms the files on disk, not which vehicle is currently spawned in BeamNG. Installation neither launches acceptance nor promotes a failed diagnostic package to qualified status.

Keep the receipt and referenced build assets for rollback. Select a previous receipt to return to an older reviewed package.

