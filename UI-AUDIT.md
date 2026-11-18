# Native UI audit and replacement workflow

Reviewed 2026-11-16 on branch `audit/native-ui-2026-11-16`, against working-tree source based on commit `fbdf8be099e68f05228757a6b4f11a2c9ecc736b`.

This is an internal audit and implementation proposal, not a description of shipped behavior. Existing uncommitted application changes were included in the review and preserved. No application behavior, saved contract, generator, registration, installed vehicle, or website was changed for this audit.

## Assessment

The central problem is that the interface asks the builder to understand the program's internal operations before it explains the next vehicle-building task. Frame preparation is the main entry point, complete-vehicle work is a secondary window, and the user must reconcile several kinds of saved state across both windows and Manage Mod. Adding more explanatory paragraphs has made the interface taller without making its decisions clearer.

The replacement should be one project workspace with task navigation, actionable prerequisites, contextual editors, and an explicit distinction between **saved project edits**, **generated packages**, **verification evidence**, and **installed packages**. Retain the supported operations, but move specialist tools out of the normal route.

Fix the interaction defects before reorganizing the screens. Otherwise the redesign will reproduce ambiguous persistence and unavailable actions in a cleaner layout.

## Evidence and limits

Evidence labels below mean **S**: traced through source; **R**: observed in fixture-backed rendered WinForms or an interaction check; **H**: usability judgment requiring evaluation with a builder. Severity is **P1** for blocked work or misleading persistence, **P2** for substantial workflow friction, and **P3** for secondary usability improvements. Severity is a review judgment, not a measured user-study result.

- Built current source into a separate output directory with `XCadRegDll=false`: succeeded with no warnings or errors. Did not register or replace the loaded add-in.
- Captured 29 form views at 96 DPI, including Frame at 780×900 and 680×620, Components at 1050×900 and 850×650, and Manage Mod at 820×850 and 650×700. These are `DrawToBitmap` captures of real controls, not full SolidWorks desktop screenshots.
- Native forms used a separately launched SolidWorks process and an empty, saved, owned assembly. The catalog supplied 30 unassigned groups and 46 hardpoint requests. These counts describe this fixture only. No CAD ownership, hardpoints, physical properties, or solver results were fabricated.
- Settings, hull options, and physical-parameter forms were also inspected outside SolidWorks. The component draft-loss and cross-tab save checks ran against fixture files. The Settings check used a unique draft value and a separate settings file.
- The native fixture's save flag was dirty after the walkthrough. This audit does not claim that merely opening these forms preserves a CAD document's dirty state; no existing CAD document was used as the fixture.
- The original user SolidWorks session disappeared during the first walkthrough. The user confirmed that they closed it deliberately, assuming the audit would open its own. This is not evidence that the audit closed it. Subsequent native probing required no pre-existing SolidWorks session.
- Loaded add-in parity was not established: the initial process module inspection returned no `beamng.cad.dll` path. Native observations describe forms instantiated from the freshly built DLL in an external STA host using live SolidWorks COM, not toolbar interaction inside the original add-in host.
- Completed receipts, real assigned vehicle geometry, imported-package editing, fixture approval, auto-connect proposals, moving-member splitting, compilation, calibration, BeamNG verification, failure recovery, and installation were traced in source but not exercised end to end. Raw-parameter and fixture-review dialogs were source-reviewed; the parameter dialog was rendered. The empty fixture cannot qualify those workflows.
- Keyboard shortcuts and accessibility metadata were source-reviewed. Full keyboard traversal, screen-reader behavior, multiple monitors, and high-DPI rendering remain unverified. Overflow measurements alone are not defects: several panes intentionally scroll.

Local evidence is archived under `artifacts/native-ui-audit-20261116/`: `observations.json`, PNG captures, `probe.ps1`, isolated settings/projects, and the separate-process persistence fixture. These files are ignored local evidence, contain workstation paths, and must not be published. The temporary probe is an audit aid, not a supported native test runner.

## Ranked findings

| ID | Priority / evidence | Finding and concrete consequence | Correction |
| --- | --- | --- | --- |
| F01 | P1 · S/R | Component drafts disappear on row changes. Editing a name, choosing another group, and returning restored the old name without a save/discard decision. `LoadParameters` replaces the editor fields when selection changes. | Introduce an explicit component draft and one Apply/Discard boundary before selection changes, search filtering, project switches, refresh, or close. |
| F02 | P1 · S/R | “Save group name / role” also saved thickness changed in Physical properties. Several differently named Save buttons call the same `SaveParameters`, which commits the entire editor. Labels misrepresent the write scope. | One “Apply component changes” command for that draft, with a visible summary of affected sections. Immediate CAD assignment actions must resolve the draft first. |
| F03 | P1 · S | “Bind reviewed joint” has contradictory enablement and execution. Its handler requires `SelectedRequest`; `Selected()` enables it only for `entry.Joint != null`. It is disabled on request rows and does nothing on joint rows. Eligibility is inferred from button text. | Give commands explicit eligibility functions. Enable binding for a request with a valid owner and eligible approved joints; explain missing prerequisites. Test both row types. |
| F04 | P1 · S/R | Settings persists edited paths after a timer and on disposal, although “Save settings” suggests a pending edit. The explicit button validates game/mod paths, but the timer persists through a different route. The isolated runtime check saved a new Python value without pressing Save. | Use a Settings draft with Apply/Cancel. Validate changed fields at Apply; report errors beside those fields. Closing with changes must offer Apply/Discard/Cancel. |
| F05 | P2 · S/H | “Define Frame” and “Generate Frame Mod” both open or activate the same Frame window. Complete-vehicle work is reached through “Components / mounts.” The public entry structure presents a frame tool as the product's main workflow. | One “Vehicle project…” entry; stage-aware shortcuts select the corresponding workspace task. Preserve old command IDs as routed shortcuts if needed. |
| F06 | P2 · S/R/H | Frame puts selection, storage, reporting, advanced hull inputs, preparation, graph refitting, fixture review, calibration, packaging, verification, diagnostics, report access, and navigation in one screen. At minimum size the hull settings viewport shows only its first few rows while 18 buttons remain visible. | Move ordinary frame tasks into a focused Frame page. Keep expert operations in “Advanced frame tools”; storage/reporting belong in Settings. Show the current required action above the editor. |
| F07 | P2 · S/R | Diagnostics is enabled in a newly opened empty Frame form. `RunCalibration` immediately returns when there is no generation, so an apparently available action has no effect. Other disabled actions mostly offer no adjacent reason. | Calculate availability at construction and on every state change; display an adjacent requirement. An enabled command must execute or explain a recoverable problem. |
| F08 | P2 · S/R/H | Setup permanently gives 40% of its area to a read-only textual checklist. At 850×650, the vehicle-layout choices lie below the visible setup area while the checklist occupies the bottom. The checklist lists missing work but provides no direct route to fix it. | Overview shows a short actionable blocker list. Selecting a blocker opens its owner/editor. Put layout selection in a focused Project setup view; expand the full checklist on demand. |
| F09 | P2 · S/R/H | Components nests five detail tabs inside the main tabs and shows the Coilover tab even for the frame, mostly disabled. Physical properties exposes custom mass, parent selection, surface thickness, excluded-mass acknowledgment, auto-bolt orientation, and graph refitting together. | Show fields for the selected representation and group type. Put moving visual pieces under Appearance, spring physics under Physics, and graph refitting under Advanced. Keep excluded-mass review explicit when applicable. |
| F10 | P2 · S/R/H | Joints mixes hardpoint requests, native joints, and panel-fastener summaries in one list; a row can change the inspector tab. General authoring commands sit beside mode selection, and a synthetic guide competes with the actual editing workflow. | Separate Missing hardpoints, Native joints, and Panel fasteners as filters/views. Preserve selected owner context. Open the synthetic guide as contextual help, always labeled illustrative. |
| F11 | P2 · S/R/H | Frame definition requires “Define / edit frame” → save selection in another window → return → “Use saved frame.” The UI explains this accurately, but the builder must manually link two persisted representations. | Use one frame-assignment transaction in the project UI that explicitly saves the preparation definition and links it to the project. Retain configuration scoping and the existing stored contracts. |
| F12 | P2 · S/H | Build paths overlap: the standalone Frame workflow calibrates/packages, while complete-vehicle Build can export CAD, generate a current frame, request fixture review, calibrate, then package. The top-level button does not preview that work. | Show a preflight task summary and actual blockers before launching. Reuse existing orchestration; do not add a generator or invent a fallback. Expose frame-only generation as an explicit secondary build target. |
| F13 | P2 · S/R/H | “Save for future builds,” “Apply to selected build,” and “Install selected build” affect different states. Follow-latest versus an explicitly selected receipt adds another distinction. A long receipt path and transient status text do not explain the relationship. | Delivery names the selected revision, latest/pinned selection, pending metadata, verification evidence, and installed result. Keep Save defaults, Create metadata revision, and Install separate and label their effects. |
| F14 | P2 · S/H | Frame Quick/Full verification, component mounting checks, attachment-only checks, vehicle verification, and diagnostics live in different places. Counts in labels are not a reliable explanation of scope. A completed run, numerical acceptance, and physical qualification are different outcomes. | One Verify page offers applicable suites with their scope and prerequisite, then shows evidence tied to the actual build/generation tested. Keep diagnostics secondary; do not imply qualification or universal suite interchangeability. |
| F15 | P3 · S/R/H | Paths, internal role IDs, paragraphs of instructions, and tooltips carry much of the navigation burden. The native forms have little explicit keyboard affordance beyond component search; Settings already provides useful accessible names. | Human-readable labels with technical details expandable/copyable; concise purpose and consequence beside actions. Extend accessible names, mnemonics, focus order, and keyboard search consistently. |
| F16 | P3 · S/R/H | A new project copies the global mod profile. The empty fixture displayed an unrelated existing vehicle name and thumbnail in Manage Mod. That is existing initialization behavior, not evidence that the fixture was built. | Show metadata as defaults and state clearly that no package exists. Keep project identity, display name, and generated thumbnail provenance separate. |

