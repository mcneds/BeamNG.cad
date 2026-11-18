---
title: "Your first CAD vehicle"
description: "Tag, review, calibrate, package and verify an assembly without confusing appearance with physics."
sidebar:
  order: 5
---

This guided path assumes the [add-in is installed](/start/install/) and [settings are configured](/start/settings/). Your first checkpoint is a reviewed CAD inventory; a complete drivable vehicle needs the subsequent joint, frame and verification steps.

**Start by tagging your real CAD groups and exporting their inventory.** The first
checkpoint is a complete, non-overlapping set of physical owners and a review of
your suspension hardpoints. Swapping your meshes onto the synthetic vehicle is
useful for appearance, but continues to test the synthetic vehicle's physics.

1. Save the assembly in its intended configuration. In **Settings**, choose a
   **Build directory** on a drive with sufficient free space and leave **Save full build report** unchecked unless
   a full recording is needed. Check material assignments in SolidWorks. Keep
   the assembly's preparation and project JSON files beside it.
2. In **Frame**, use the current frame selection and check its body list.
   Save that assignment; wait to prepare/calibrate the final frame until its
   mounting plan has been reviewed in step 5.
3. In **Project**, choose **New from CAD...**, select the authoring method and
   save a separate project filename. Native CAD authoring is recommended;
   reviewed mounting JSON remains supported. Open **Vehicle layout and project tools...**. For the current vehicle,
   choose **front double wishbone**, **rear trailing arm**, and **CVT / rear final
   drive with geared front output**. The separate project keeps an existing appearance trial intact. The new
   project lists the required groups with empty assignments and a distinct mod
   identity; no mesh, physical package or hardpoint coordinates are imported.
   **Apply vehicle setup** adds any required rows after changing the layout. Use the
   checklist for this configuration. It requests the frame, engine/CVT/housings,
   front driveshaft, front arms/uprights/tie rods, rear trailing arms, steering
   rack, four halfshafts, four spring/damper groups, four wheel groups and panels.
   Optional brake/accessory/separate CVT-output-shaft groups may be absent when
   there is no separate CAD group for them.
4. Under **Components → CAD assignment**, select an unassigned group row, pick
   its CAD bodies or instances, and use **Set to selected**. This saves
   into that row; repeating the action replaces its selection. Use **New tagged
   group** only to add another group, such as a repeated panel or shaft section.
   The group dialog asks for its role and name, then adds and selects a saved empty row. Assign CAD next. Repeated panel/shaft roles carry over; unique roles such as
   frame start as an unassigned new component to avoid accidental duplicates.
   **Assign whole components** explicitly expands to their
   owning instances. For the frame, use **Use saved frame**. Each body has one
   physical owner; independently moving arms, wheels and panels need separate
   groups. Name repeated panels individually. For surfaces, use **Physical
   properties** to enter thickness and material, or exclude their mass and
   choose a physical parent. A weightless skin has no independent breakaway.
5. In **Build**, choose **Refresh tagged CAD** and correct missing roles,
   duplicate ownership, unresolved references and material errors. **Stop here
   for the first review.** The **Log** gives the project and inventory paths
   (`<assembly>.beamng-project.json` and its `.inventory.json` companion). Keep
   their referenced export directories available. Review actual pivot centres,
   wheel axes and dimensions, spring/damper endpoints, mounts, travel and the
   CVT/differential ratio and reverse arrangement against that inventory.
   The tested example's coordinates and ratios are not defaults for your car.
6. In **Joints**, choose **Authored CAD joints**, review native mates
   and bind every requested hardpoint to your CAD. Follow the
   [joint and fastener workflow](/guides/joints/), including
   the moving rack and physical parameters. **Check definition** reports missing
   or incompatible inputs. An existing reviewed JSON definition can still use
   **Reviewed template definition** and **Load template hardpoints**. The **Next step**
   panel leads from incomplete body assignments to joints and hardpoints. You can
   preview the frame while doing this work. Once inputs are ready, prepare the hull
   and choose **Accept hull / review fixtures** to check the mounting plan.
   Approve the fixtures, **Calibrate CAD frame**, then **Package calibrated mod**.
   Changing the mounting plan later requires fresh calibration.
7. Return to **Build → Regenerate physics / package**. This builds the
   full vehicle from your CAD properties and reviewed template. Check its receipt
   and `manifest.json`. Without a complete authored or imported definition, the component builder is
   not a complete drivable-vehicle generator.
8. First run **settle, supported drivetrain and articulation** against that new
   manifest. Inspect resting wheel orientation, suspension motion and captures
   before driving. The current UI's **Verify package** runs the full 24-test
   suite; the shorter first pilot uses the command below. After the pilot passes,
   run **Verify package**, then use **Manage project mod** to install the reviewed
   package. A failed pilot needs diagnosis and a new revision before acceptance.

From the project root, set the paths for your installation and the new build:

```powershell
$calibrationPython = 'C:\BeamNGCad\venv\Scripts\python.exe'
$game = 'D:\SteamLibrary\steamapps\common\BeamNG.drive'
$profile = 'C:\BeamNGCad\harness'
$manifest = 'C:\BeamNGCad\builds\vehicle\manifest.json'
& $calibrationPython tools/test-synthetic-vehicle.py $manifest --scenario settle supported articulation --game $game --profile $profile
```

Despite its historical filename, this pilot tool consumes the exported-vehicle
manifest, not a fixed synthetic frame. Always pass your own game and isolated profile paths as shown.
It stops on failure and records `pilot-verification.json` beside the manifest.
Successful reports are compacted by default; failures retain diagnostic evidence.
