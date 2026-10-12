---
title: "Troubleshooting"
description: "Troubleshooting — beamng.cad documentation."
sidebar:
  order: 4
---

Start with the current operation's **Log** and receipt. Keep the exact project, manifest and failed diagnostics when asking for help.

| Symptom | Check and recovery |
| --- | --- |
| Add-in commands missing | Check registration/DLL path, adjacent dependencies, enabled add-in and active assembly; restart SolidWorks after DLL changes |
| Python command fails immediately | Select the real interpreter and run the calibration worker's `doctor` action |
| Saved geometry cannot resolve | Open the saved configuration, resolve suppressed/lightweight geometry, and explicitly repair invalid references |
| Tree item highlights but assignment is empty | Select actual body geometry; a tree highlight can differ from the native selection list |
| Component has no bodies | Reference-only planes/sketches cannot be assigned as a physical mesh |
| Duplicate ownership | Separate independently moving owners and remove overlapping assignments |
| Missing material or surface mass | Assign real material data and sheet thickness, or explicitly choose appropriate visual-only treatment |
| Hull acceptance is disabled | Selection, parameters or source changed; prepare a fresh preview |
| Stale frame or mount-plan hash | Prepare/calibrate again with the reviewed current mounting plan |
| Native mate cannot be imported | Check supported motion, ownership and requested hardpoints; a solved CAD mate is not automatically a supported physical joint |
| Appearance remains old | Saving an assignment does not package it; use **Package saved appearances** |
| `VY node not found` | Inspect mesh/node binding and noncollinear basis; refresh with the appropriate rigid-prop/flexbody representation |
| Blank/missing capture | Retain diagnostics; a successful image save does not establish usable evidence |
| Installed ZIP looks correct but vehicle is old | Check active user mods folder, unpacked conflicts and currently spawned vehicle; reload/restart |
| Calibration completes but status is limited | Inspect independent qualification fields and rendered-review requirements |
| Vehicle drifts or alignment changes | Compare native motion to the same CAD linkage before altering physical inputs |

## A sensible recovery order

1. Confirm you are using the intended assembly configuration and project.
2. Check inputs and ownership before tuning numerical settings.
3. Refresh/export changed CAD.
4. Regenerate any affected frame or vehicle artifacts.
5. Repeat the failed pilot with the same defined scope.
6. Run complete acceptance before claiming qualification.

Never reuse old geometry just because an STL exists. Do not use example hardpoints or an alignment change to conceal a mismatch to captured CAD.

## What to include in a report

Record the operation, exact error, relevant source/build paths, tool versions, selected configuration and receipt status. Include the smallest relevant log or screenshot. Reference the failed manifest and retain its hashes; an unrelated later build cannot reproduce the same result.