Source anchors: [entry routing](beamng.cad/MainSwAddIn.cs), [component editing and orchestration](beamng.cad/UI/ComponentWorkflow.cs), [joint eligibility](beamng.cad/UI/JointWorkspacePanel.cs), [settings persistence](beamng.cad/UI/SettingsPanel.cs), [frame state and commands](beamng.cad/UI/FrameWorkflow.cs), [automatic frame generation](beamng.cad/UI/ComponentWorkflow.AutoConnect.cs), [delivery](beamng.cad/UI/ModManager.cs), and [project creation](beamng.cad/Preparation/VehicleProject.cs). Local hashes accompany the evidence so later edits do not silently change this baseline.

## Replacement navigation and behavior

Use the current WinForms/xCAD platform. Introduce a single modeless project workspace, with small dialogs for bounded edits and explicit review. This is a navigation redesign, not a UI framework migration.

```text
SolidWorks: beamng.cad > Vehicle project…       Settings…

Project: <display name>   Assembly: <name>   Configuration: <name>
Context: current / activate matching assembly   Project menu…
----------------------------------------------------------------
Overview      | Next task: <specific missing prerequisite>
Components    | Why it is needed
Joints        | [Open the relevant editor]
Frame         | Other blockers…
Build         |
Verify        | Build: <revision or none>  Verification: <status>
Delivery      | Installed: <revision / absent / unknown>
----------------------------------------------------------------
Task: <phase>  <measured progress or working>  [Stop] [Details]
```

- Navigation is freely revisitable, not a locked wizard. Overview orders blockers by actual prerequisite: context/environment, physical CAD and materials, mounting definition, frame preparation/calibration, package, verification, delivery. Explain that the mounting definition must be current before fresh frame calibration. Appearance work can proceed independently once its supported physical/imported parent exists.
- Opening with no assembly shows Project selection and a requirement to open/save an assembly; existing build delivery can still be used without an active assembly. A mismatched CAD document/configuration disables CAD-dependent actions with an activation instruction, while receipt inspection remains usable.
- Project menu contains New from CAD, Open, Import physics into an empty project, Reset imported project, Independent copy, layout choices, and working-assembly controls. Present “Authored CAD joints” and “Reviewed template definition” as supported authoring choices with their requirements. Preserve persisted `legacy` values and existing import behavior; do not silently change an old project's mode.
- Keep one workspace per project context. Child editors share the project session; another project can have its own workspace. Focus an existing matching workspace rather than opening a second editor for the same project. Re-read external package revisions before display or mutation; do not overwrite them from stale controls.

### Components and Joints

```text
Components: [Search…] [Missing CAD] [Needs review] [All]
----------------------------------------------------------------
Group list          | <group name>  <role>  <assignment state>
                    | CAD assignment  Physics  Appearance
                    | <only fields relevant to this group>
                    | Changes pending: <sections>
                    | [Apply component changes] [Discard]
----------------------------------------------------------------
CAD assignment: [Assign selection] [Assign whole components]
               [Show assigned geometry] [Zoom option]
```

- Keep physical CAD, appearance CAD, and physical-parent ownership visibly distinct. Assigning appearance must never satisfy physical readiness. Frame assignment uses the focused Frame editor rather than ordinary group-assignment buttons.
- One component draft contains name, role, representation, mass, surface, hull, and spring edits. Apply validates and commits the draft; Discard restores its baseline. Changes in other sections are included in an explicit summary. Before leaving or executing an action that refreshes/exports the draft, offer Apply/Discard/Cancel. Apply failures retain the draft and focus the error. No silent draft persistence or deletion.
- Saved CAD-reference captures remain explicit actions. For split coilover visuals, expose housing/shaft/spring and mounting orientation only for supported groups. Distinguish those visual edits from spring-rate changes requiring fresh physics.
- Joints provides a searchable work list with Missing hardpoints / Native joints / Panel fasteners views, one selected owner, and a contextual inspector. Define action eligibility by row type and actual prerequisites, never label text. Preserve distinct hinge points when binding a reviewed joint; keep motion and attachment failure settings separate.
- Auto-connect remains a reviewed proposal operation. Moving-member classification/splitting, mate repair, offsets, release sets, and physical parameters remain available in the applicable inspector or Advanced menu.

### Frame, Build, Verify, and Delivery

