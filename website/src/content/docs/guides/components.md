---
title: "Components and materials"
description: "Choose templates, tag CAD owners, assign sheet thickness and review component generation."
sidebar:
  order: 1
---

Open **Components** on the SolidWorks beamng.cad CommandManager. Assignments live beside the saved
assembly in `<assembly>.beamng-project.json`, including persistent CAD references,
configuration, body IDs, role tags, generation settings and mounting points.
Tagging does not require a completed frame package or a successful hull preview.

Component fields, including spring settings, share one **Apply component changes** / **Discard** boundary. Switching groups, filtering the list, leaving the task or starting an operation offers Apply/Discard/Cancel when edits are pending. Apply covers the edited component fields together; CAD-reference assignment and package generation remain explicit actions.

## Choose the template set first

On **Vehicle setup / MVP**, choose front suspension, rear suspension and drivetrain,
then **Apply vehicle setup**. Required groups and associations come from those
choices in `FramePipeline/template_catalog.json`.

For an endpoint-authored arrangement, use [Driveline graphs](/guides/shafts/).
Once a graph is adopted, its devices and shaft owners replace the drivetrain
preset's role/count requirements. Suspension templates still define the four
hub mechanisms. Partial graphs can be saved but must pass **Check graph** and
generation preflight before use.

Input schemas include front double wishbone or MacPherson strut, rear trailing
arms or double wishbone independent suspension, and CVT rear drive with or without
the rear differential's geared front output. Defaults match the Mochi layout:
front wishbones, rear trailing arms, CVT into rear differential with a geared
output feeding the front differential. Full-vehicle generation currently supports
front wishbones with either trailing-arm or wishbone rears. The strut option is an
inventory schema for future work. Choosing a setup does not qualify the vehicle:
ratios, joints and hardpoints still require actual inputs and native verification.

Changing a setup retains existing selections. Tags no longer requested appear as
**OUTSIDE CURRENT SETUP**. Revise them or change the setup before packaging.

## Tag the CAD groups

For a rigid small component such as a steering-wheel body, select the **rigid**
generation method instead of wrapping its detailed mesh. This uses the declared
mounting points plus six mass points to preserve CAD mass, centre of mass and
inertia. Its appearance follows a rigid prop. These mass points are not a
collision shell; the method does not model local bending, rupture or steering
column animation. Use a panel or collision-bearing bulk representation when
those behaviours are required. Attachment and joint definitions remain separate.

This is an explicit representation choice, not a guess based on the component's
name. A lightweight rigid control does not need a dense node at every feature of
its visible mesh. Numerical support-mass requirements for suspension hardpoints
remain separate from its captured CAD mass.

1. Click **New tagged group**, then choose its role and a useful name in the dialog.
   The role supplies a starting representation. Full-vehicle generation replaces
   suspension-group collision previews with the template's parametric mechanisms;
   bulk and panel groups retain their corresponding generated representations.
2. Select CAD bodies or faces and click **Set to selected**. A face means
   its entire owning body. Solid and surface bodies are supported. For a whole
   component or subassembly, use **Assign whole components**; selecting its edge
   or feature is sufficient for that explicit action. **Set to selected** replaces
   the group's saved geometry. To keep its existing bodies and include more,
   select the additional CAD and click **Add to group**. Additions must use the
   same assembly and configuration; bodies owned by another group are rejected.
3. Repeat for the checklist groups. Each body belongs to one assignment. Group
   meshes of one rigid part together; separate parts that need independent motion
   or breakaway. Multiple panels/accessories are allowed. Use **Use saved frame**
   for the calibrated frame.
4. To tag an existing list entry, change **MVP role** and **Apply component changes**.
   **Show CAD selection** recalls its bodies.
5. Click **Refresh tagged CAD** after assigning groups or changing CAD. This
   resolves saved selections, exports current geometry/materials, refreshes mounts
   and writes `<assembly>.beamng-project.json.inventory.json`.

The inventory contains template choices, missing/duplicate roles, ownership,
persistent references, mesh hashes, mass-input issues and planned associations.
It is the reusable handoff for iteration. Broken groups are reported without
reusing old exports. Tags do not assert that a hinge, shaft or connection has
been built or tested. Load a reviewed template definition for mechanism hardpoints,
include its mounting plan in fresh frame calibration, then regenerate the vehicle.

From the project root, set `$calibrationPython` to your configured interpreter and regenerate inventory offline from the last CAD exports:

```powershell
& $calibrationPython beamng.cad/FramePipeline/component_worker.py inventory --project '<assembly>.beamng-project.json' --output inventory.json
```

This command does not refresh SolidWorks. Use the UI refresh after CAD edits.
Missing groups are valid partial preparation, not vehicle qualification.
Geometry files stay in the configured build directory.

## Surface weight

For an assigned component, choose:

- **Use thickness + SolidWorks material**: enter **Surface thickness mm**. Mass
  uses native surface area, entered thickness and SolidWorks material density.
  Mass, center and inertia are fitted to positive node masses. Thickness
  contributes to inertia without modifying or thickening the CAD body.
- **Exclude surface mass**: surfaces add zero mass; solid bodies retain their
  native mass. A group with no positive mass cannot be a physical component.
  Select **Visual only**, choose its physical parent (and moving member when
  applicable), then choose **Exclude mass** and **Accept visual only with excluded mass**.
  It follows its parent's nodes with no independent collision or breakaway.
  Put mounts on the physical parent, or supply thickness for separate physics.

Thickness and density must be positive for weighted sheets. They may remain unset
while tagging; preview reports missing inputs. Export does not assign materials.
Component assignment permits sheets; frame calibration still requires solids.

Representation and mass policy are separate. A **Visual only** group can also carry
CAD or custom positive mass: that mass, COM and inertia are fitted into its physical
parent's nodes once. An infeasible fit is rejected. Excluded mass stays explicitly
labelled, and changed geometry/mass settings require renewed acknowledgement.

## Generation and mounting

**Estimate from CAD** suggests panel spacing or bulk alpha-wrap settings.
**Generate / preview** fits mass and displays that component's representation.
The panel template preserves projected openings and adds numerical depth locators.
Strongly curved panels require bulk representation for now. Hull visibility uses
retained temporary graphics; closing the window disposes them.

Mounting points retain CAD references and local offsets. Select a component entry,
then a vertex, point, circular edge, or two points for a midpoint. Use several
separated points for a fixed attachment. Connections join distinct component graphs;
each fastener has its own break group. Current calibrated-frame connections use
reported support patches on existing nodes. Dedicated short parent/child beam
pairs require adding parent nodes before fresh frame calibration.

Full vehicle templates distinguish **direct structural mounts** from **release
mounts** in the frame mounting plan. A direct joint uses existing structural
frame nodes. A release mount adds its short parent-node patch before calibration.
Changing either the position or representation requires a new frame graph and
calibration; changing a dropdown cannot silently alter a sealed frame artifact.
Hardpoints also need physical support in the CAD assembly. A successful linkage
solve by itself does not establish that a remote mounting point has a bracket
or frame member capable of carrying its loads.

Package the project's calibrated frame before **Package components**. The package
preserves frame provenance, geometry hashes and project identity. **Verify component
mounts** runs settle, load and release recordings in one owned BeamNG session,
respawning between recordings. Only changed files are staged; a reload during
recording fails the test. Successful tests retain compact measurements/images;
failed or explicitly requested diagnostics remain complete.

Panel/accessory stiffness and rupture remain provisional. Mounting verification
does not qualify suspension, drivetrain, crash accuracy or unknown material behavior.