- Frame presents Selection → Hull preview → Fixture/orientation review → Calibration, with its current evidence and next task. Hull tuning is collapsed until requested. A project-level frame-assignment command writes both existing contracts; if linking fails, report that the definition is saved but unlinked and offer retry. Never claim atomicity across two files without implementing it.
- Build offers “Generate vehicle package” as the normal target and “Generate frame-only package” as a secondary target. Preflight lists missing inputs and the work it will perform, including fresh frame generation/calibration and required review. Start revalidates the plan against current CAD/project state. Reuse the calibrated pipeline and current invalidation checks.
- “Update package appearances” is a distinct build operation, available when saved appearances are pending and a base physics package exists. State that spring/physical edits need physics regeneration. Property refitting is a separate advanced operation that preserves node/mount positions under its existing contract.
- Verify lists the applicable current frame, vehicle, component-mounting, and attachment-only checks without claiming equivalent coverage. Show the selected input revision and the report outcome, captures, and limitations. Retain old reports as historical evidence; never assign their success to a newer untested revision.
- Delivery keeps vehicle metadata and thumbnail editing together. “Save defaults” affects future packages; “Create metadata revision” customizes the selected package; “Install revision” installs that exact revision. Metadata changes remain pending until explicitly applied. Choosing an older receipt visibly pins it; “Follow latest” is explicit. Derive installed status from existing disk comparison rather than a remembered success message.
- Do not add a new blanket installation gate as a UI side effect. Preserve existing acceptance/install policy, show missing or stale verification clearly, and do not present installation as physical qualification.
- Keep one task area with progress, elapsed time where available, Stop, a retained terminal result, and expandable logs. Stop retains completed evidence and reports which changes were saved. Closing during a task requests cancellation and waits for cleanup. Failure presents the reason and the exact repair action; logs remain available.

### Settings and layout rules

- Separate Game and installation, Build tools, Verification environment, and Storage/reporting. Use a draft with field-level validation at Apply. Validate tools needed for the operation at preflight; unrelated optional tooling must not prevent saving an otherwise valid setting.
- Start with a resizable 1050×900 workspace and support 850×650; use one vertical scrolling editor region and an always-visible draft/task footer. At narrow widths, wrap fields and toolbars; do not rely on fixed horizontal rows. Long group names and project details must be readable on selection without requiring a tooltip.
- Provide keyboard access to navigation, search, contextual actions, review, Apply/Discard, and Stop. Preserve Ctrl+F and Escape-to-clear in component search. Give inputs accessible names, define focus order, and return focus after dialogs. Do not globally bind Escape to discard work or stop a build.

## Capability disposition

No supported capability is retired. “Combine” below combines entry points or visual placement; it does not equate different physical operations.

| Existing capability family | Disposition and destination |
| --- | --- |
| Define/Generate Frame, show frame selection; workflow-window navigation | **Combine** under workspace routing; **keep** Show selection as a contextual shortcut. |
| New/open projects, layout choices, template hardpoint JSON, physics-package import/continue/reset, independent copies | **Relocate** to Project/setup; **keep** both authored and reviewed-definition paths and reset backups. |
| Create/open/update companion, optional geometry refresh, original appearance refresh | **Relocate** to Project > Working assembly and selected-group actions; preserve revision/repair distinctions. |
| Group creation, role/name editing, physical selection versus whole-component capture, frame-definition reuse, removal | **Keep** in Components; **combine** draft saves; **combine** frame definition/linking into one guided action. |
| Physical/appearance inspection, CAD highlighting, zoom, component search | **Keep** adjacent to the current group; context-specific source choice remains explicit. |
| Surface mass/thickness, representation, custom/excluded mass, parent/member choice and excluded-mass acknowledgment | **Keep** in Physics; **hide contextually** when irrelevant; preserve review requirements. |
| Hull method/density/alpha/offset, estimate, group preview, overlays | **Relocate** to contextual Hull/Advanced controls; **keep** preview and estimate effects distinct. |
| Separate appearance capture/alignment, pending appearance packaging, coilover pieces/orientation | **Keep** in Appearance; **combine** duplicated packaging entry points into Build's appearance operation. |
| Coilover spring physics | **Relocate** to Physics for supported spring/damper groups; preserve regeneration requirement and example-value warnings. |
| Native-mate command/scan, capture/bind/approve, positioning-only, highlight, check definition, authoring-mode selection | **Keep** in Joints; **combine** request review and owner context; repair command eligibility. |
| Synthetic connection guide and requested markers | **Relocate** to contextual help; preserve the explicit illustrative label and no-write behavior. |
| Moving-body classification, save/show/zoom, split companion revision, refresh colours | **Keep** in a contextual Moving members dialog; **combine** duplicate entry points. |
| Mount ownership, capture/repair/remove, local offsets, refresh CAD points | **Keep** under Joints > Hardpoints; offsets in Advanced. |
| Panel fastener add/update/remove, endpoint choice, attachment type, spring/damping/failure, release sets and short links | **Keep** under Panel fasteners; expose physical settings on selection. |
| Auto-connect options/proposal review, raw template parameters, graph/property refitting | **Relocate** to applicable Advanced tools; preserve explicit review and fixed-graph contracts. |
| Frame selection/removal, material editing/read refresh, hull defaults/tuning/visibility, prepare/accept, fixtures/calibrate | **Keep** in Frame; **hide contextually** by task. CAD material editing remains an explicit CAD mutation. |
| Fixed-graph frame refit, open immutable generation, diagnostics | **Relocate** to Advanced frame tools with current-generation context. |
| Refresh tagged CAD/inventory, frame-only package, complete-vehicle package | **Keep** in Build; **combine** orchestration entry points, not their output scope. |
| Quick/full frame, vehicle/component verification, attachment-only checks, reports/captures | **Keep** in Verify; diagnostics secondary; preserve evidence/input identity. |
| Metadata save/customize/install, choose receipt/follow latest, overwrite reinstall, image import/hull/viewport/remove, folders | **Keep** in Delivery; **relocate** incidental folder/reinstall actions to secondary controls. |
| Tool/environment paths, output location, report retention | **Relocate** exclusively to Settings, with contextual links from preflight errors. |
| Progress, cancellation, logs and retained evidence | **Combine** presentation in the workspace task area while preserving existing worker ownership and cancellation behavior. |

`ExportDialog.cs` and `StaticFramePanel.cs` are empty files in this baseline. They are not active screens or fallback generators and contribute no audited interaction.

## Implementation sequence and acceptance

Each phase should be a separately reviewable change. Keep project/receipt schemas, command IDs where practical, and generation/verification semantics compatible. Introduce only internal UI session, component-draft, and typed-command eligibility interfaces; no new external API or wire format is needed.

| Phase | Work | Acceptance criteria |
| --- | --- | --- |
| 1 — Correctness | Fix joint binding eligibility; component draft persistence; Settings Apply/Cancel; initial command availability. | Binding works for eligible requests and cannot execute on a joint-only row. Edit→switch/search/close cannot silently discard drafts. Apply commits the named scope. Invalid edited paths cannot bypass validation through timer/disposal. Empty Frame commands do not silently no-op. |
| 2 — Shared context | Introduce one workspace/session, task navigation, project/context header, and common task/result area. Route existing commands to the intended page. | Reopening focuses the matching workspace. Wrong document/configuration gives an actionable requirement. Refreshing after a package operation shows the actual selected receipt; another window's revision is preserved. Standalone delivery remains usable without active CAD. |
| 3 — Focused editors | Move component, joint, frame, and project controls into the proposed structure. Implement the existing-frame definition/link transaction and contextual fields. | All capability families above have a reachable destination. Ordinary non-coilover groups show no disabled coilover editor. No synthetic point becomes a project point. Saved frame reuse survives restart and remains configuration-scoped. |
| 4 — Build to delivery | Add readiness links, task preflight, distinct appearance operation, revision-aware Verify/Delivery, and metadata draft handling. | Fresh/resumed CAD and imported-physics routes expose the correct next action. Appearance updates cannot stand in for physics changes. Stale reports remain historical. Save defaults, metadata revision, pinned receipt, follow latest, and installed result stay distinguishable. |
| 5 — Usability verification | Check realistic assigned fixtures, keyboard traversal, resizing, and display scaling; reduce prose after testing task comprehension. | At minimum size every action and field is reachable, draft/task controls stay visible, and long labels are readable. Test 100%, 150%, and 200% DPI separately when available. A builder can locate the next action and explain its effect without consulting raw paths or logs. Record observations rather than claiming an unmeasured efficiency improvement. |

Regression scenarios must include: fresh and resumed projects; missing or corrupt selected project; wrong assembly/configuration; physical and visual ownership mismatch; partial coilover pieces; excluded-mass acknowledgment; request versus joint selection; authored versus reviewed-definition input; unresolved/stale mate scans; frame definition saved but unlinked; outdated calibrated frame; no package; appearance-only revision; older pinned receipt; pending metadata; cancelled fixture review/build; worker failure/retry; and another window producing a newer package. Preserve source CAD, prior revisions, and evidence in all checks.

## Pending UI requirement: button explanations and terminology

Added 2026-11-16 following user feedback on the Components CAD-assignment view. Builders should not need the designers' internal vocabulary or prior conversation to understand an action. This expands F15 into an explicit requirement; hover help has not been implemented by this audit entry.

- Give every action button a concise, task-specific hover explanation. Cover navigation links, icon-only commands and authoring-method choices too. Explain what the action does, what selection/input it uses, and its result. Where relevant, state whether it opens an editor, saves a project change, changes CAD, creates a revision or starts generation. Repeating the label is insufficient.
- Define unfamiliar terms in the context of the action: tagged group, hardpoint, reference skeleton, companion assembly, moving member, calibration and receipt. Prefer familiar words in labels wherever possible. Review wording across the whole workspace, rather than fixing only the buttons in this screenshot.
- Provide the same help through keyboard focus or a reachable help control, with accessible descriptions. Keep essential instructions and consequences visible beside the action. Hover text supplements those instructions; it must not become the only way to discover required inputs or save behavior.
- Explain disabled actions with the current unmet prerequisite and the next repair step. Disabled WinForms buttons do not reliably receive normal hover/focus events, so provide an adjacent reason or an accessible help target rather than relying on the disabled button's tooltip.
- Keep help readable within the narrow SolidWorks Task Pane, with sensible wrapping and enough display time to read it. Address clipped labels and overflowing instruction text as layout defects too; tooltips do not replace readable controls.

Initial examples for wording review against the handlers:

| Control | Explanation to provide |
| --- | --- |
| New tagged group | Creates and saves an empty component entry with a role and name. Assign its CAD geometry next. Explain that a group identifies geometry owned by one simulated component. |
| Assign current selection / Assign whole components | Explain exactly which selected bodies or complete component instances are included, which group receives them, and when the assignment is saved. Make the difference between these two actions explicit. |
| Moving pieces / split for mates | Opens classification of independently moving bodies within this group, such as a shock housing and shaft. Explain the separate save and companion-revision steps needed to make those pieces available for native mates. |
| Locate on reference skeleton | Opens an illustrative layout showing the selected component role. State that this guide does not assign real CAD geometry or measured hardpoints. |

Acceptance: inventory the workspace's buttons and related action controls, review their help against actual behavior, and check hover, keyboard access, disabled-state explanations and narrow-pane readability. In a walkthrough, a builder unfamiliar with the implementation should be able to explain an action's inputs and effects before pressing it. Record missing or misleading help and observed comprehension; this entry does not claim completed usability verification.

## Pending UI correction: frame assignment from Overview

Added 2026-11-16 following the user's live Components screenshot. The builder followed Overview into the component list, selected the Frame group and highlighted frame CAD, then found the expected assignment action disabled. This extends F11 and the disabled-action requirements above; no UI behavior has been changed for this entry.

- Observed: Frame is selected and CAD geometry is highlighted, but **Assign current selection** and **Assign whole components** are greyed out. The group still reads **CAD: unassigned**. Further down, the panel reports a saved frame definition for the current configuration and offers **Define / edit frame…** and **Use saved frame**. The footer also shows **Failed: Define the frame selection first.** The screenshot does not establish which action produced that failure.
- Source confirms that frame rows deliberately disable the ordinary assignment buttons. Frame definition capture and linking that saved definition to the project are separate operations. The problem is that Overview and the shared assignment editor establish an expectation of direct assignment before exposing this exception.
- Make the route consistent from Overview onward: identify frame assignment as a distinct task and open the relevant controls directly. When Frame is selected, prioritize its available next action and explain whether the current selection, a saved definition, or a project link is missing. Do not lead with generic assignment instructions and disabled ordinary-component commands.
- Prefer the single frame-assignment transaction proposed in F11: capture the intended CAD selection, save the configuration-scoped preparation definition, and link it to the project through one explicit action. Offer reuse/edit of an existing definition clearly, preserving both persisted contracts and keeping calibration a separate task.
- Reconcile saved-definition, project-assignment and failure messages so a builder can understand why a saved frame can coexist with an unassigned group, and what action resolves the current state.

Acceptance: walk from Overview to assigning a new frame and to reusing an existing saved frame in a fresh project. In each case, the next action is visible and usable without discovering an exception lower down the pane or interpreting a greyed-out button. Check narrow-pane layout and keyboard access. This entry records user feedback and source review, not a completed interaction test or implemented correction.

## Pending UI clarification: reviewed template JSON

Added 2026-11-16 following user feedback on **New CAD project — authoring method**. The label **Reviewed template JSON mounting definition** was unclear: it could be understood as a compact archive of a prepared assembly and its file relationships. This is a recorded usability finding and proposed correction; the dialog has not been changed for this item.

- Explain the input before the authoring-method choice. Suggested label: **Use an existing reviewed vehicle definition (JSON)**. Suggested help: “Load a checked definition of the vehicle mechanisms, hardpoint coordinates, mounts and physical parameters. CAD geometry and component assignments are supplied separately. Choose native CAD authoring to capture these inputs through SolidWorks mates and reference geometry.”
- Explain that “reviewed” means the definition's values and relationships have been checked against the actual vehicle/CAD assembly. It does not mean BeamNG testing or physical qualification has been completed. Example skeleton coordinates are placeholders.
- State that this option expects an existing definition matching the selected vehicle setup. Selecting it does not automatically export a prepared assembly, bundle CAD files or meshes, or make the assembly portable. The definition can contain measurements taken from a prepared assembly, but it is a mechanism specification rather than an assembly archive.
- Keep the explanation consistent in the new-project dialog, Project/setup import controls, Joints authoring-mode selection and maintained template documentation. Preserve both supported authoring routes and existing saved contracts.

Acceptance: before choosing a route, a builder can identify what JSON they need, what it contains, what separate CAD inputs remain necessary, and what “reviewed” establishes. Check comprehension during the next native UI walkthrough; this feedback is not a completed usability study.

## Pending UI clarification: completing material assignment

Added 2026-11-16 following user feedback while assigning materials to selected CAD. The user initially thought **Apply** did nothing, then noticed the small instruction below telling them to close when done. Record this as a discoverability and completion-feedback issue; the report does not establish a failed material write. No application behavior has been changed for this entry.

- Make the instruction to close when finished prominent beside the material action controls, rather than relying on small text below the editor.
- Explain what **Apply** affects, whether the material editor remains open, and what closing it does. Review the actual handler before choosing labels such as **Apply and close** or **Done**, so the wording matches persistence behavior.
- Give visible feedback after applying to the selected items, including the affected selection and any failure or unavailable prerequisite. Make the next step clear without requiring the builder to search for footer instructions.

Acceptance: during the next native walkthrough, a builder can apply a material to selected CAD, recognize the result, and identify how to finish and return to the workflow without discovering a small instruction below. Check narrow-pane readability and keyboard access. This entry records user feedback, not a completed interaction test or implemented correction.

## Pending UI improvement: frame approximation feedback and preview

Added 2026-11-16 following user feedback while making the frame approximation. Parameter explanations and feedback are insufficient for a new builder, who cannot be expected to share the numerical intuition of someone who has repeatedly tuned these values. This extends F06; it records a usability finding and proposed work, not an implemented preview or measured performance result.

- Explain each approximation parameter beside its control: what it changes, its units or scale, and the expected effect of increasing or decreasing it. Describe the relevant tradeoffs, such as geometric detail, graph complexity and processing cost, where supported by the actual algorithm. Review explanations against the implementation rather than inventing recommended ranges.
- Provide a visual preview using the selected frame CAD, with clear overlays for the approximation and resulting graph where available. Let the builder compare the result with the source geometry and see which details are retained or lost. Include useful result summaries, such as node/beam counts and available geometry diagnostics, tied to the parameters that produced them.
- Investigate GPU acceleration for responsive rendering and, where feasible, preview computation. The goal is fast, snappy feedback as parameters change; the backend is a feasibility question. Distinguish rendering speed from solver recomputation cost. Debounce expensive updates, cancel superseded work where supported, and show progress and stale-preview status so an old result cannot appear to represent new settings.
- Label any illustrative or reduced-fidelity preview and explain its limits. Keep actual calibrated generation and its validation authoritative; a visual preview does not establish physical properties or qualification. Do not present interpolated or fabricated solver output as a recomputed result.

Acceptance: in a walkthrough, a builder unfamiliar with the numbers can explain a parameter's effect, change it, recognize which settings the displayed result represents, and judge the visible geometric tradeoff before committing to generation. Measure update latency on representative assemblies and check keyboard access, narrow panes, cancellation and unavailable GPU behavior. Record preview fidelity and performance limits with the findings; this entry does not claim those checks have run.

## Frame preparation failure follow-up: unloaded CAD and worker imports

Added 2026-11-16 following the user's preparation log. Automatic inspection of a restored frame emitted two lightweight-component exception traces. The subsequent material action reported all 66 bodies assigned with none remaining; preparation then failed importing `appearance_textures`. The assignment report is separate from preparation success.

Source review identified that the gated Python launcher used `runpy.run_path` without adding the script directory to `sys.path`. The sibling module exists in the reported output directory. The launcher now restores direct-script import behavior and includes import errors in its failure summary. Frame startup now recognizes the lightweight condition, retains the saved selection names and explains that inspection is pending. An explicit **Load frame data** action loads only the saved frame scope while preserving selection; automatic opening and material refresh remain read-only. Missing references and genuine suppression still surface as errors.

Verification: isolated Debug build with `XCadRegDll=false` passed (36 warnings, no errors). The actual launcher passed sibling imports from a nested directory, spaced-argument handling, preparation `--help`, missing-module error reporting and parent/child cancellation checks. Offline workspace checks passed. These results do not establish completed hull generation or native lightweight interaction; the existing SolidWorks session and its loaded add-in were left untouched. Recheck restored lightweight frames, explicit loading and suppression in an owned native fixture before claiming that coverage.

## Pending physics audit: timestep stability and dynamic accuracy

Added 2026-11-16 following the beam-expert discussion. This is a proposed verification task, not a completed test or qualification result.

- Check the highest coupled structural frequency against the solver's stability limits, including damping. At a 0.5 ms timestep, an undamped central-difference model has a theoretical stability boundary near 637 Hz. Confirm that this model applies to the current BeamNG solver through controlled in-game tests; do not treat that number as a verified engine limit.
- Use an isolated spring/mass fixture to measure frequency and decay errors below the stability boundary as well as the onset of divergence. State endpoint constraints and use reduced mass for two freely moving nodes. Compare the observations with the existing coupled-frequency and damping checks.
- Assess whether timestep-driven stiffness reductions materially change suspension response or hardpoint deflection under representative loads. Numerical stability alone does not establish physical accuracy or qualification.
- Treat telemetry sampling/Nyquist limits separately: they govern which frequencies the measurements can resolve, not whether the simulation is stable. Record the actual physics timestep and telemetry sampling rate with the evidence.

Use isolated fixtures and output directories, preserving existing CAD, projects, installed vehicles, and historical evidence. References: [BeamNG physics timestep](https://documentation.beamng.com/beamng_tech/tools/cosimulationeditor/tight_coupling/), [BeamNG developer discussion of explicit integration](https://www.beamng.com/threads/quick-question.28725/), and [beam stiffness/damping warnings](https://documentation.beamng.com/modding/vehicle/sections/beams/).

## Verification performed for this audit

These checks validate the inspected baseline and audit evidence. They do not validate the proposed redesign, which is not implemented.

```powershell
dotnet build beamng.cad.slnx -c Debug -p:XCadRegDll=false -p:OutputPath=bin/ui-audit-20261116/
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-WorkflowProgress.ps1 -OutputDirectory beamng.cad/bin/ui-audit-20261116
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-FrameAssignmentWorkflow.ps1 -OutputDirectory beamng.cad/bin/ui-audit-20261116 -Destination artifacts/native-ui-audit-20261116/persistence -Phase Write
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-FrameAssignmentWorkflow.ps1 -OutputDirectory beamng.cad/bin/ui-audit-20261116 -Destination artifacts/native-ui-audit-20261116/persistence -Phase Read
```

Build, task-progress lifecycle checks, and separate-process frame/group persistence/search checks passed. Fixture interaction observations confirmed Settings autosave without Save, unsaved-name loss on component switch, and cross-tab thickness persistence from the name/role Save button. There were no generation, BeamNG, installation, full keyboard, or high-DPI qualification runs. Website checks were not applicable because no website content, tooling, or evidence registry changed.


## Initial implementation: native categories and docked workspace

The first implementation is on the audit branch. Following the manual-review feedback, the project workspace is hosted in a **native SolidWorks Task Pane**, with **Project, Components, Joints, Frame, Build, Verify, Delivery, and Settings** available as SolidWorks CommandManager commands. Define Frame is no longer the floating parent of the workflow. Focused file, authoring-method, new-group, fixture, and parameter dialogs remain separate where appropriate.

Implemented:

- Explicit component Apply/Discard, including spring edits, with pending-change decisions before selection/search/task changes and operations. New group creation has its own role/name dialog.
- Settings Apply/Discard and changed-field validation; no timer or disposal autosave.
- Typed joint-action eligibility, including functional reviewed-joint binding for eligible requests.
- Immediate Frame availability checks, including disabled diagnostics without a generation.
- Shared project/context header, separate Build and Verify tasks, retained task output, Stop, and expandable Details.
- New from CAD creates a separate native-authored or reviewed-definition project, with unassigned groups and no imported physics or generated package. Previously saved frame definitions remain available explicitly; opening the workspace does not link them automatically.
- Narrow component/joint lists stack above their editors. The component Apply/Discard footer remains reachable.

The existing specialist editor bodies are reused in this first batch. Deeper reduction of frame controls, contextual tabs, and joint-list organization remains further work; this is not completion of all audit recommendations.

### Verification of the first batch

- Isolated compilation succeeded with no errors and 36 warnings, predominantly existing deserialized-field/unreachable-code warnings. COM registration was disabled during compilation.
- `tools/Test-ProjectWorkspace.ps1 -Native` passed against the release output: Settings validation/decisions, fresh project isolation, joint binding, component draft decisions, new-group ownership, narrow footer access, initial Frame availability, all task routes, and actual Task Pane control hosting. UI-thread exceptions are captured and fail the check.
- Progress lifecycle and separate-process frame/group persistence/search checks passed.
- Website type/content checks, production build, links/assets/search/provenance checks passed. Browser checks: 34 passed; two WebGPU checks skipped because that backend was unavailable.
- Application evidence review passed. The full documentation evidence check still reports unrelated changes in frame generation, calibration, and website configuration. Their hashes were not refreshed by this UI task.
- Native checks used owned empty assemblies and isolated settings/projects. No vehicle generation, BeamNG verification, user project edits, or package installation was performed. Full keyboard traversal and high-DPI native coverage remain unverified.

Two test-development failures were corrected before the passing run: a generic Windows callback in the prompt helper, and a null-editor comparison in the workspace status timer. The corrected suite exercises an idle workspace through multiple timer ticks and rejects UI-thread exceptions.

### Manual from-scratch trial

1. Open and save the intended assembly/configuration in SolidWorks.
2. Choose **Project > New from CAD...**, select the authoring method, and save a new project filename. Your previous projects and packages remain available.
3. Set the vehicle layout through **Project > Vehicle layout and project tools...**. Apply any Settings edits explicitly.
4. Use the native **Components**, **Joints**, and **Frame** category buttons to assign and review your own CAD. Use **Apply component changes** for edited fields. Frame selection and project linking remain explicit; choose the current CAD selection when redefining the frame.
5. Use **Build > Refresh tagged CAD** for the first inventory checkpoint. Review it before intentionally running calibration/generation. **Verify** and **Delivery** operate on generated package revisions afterward.

The add-in launch leaves these decisions to the builder; it does not automate the vehicle-building sequence.


### Live host verification and handoff

The live CommandManager was checked against the existing companion assembly from the first export, rather than the broken source assembly. All category buttons are present. A Toolbox/PDM lookup prompt blocked the initial open calls; declining that external lookup allowed the existing companion to finish opening. No CAD document was saved by the automation.

Live inspection found a limitation missed by the initial raw-HWND hosting check: the command reached Overview, but the control stayed at its default size and the panel was not activated reliably. The final implementation uses xCAD's `CreateTaskPane<DockedProjectHost>` and `IsActive` lifecycle, with the project workspace inside its managed control container. A real native Project click then displayed the full-height docked editor beside the companion.

To preserve the already-open companion while replacing the loaded managed add-in, the running preview was built with an isolated assembly identity (`beamng.cad.workspace.preview`) and registered from `bin/ui-workspace-native-host`. This is a build override, not a project configuration or saved-contract migration. The normal assembly identity also compiles successfully into `bin/ui-workspace-verified`. Current-user registration backups are retained with the isolated output.

The existing companion remains open and the docked panel is at its fresh-project entry, without a project selected or generation started. The final host revision passed its offline regression checks; the component/native interaction suite passed before the hosting replacement, and the replacement's activation and sizing were additionally verified in the live add-in. Native high-DPI and full keyboard traversal remain unverified.

## Implemented: separate GPU live approximation

Added 2026-11-17 in response to the preview feedback and the native-mate failure log. This updates the pending approximation item above; it does not requalify earlier native walkthroughs.

- **Live proxy preview** captures saved-frame display triangles without reading materials or scanning mates. Parameter edits reuse the snapshot. SolidWorks COM capture stays on its owning thread and yields between faces; an individual native call remains non-interruptible.
- The separate preview window uses OpenGL compute to voxelize triangles, close gaps, apply approximate symmetry and expand the surface. It compacts boundary faces and draws them directly from GPU buffers. No generated geometry is read back during interaction, and no SolidWorks wire bodies are created. Input edits debounce for 80 ms; superseded results are hidden and pending work is cancelled.
- This is a distinct approximation algorithm, not GPU execution of CGAL. A 64-cubed voxel volume and bounded box morphology trade fidelity for update latency. Alpha scale, offsets and source-half symmetry affect the approximation. Final grid construction, shrinkwrap and welding require **Prepare actual hull**. Cell spacing and radius caps are displayed; no physical properties or hardpoints are inferred. The [CGAL manual](https://doc.cgal.org/latest/Alpha_wrap_3/index.html) describes the authoritative algorithm's different construction and guarantees.
- **Prepare actual hull** retains the existing CPU preparation route. **View prepared hull** displays its actual OFF edges in a batched viewport mesh. Ordinary preparation no longer scans the full vehicle's mates or requires suspension hardpoints. **Accept hull / review fixtures** performs those checks before generation, retaining the prepared hull when bindings are missing. Explicit fixed-graph refitting still checks its mounting contract.
- Missing GPU compute falls back to a labeled, bounded CPU occupancy approximation. Software viewport rendering, stale-state handling, keyboard camera controls, Stop and close cleanup are covered by standalone checks. The original CAD and physical generation contracts are unchanged.

### Dated performance evidence

Measured on the NVIDIA GeForce RTX 3050 Laptop GPU using an existing 43,994-triangle prepared frame STL; source SHA-256 `4830fe32acbf9f3598f042419eec0ce361c889f44c57d022f4d736c7d4351c20`.

| Operation | Observation | Scope |
| --- | --- | --- |
| Initial GPU snapshot conversion, upload, voxelization and first approximation | 950 ms | Excludes native CAD capture |
| 20 resident-snapshot alpha edits | Median 2.6 ms; 95th percentile 31.9 ms | GPU submission through completion fence; excludes debounce and presentation |
| Authoritative Blender/CGAL hull worker | 6.531 seconds | Fresh owned output, same saved STL, original 3×5×7 settings; excludes CAD export and mate scan |

These operations have different fidelity and outputs. The GPU does not predict final node/beam counts, and these timings are neither end-to-end application timings nor physical qualification. The CPU run completed with output SHA-256 `8e23bd9c3bb6371c6048da22cf496142a2adb9bb83ae36b1789552e3d5044b49`. The measured renderer and volume shader hashes are `31df805ca2819f28a403baf7121aead75558a3741a2c8a77932ac45c6574ddaa` and `bfb3f6d66d6c4fab50b1bc228c0211a36b2fb42745027d3cdc264822b9e2ee6a`, respectively. Raw logs remain local under `artifacts/proxy-preview-*` and `artifacts/proxy-benchmark-*`.

### Verification and remaining coverage

Isolated compilation into `beamng.cad/bin/proxy-preview-verified` passed with `XCadRegDll=false`, no errors and 36 existing warnings. GPU checks passed on actual saved geometry, including visible framebuffer pixels, parameter changes, cancellation, stale-result removal, caller graphics-context restoration and closing during snapshot work. Forced-software checks passed for CPU geometry, OFF parsing/display, rapid edits, minimum window size and disposal. An asymmetric Blender fixture confirmed the positive-X default source half and the opposite-half switch. Task-progress and offline project-workspace regressions passed.

Two implementation failures found by these checks were corrected: asynchronous graphics continuations without a host synchronization context, and attempting to make a destroyed window's graphics context current during disposal. A reversed approximate symmetry source-half choice was also corrected against the Blender fixture.

Handbook checks and the production link/asset/search/provenance checks passed. Browser results: 34 passed; 2 website WebGPU tests skipped because that backend was unavailable. Application evidence hashes, including the new shaders, were reviewed. The strict evidence check still flags frame-generation, frame-calibration, vehicle-generation and website groups; unrelated historical hashes were not refreshed to silence those warnings. The website group also tracks the shader-extension addition to the evidence checker.

The new preview has **not** been registered or loaded into the existing SolidWorks session. Native display capture on the user's current assembly, loaded-add-in parity, full keyboard traversal, high-DPI behavior and unavailable-hardware behavior remain unverified. The standalone GPU and forced-software results do not establish those checks. No existing user CAD, project, installed vehicle or historical recording was changed by this verification.

### Docked preview follow-up (2026-11-17)

The floating preview was created with an unowned `Show()` call. Source inspection found no settings handler that closes it; losing it behind SolidWorks is a plausible explanation for the reported disappearance, not a reproduced native-host diagnosis.

The frame editor now owns an embedded preview for its entire lifetime. `FramePreviewPane` shares a resizable split with the editor tabs: stacked below 760 px and side by side when wider. Settings edits retain the renderer and input focus. Selection/storage controls live under Selected geometry; generation tools live under Build / calibration. Hull settings and its preparation actions remain together, and settings scroll independently. Preview details expand the full status and fidelity limits without consuming the default narrow viewport. Hull help text spans both columns instead of being squeezed into a third column.

Isolated compilation into `beamng.cad/bin/proxy-preview-docked` passed with COM registration disabled, zero errors and 36 existing warnings. Both actual OpenGL and forced-software tests exercise real numeric settings, stable preview/graphics handles, focus, narrow/wide layout, divider movement, tab changes, removal/reattachment, and owner disposal during updates. Offline project-workspace and task-progress checks pass. This layout verification uses a synthetic display fixture and does not replace the dated performance measurements above. Running SolidWorks and high-DPI coverage remain unverified; no add-in registration was performed.

### Disconnected document and installation follow-up (2026-11-17)

User logs reported RPC_E_DISCONNECTED at FrameSelection.ValidateDocument, while GPU updates completed. The editor retained its original native document wrapper, and session checks accepted a reopened assembly by saved filename alone. Validation now checks native identity before dereferencing the document and translates a disconnected object into recovery guidance. While idle, Frame can replace the wrapper only for the same source path and original configuration; this invalidates captured/prepared results and restores the saved assignment. Pending hull settings are saved before reload. An in-flight operation never rebinds to a replacement document. Session context supplies the current active wrapper to future editors.

Managed COM-interface doubles exercise disconnected identity, idle rebinding, configuration rejection, cache invalidation and refusing to rebind during capture. Build, actual OpenGL, software fallback and offline workspace checks pass in `beamng.cad/bin/proxy-preview-context`. Native-host reproduction of this disconnect remains unverified.

The user's screenshot still showed the previous floating-window layout. Effective COM registration pointed at Debug/net472. Registration has now been deliberately updated through Register-CurrentUser.ps1 to the tested proxy-preview-context output, with the prior per-user keys backed up by that script. The running SolidWorks session was left open; it must be restarted after saving CAD to load the updated managed add-in. Registration is not evidence of a successful live-host load.

### Projected live hull and symmetry recovery (2026-11-17)

The coarse pruning volume did not show what the grid/shrinkwrap/weld stages produce. The default live display now shows projected edges. GPU proxy closing/dilation feeds a bounded volume readback, then a background CPU worker lays out the requested lattice, retains intersecting/enclosed cells, extracts boundary polygons, projects vertices onto nearest captured CAD triangles through a cached bounding-volume tree, applies surface offset, clips/mirrors the selected X half, snaps the seam and welds nearby vertices. Triangulated edges are uploaded for GPU drawing. The intermediate pruning volume has its own optional checkbox. The CPU fallback uses conservative triangle boxes for its proxy and the same later stages.

Surface offset is applied after projection, rather than conflated with proxy offset. Symmetry happens after projection, rather than modifying the resident voxel seeds. Approximate proxy bounds, tessellation, polygon clipping, seam snapping, representative-based welds and fan triangulation still differ from CGAL/Blender. This remains a visual estimate, never a generation input or physical graph. In the saved original-settings frame it produced 64 vertices/187 edges; this is not an acceptance tolerance or evidence of exact topology parity.

The persistent orange box in the supplied screenshot was the labelled CPU occupancy fallback. Invalid even-width symmetry was being caught as a GPU failure, permanently switching backends. InvalidDataException is now treated as an editable input/result error, retaining the GPU backend and immutable source snapshot. Fixing the setting resumes the same renderer. Explicit buffer-update barriers make compute output visible to the new CPU volume readback; the ordering requirement is documented in the [OpenGL memory-barrier reference](https://wikis.khronos.org/opengl/GLAPI/glMemoryBarrier).

Build into `beamng.cad/bin/proxy-preview-projected` passed with registration disabled, zero errors and 36 existing warnings. Analytic cube checks cover known lattice topology, projection of an oversized lattice onto CAD, grid changes, independent surface offset, weld collapse, seam distance and cancellation. Actual GPU checks cover visible projected edges, positive/negative source-half selection, identical geometry after symmetry on/off, invalid even-width symmetry recovery without backend changes, stale-result removal, context restoration, docking and disposal. Forced-software and disconnected-document checks pass.

Fresh local measurements on the same saved 43,994-triangle STL and RTX 3050: initial conversion/tree/upload/voxelization plus first projected result 2,093 ms; 20 alpha edits at 9×9×9 with zero weld/offset median 77.7 ms, p95 94.3 ms; five updates at original 3×7×5 (X/Y/Z), 0.01 m offset and 0.15 m weld median 31.6 ms. Repeated timings include GPU volume work/readback, CPU topology/projection/weld and edge upload, and exclude capture, snapshot setup, debounce and presentation. These timings supersede no historical measurements above: the new path performs substantially more work. Raw local logs are `artifacts/proxy-preview-projected-{gpu,software}-final.local.log`. Native-host/high-DPI coverage remains unverified.

After these checks, per-user registration was deliberately pointed at the tested `proxy-preview-projected` build using Register-CurrentUser.ps1. Its registration directory contains backups of the preceding keys. The current SolidWorks process remains untouched and requires a restart to load this build. Handbook type/build/link checks and application evidence review pass; unrelated source-group drift remains flagged.

### Sparse outer-hull search (2026-11-17)

Implemented the approved fast-shortlist / explicit-check workflow. Find sparse hull opens Hull suggestions with Coarser/Balanced/Finer quality choices, cancellation, candidate preview, Check selected and Apply. Search changes only grid dimensions, alpha divisor and weld. Surface offset, mapping, symmetry, source half, seam and offset ratio remain locked until explicit ratio refinement during checking. Current settings and prepared results are retained during search/review; Apply uses the normal options-change path and invalidates prepared output. CAD/context/setting/quality changes discard suggestions.

Preview results now retain canonical indexed triangles with consistent boundary winding. Eligibility checks require one connected closed oriented shell, Euler characteristic 2, cycle-shaped vertex links, nonzero volume, no collapsed/duplicate faces and no illegal triangle intersections. The fixed 96-pixel silhouettes from 26 directions conservatively rasterize CAD and fill enclosed image openings; candidates are compared with the same raster coverage. This avoids scoring every tube independently or rewarding oversized boxes/inward collapse. Balanced error limits and ranking are documented in the maintained frame guide. The score is a visual heuristic, not engineering accuracy or global optimality.

GPU evaluations retain the displayed buffers and reuse resident source/tree/proxy data. CPU fallback uses weakly held per-snapshot caches. Search uses at most 150 distinct evaluations with a cancellable 20-second evaluation budget after setup. The three suggestions span the vertex-count/fit frontier. Check selected writes a fresh isolated captured STL and invokes the existing alpha-wrap adapter at half/current/double offset ratio through an owned process job. Each completed OFF result is re-scored; failures and cancellation preserve preceding results. Checked snapshots never become a prepared generation or physical graph.

Current local verification: isolated `bin/hull-search` build passed with registration disabled, zero errors and 36 existing warnings. Geometry fixtures reject open/disconnected/collapsed/duplicate/self-intersecting shells and a watertight torus, and accept a windowed frame covered by a sparse shell. Count-bounded determinism, proxy deduplication, cancellation deadline, unchanged settings/viewport, Apply cloning/real frame invalidation, locked settings and stale-CAD cancellation pass. Python worker checks cover partial failure, missing output, cancellation retention and changed snapshot fingerprints. Standalone actual OpenGL and owned Blender/CGAL checks pass; native loaded-add-in behavior remains unverified.

On the saved 43,994-triangle STL, one current GPU run evaluated 150 candidates in 7.7 seconds after setup and returned 43-, 52- and 76-vertex alternatives. The 43-vertex 3×4×4 (X/Y/Z) candidate produced three full checked meshes at ratios 50/100/200; two met Balanced criteria and one missed fit tolerance. This is a dated local example, not a guarantee for other CAD. Raw logs remain local under `artifacts/hull-search-*`; native check outputs use fresh temporary fixture directories printed by Test-HullSearch.ps1.

Final software-fallback, actual OpenGL, owned Blender/CGAL, worker, frame-document, workspace and progress checks passed. Handbook type/build/link and application-evidence checks passed. Strict global evidence checking continues to flag pre-existing frame-generation, frame-calibration, vehicle-generation and website drift; the candidate worker is additionally tracked by the reviewed application group. After verification, Register-CurrentUser.ps1 pointed the existing per-user registration at `bin/hull-search`, backing up prior keys. The running SolidWorks process was left untouched; a restart is required to load this managed assembly. Registration does not establish live-host behavior.

### Search opened before capture: navigation repair (2026-11-17)

The supplied narrow-pane screenshot showed Hull suggestions selected, with earlier tab headers scrolled off-screen. Search correctly required a snapshot, but its message referred to the hidden Live proxy preview action. Show current settings only refreshed the viewport and did not select the actual settings page.

Show current settings now selects the canonical Hull settings tab through its owning workflow. Suggestions has a direct Start / refresh preview action, and the permanent preview toolbar says Start preview until capture succeeds, then Refresh CAD. Missing-snapshot guidance names these visible actions; successful capture replaces that guidance with the next search action.

The COM-interface fixture reproduces opening suggestions before capture in a 360-pixel editor and verifies both capture entry points and navigation back to Hull settings without changing saved values. The isolated `bin/hull-search-navigation` build and focused document/navigation plus software-preview regressions pass. Handbook type/build/link and application evidence checks pass. Per-user registration now points at this tested build, with prior keys backed up. Running SolidWorks remains untouched and must restart to load the update; live-host reproduction is not claimed by the fixture.

### Checked result outside fit target: Apply eligibility (2026-11-17)

The user's screenshot selected Finer, with a successfully checked mesh still marked outside fit tolerance. Apply was disabled by the quality criterion, not by unfinished checking. Rounded whole-percent fit labels and the absence of an adjacent explanation obscured the distinction.

Suggestions now show one-decimal fit scores and an Apply status showing the selected quality's fit and worst-view limits against actual metrics, or its structural rejection reason. Quality changes reclassify the existing meshes without rerunning geometry or clearing the checked status/selection. They do not change current hull settings. New searches remain available to explore other candidates. Closed-shell and intersection failures remain ineligible at every quality.

GPU and software fixtures verify that a checked mesh with 95.5% weighted fit and 92% worst-view overlap is rejected under Finer and accepted under Balanced, retaining the same mesh, selection and checked status. The isolated `bin/hull-search-eligibility` build passed with registration disabled, zero errors and 36 existing warnings. Handbook type/build/link and application evidence checks passed. The existing per-user registration now points at this tested build with prior registration keys backed up. The running SolidWorks process was left open; restart is required to load the update, and native-host behavior remains unverified.

### Manual application remains the user's choice (2026-11-17)

The user explicitly requested that optimizer criteria not prevent applying a chosen result. Apply now copies any selected candidate's settings while idle. Candidates outside fit targets or with structural optimizer warnings show Apply anyway, with their diagnostics retained. The optimizer's accepted flag still governs ranking/recommendations and is never changed by manual application. No confirmation dialog is added. Normal preparation/generation input checks remain in place; applying settings does not approve a mesh or physical result.

GPU and software regressions verify actual Apply callbacks for below-target checked candidates and structural-warning candidates, cloned settings, unchanged rejection status/diagnostics, quality reassessment and stale-result invalidation. The isolated `bin/hull-search-manual-apply` build passed with registration disabled, zero errors and 36 existing warnings. Handbook type/build/link and application evidence review pass. Per-user registration points at that tested build with previous keys backed up; the running SolidWorks process remains untouched and must restart to load it. This supersedes the earlier UI restriction, without changing the optimizer's scoring thresholds.

### Pruning-volume visibility and ownership (2026-11-17)

The pruning toggle could address a stale/absent indirect-draw buffer after candidate selection; software and OFF-only views also exposed an ineffective control. GPU approximation results now retain their immutable proxy-volume array. Presenting a candidate uploads its own volume and regenerates boundary faces, while offscreen search evaluation leaves the displayed volume intact. Opacity is increased for visibility, and live parameter edits preserve the user's toggle choice. Checked/prepared OFF results and software views disable the checkbox as Pruning volume (not retained), rather than showing an unrelated approximation or old buffer.

Real GPU framebuffer checks verify visible volume pixels on/off, unchanged visible buffers during evaluation, correct boundary-face count from the selected candidate's cells, selection rendering, and no stale volume for an OFF-only result. Integrated UI checks cover live-update toggle retention and prepared-view disabling. Software candidate checks confirm volume availability is disabled there. The isolated `bin/proxy-volume-toggle` build passed with COM registration disabled, zero errors and 36 existing warnings. Handbook type/build/link and application evidence checks pass. Per-user registration now points at that tested build with prior keys backed up. SolidWorks was left running and requires restart to load it; native-host validation remains pending.

### Manual trial finding: Next step after the proxy

The frame preview finished while required physical bodies still needed separate assignments. The hardpoint prerequisite appeared only in the status at the bottom of Frame, and the builder had to switch between menus to find the next action. A persistent Next step panel now leads from the first missing CAD group to actual joints and hardpoints, then to hull acceptance and fixture review. Acceptance still runs the existing mounting checks. The geometry preview can be used throughout setup.
