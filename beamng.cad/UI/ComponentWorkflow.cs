using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using BeamNG.Cad.FramePipeline;
using BeamNG.Cad.Preparation;
using SolidWorks.Interop.sldworks;
using Environment=System.Environment;

namespace BeamNG.Cad.UI
{
    internal sealed partial class ComponentWorkflow : Form
    {
        private readonly ISldWorks app;
        private readonly ModelDoc2 model;
        private readonly FrameSelection selection;
        private VehicleProject project;
        private ExporterSettings settings;
        private readonly ComponentAssignmentList components=new ComponentAssignmentList();
        private readonly TextBox componentSearch=new TextBox {Name="ComponentSearch",Dock=DockStyle.Fill};
        private readonly Label componentCount=new Label {Name="ComponentCount",AutoSize=true};
        private readonly TextBox activeProject=new TextBox {Name="ActiveProjectPath",Dock=DockStyle.Top,ReadOnly=true};
        private readonly ListBox anchors=new ListBox {Name="MountAnchors",Dock=DockStyle.Fill,DisplayMember="Label"};
        private readonly MountOwnerPanel mountOwner=new MountOwnerPanel();
        private readonly ListBox connections=new ListBox {Name="MountConnections",Dock=DockStyle.Fill,DisplayMember="Label"};
        private readonly ComboBox template=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Width=130};
        private readonly MvpCatalog mvpCatalog=MvpCatalog.Load();
        private readonly ReferenceSkeleton referenceSkeleton=new ReferenceSkeleton();
        private JointWorkspacePanel jointsPanel;
        private readonly TemplateImportPanel templateImport=new TemplateImportPanel();
        private readonly AssignmentInspectionPanel assignmentInspection=new AssignmentInspectionPanel();
        private readonly CoiloverPanel coiloverPanel=new CoiloverPanel();
        private readonly FrameAssignmentPanel frameAssignment=new FrameAssignmentPanel();
        private readonly CompanionAssemblyPanel companionPanel=new CompanionAssemblyPanel();
        private readonly Button assignSelection=new Button {Name="AssignCurrentSelection",Text="Set to selected",AutoSize=true};
        private readonly Button addToGroup=new Button {Name="AddToGroup",Text="Add to group",AutoSize=true};
        private readonly Button assignComponents=new Button {Name="AssignWholeComponents",Text="Assign whole components",AutoSize=true};
        private FrameAssignment savedFrame;
        private string savedFrameError;
        private string[] otherFrameConfigurations=Array.Empty<string>();
        private Action continueTemplate;
        private readonly ComboBox mvpRole=new ComboBox {Name="MvpRole",DropDownStyle=ComboBoxStyle.DropDownList,Width=260,DisplayMember="Label"};
        private readonly TextBox mvpChecklist=new TextBox {Name="MvpChecklist",Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Both,Dock=DockStyle.Fill,WordWrap=false};
        private readonly Dictionary<string,ComboBox> templateChoices=new Dictionary<string,ComboBox>();
        private readonly ComboBox method=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Width=120};
        private readonly ComboBox surfaceMass=new ComboBox {Name="SurfaceMassMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=230};
        private readonly ComboBox visualParent=new ComboBox {Name="VisualParent",DropDownStyle=ComboBoxStyle.DropDownList,Width=210,DisplayMember="Label"};
        private readonly ComboBox representation=new ComboBox {Name="ComponentRepresentation",DropDownStyle=ComboBoxStyle.DropDownList,Width=190};
        private readonly ComboBox massPolicy=new ComboBox {Name="ComponentMassPolicy",DropDownStyle=ComboBoxStyle.DropDownList,Width=210};
        private readonly ComboBox visualMember=new ComboBox {Name="VisualParentMember",DropDownStyle=ComboBoxStyle.DropDownList,Width=210,DisplayMember="Label"};
        private readonly NumericUpDown customMass=Number(0,100000,0);
        private readonly CheckBox flipAutoNormal=new CheckBox {Text="Reverse auto-bolt normal",AutoSize=true};
        private readonly NumericUpDown thickness=Number(0,1000,0);
        private readonly List<Control> componentActions=new List<Control>();
        private readonly ComboBox parentAnchor=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Width=220,DisplayMember="Label"};
        private readonly ComboBox childAnchor=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Width=220,DisplayMember="Label"};
        private readonly ComboBox joint=new ComboBox {Name="AttachmentType",DropDownStyle=ComboBoxStyle.DropDownList,Width=225,DisplayMember="Label"};
        private readonly TextBox componentName=new TextBox {Name="ComponentName",Width=180,Text="Component"};
        private readonly TextBox anchorName=new TextBox {Name="AnchorName",Width=150,Text="Mount"};
        private readonly TextBox mountName=new TextBox {Width=130,Text="Fastener"};
        private readonly TextBox releaseSet=new TextBox {Name="FastenerReleaseSet",Width=170};
        private readonly NumericUpDown attachmentLength=Number(1,50,6);
        private readonly NumericUpDown spacing=Number(0,10000,0),alpha=Number(0,10000,0),wrapOffset=Number(0,1000,0);
        private readonly NumericUpDown[] offsets={Number(-10000,10000,0),Number(-10000,10000,0),Number(-10000,10000,0)};
        private readonly NumericUpDown spring=Number(0,100000000,0),damping=Number(0,100000,0),strength=Number(1,10000000,4000);
        private readonly CheckBox visible=new CheckBox {Text="Show component hull",Checked=true,AutoSize=true};
        private readonly Label status=new Label {Name="ComponentStatus",AutoSize=true,Dock=DockStyle.Top};
        private readonly TextBox log=new TextBox {Name="ComponentLog",Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill};
        private readonly ProgressBar progress=new ProgressBar {Dock=DockStyle.Bottom,Visible=false};
        private readonly Panel editor=new Panel {Dock=DockStyle.Fill};
        private readonly Button stop=new Button {Name="StopComponentTask",Text="Stop task",Dock=DockStyle.Bottom,Visible=false};
        private readonly Dictionary<string,HullPreview> previews=new Dictionary<string,HullPreview>();
        private CancellationTokenSource cancel;
        private bool closing;
        private bool refreshingComponents;
        private string batchDetail="";
        private string lastSearch="";
        private ComponentDefinition Selected=>components.SelectedItem as ComponentDefinition;
        private string Worker=>Path.Combine(Path.GetDirectoryName(typeof(ComponentWorkflow).Assembly.Location),"FramePipeline","component_worker.py");
        private sealed class AnchorItem {public string Id;public string Label {get;set;}}

        public ComponentWorkflow(ISldWorks app,ModelDoc2 model):this(app,model,new ExporterSettings(null)){}
        internal ComponentWorkflow(ISldWorks app,ModelDoc2 model,ExporterSettings preferences)
        {
            this.app=app;this.model=model;selection=new FrameSelection(app,model,true);selection.ValidateDocument();
            settings=preferences;project=OpenSelectedProject();
            Text="beamng.cad - Components and mounts";Width=1050;Height=900;MinimumSize=new System.Drawing.Size(850,650);ShowInTaskbar=false;
            template.Items.AddRange(new object[]{"auto","bulk","panel"});template.SelectedIndex=0;
            method.Items.AddRange(new object[]{"auto","alpha_wrap","convex","rigid"});method.SelectedIndex=0;
            surfaceMass.Items.AddRange(new object[]{"Use thickness + SolidWorks material","Exclude surface mass"});surfaceMass.SelectedIndex=0;thickness.Name="SurfaceThickness";
            representation.Items.AddRange(new object[]{"Physical component","Visual only"});massPolicy.Items.AddRange(new object[]{"Use CAD / material mass","Custom mass","Exclude mass"});
            visualParent.SelectedIndexChanged+=(s,e)=>RefreshVisualMembers();
            joint.Items.AddRange(new object[]{new AnchorItem {Id="breakable_fastener",Label="Breakable attachment"},new AnchorItem {Id="fixed",Label="Non-breaking attachment"}});joint.SelectedIndex=0;
            joint.SelectedIndexChanged+=(s,e)=>UpdateAttachmentControls();
            parentAnchor.SelectedIndexChanged+=(s,e)=>UpdateAttachmentControls();
            RefreshRoles(null);
            var tabs=new TabControl {Name="WorkflowPages",Dock=DockStyle.Fill};
            var referencePage=new TabPage("Joints & mounts");
            var partPage=new TabPage("Components");var mountPage=new TabPage("Mounting points");var connectionPage=new TabPage("Connections");
            var mvpPage=new TabPage("Vehicle setup / MVP");var setupStack=Sections();
            var setupButtons=Section(setupStack,"1. Choose the vehicle layout","For your actual vehicle, start by choosing its configuration and assigning CAD groups. The checklist below records what is missing.");
            foreach(var set in mvpCatalog.TemplateSets)
            {
                var choice=new ComboBox {Name="MvpTemplate_"+set.Id,DropDownStyle=ComboBoxStyle.DropDownList,Width=300,DisplayMember="Label"};choice.Items.AddRange(set.Options.Cast<object>().ToArray());
                choice.DropDownWidth=Math.Max(choice.Width,set.Options.Max(o=>TextRenderer.MeasureText(o.Label,Font).Width)+28);
                choice.SelectedItem=mvpCatalog.Selected(project,set);templateChoices.Add(set.Id,choice);Labeled(setupButtons,set.Label,choice);
            }
            Button(setupButtons,"Apply vehicle setup",()=>Run(()=>{if(Selected!=null)SaveParameters();project.MvpTemplates=templateChoices.Select(p=>new MvpTemplateChoice {Category=p.Key,Template=((MvpTemplateOption)p.Value.SelectedItem).Id}).ToList();var imported=!string.IsNullOrEmpty(project.PhysicsTemplateReceipt);if(!imported)mvpCatalog.AddMissingGroups(project);Save();RefreshLists();RefreshRoles(Selected);status.Text=imported?"Layout selected for the guide. This project uses imported physics; start a fresh physical project to generate the new layout and its required groups. Saved assignments are retained.":"Required groups updated. Missing CAD assignments are listed explicitly. Groups outside this setup are retained.";return Task.CompletedTask;}));
            var definitionButtons=Section(setupStack,"2. Review joints and mounts","Use Joints & mounts to bind native CAD mates and reference points, including detachable panel fasteners. Complete the mounting plan before fresh frame calibration. Reviewed template JSON can also supply explicit hardpoints.");
            ReferenceLink(definitionButtons,()=>tabs.SelectedTab=referencePage);
            Button(definitionButtons,"Load template hardpoints",()=>Run(()=>{using(var dialog=new OpenFileDialog {Filter="Vehicle template definition (*.json)|*.json",Title="Choose the reviewed template and mounting definition"})if(dialog.ShowDialog(this)==DialogResult.OK){LoadReviewedDefinition(dialog.FileName);Save();RefreshLists();status.Text="Template definition selected. Its mounting plan must be included in fresh frame calibration.";}return Task.CompletedTask;}));
            var importButtons=Section(setupStack,"Project","Start fresh without importing physics, open saved work, or optionally reuse an existing physics package. A fresh project is saved separately; your current work is kept.");
            importButtons.Controls.Add(templateImport);templateImport.ImportRequested+=()=>Run(ImportPhysicsTemplate);
            templateImport.ResetRequested+=()=>Run(ResetPhysicsTemplate);
            templateImport.FreshRequested+=()=>{if(FreshProjectRequested!=null)FreshProjectRequested();else Run(StartFreshProject);};templateImport.OpenRequested+=()=>Run(OpenProject);
            var working=Section(setupStack,"Working CAD assembly","Keep reference work in a companion assembly. Update after editing source assignments; unchanged parts and sketches stay in place. Changed geometry gets a new part and may need mount repair. Each update opens a new revision and keeps the previous one.");
            working.Controls.Add(companionPanel);companionPanel.CreateRequested+=()=>Run(CreateWorkingAssembly);
            // These commands open/activate their own linked documents. A source
            // window may still be open while the companion is active in CAD.
            companionPanel.UpdateRequested+=()=>Run(UpdateWorkingAssembly,false);companionPanel.OpenRequested+=()=>Run(OpenCompanion,false);
            companionPanel.AppearanceRefreshRequested+=()=>Run(RefreshCompanionAppearances);
            // Keep the reuse/reset entry point visible before the long setup
            // controls and checklist, including at the minimum window size.
            setupStack.SuspendLayout();
            setupStack.SetRow(importButtons.Parent,0);setupStack.SetRow(setupButtons.Parent,1);setupStack.SetRow(definitionButtons.Parent,2);
            setupStack.ResumeLayout(true);
            var setupLayout=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=1,RowCount=2};
            setupLayout.RowStyles.Add(new RowStyle(SizeType.Percent,60));setupLayout.RowStyles.Add(new RowStyle(SizeType.Percent,40));
            var setupScroll=new Panel {Dock=DockStyle.Fill,AutoScroll=true};setupScroll.Controls.Add(setupStack);
            setupLayout.Controls.Add(setupScroll,0,0);setupLayout.Controls.Add(mvpChecklist,0,1);mvpPage.Controls.Add(setupLayout);
            tabs.TabPages.AddRange(new[]{mvpPage,partPage,referencePage});
            var partLayout=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=2,RowCount=1};
            partLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,34));partLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,66));
            var details=new TabControl {Name="ComponentDetails",Dock=DockStyle.Fill};
            var groupColumn=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=1,RowCount=3};
            groupColumn.RowStyles.Add(new RowStyle(SizeType.AutoSize));groupColumn.RowStyles.Add(new RowStyle(SizeType.AutoSize));groupColumn.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            var search=new TableLayoutPanel {Dock=DockStyle.Top,AutoSize=true,ColumnCount=1,Padding=new Padding(3)};
            search.Controls.Add(new Label {AutoSize=true,Text="Find component (name or role)"});search.Controls.Add(componentSearch);search.Controls.Add(componentCount);
            groupColumn.Controls.Add(assignmentInspection,0,0);groupColumn.Controls.Add(search,0,1);groupColumn.Controls.Add(components,0,2);
            partLayout.Controls.Add(groupColumn,0,0);partLayout.Controls.Add(details,1,0);partPage.Controls.Add(partLayout);
            partLayout.Resize+=(s,e)=>
            {
                var narrow=partLayout.ClientSize.Width<760;
                var browserHeight=Math.Min(480,Math.Max(320,partLayout.ClientSize.Height-180));
                ResponsiveLayout.Split(partLayout,groupColumn,details,narrow,browserHeight);
                if(narrow)partLayout.RowStyles[0].Height=browserHeight;
            };

            assignmentInspection.ShowRequested+=()=>Run(ShowAssignedGeometry);
            components.DoubleClick+=(s,e)=>assignmentInspection.ShowCurrent();
            var assignment=DetailPage(details,"CAD assignment");
            var partButtons=Section(assignment,"Assign a physical group","Select a group row and pick CAD bodies or instances. Set to selected replaces its saved geometry; Add to group keeps it and adds your selection. New tagged group saves an empty row. The frame uses the saved definition shown below. Assignments reload after restarting SolidWorks.");
            Button(partButtons,"Moving pieces / split for mates",()=>Run(EditMovingMembers));
            Labeled(partButtons,"Role",mvpRole);Labeled(partButtons,"Name",componentName);
            ReferenceLink(partButtons,()=>{referenceSkeleton.SelectRole((mvpRole.SelectedItem as MvpRole)?.Id);tabs.SelectedTab=referencePage;});
            Button(partButtons,"New tagged group",()=>Run(NewTaggedGroup));
            assignSelection.Click+=(s,e)=>Run(AddComponent);assignComponents.Click+=(s,e)=>Run(()=>AddAssignment(true));
            addToGroup.Click+=(s,e)=>Run(()=>AssignGeometry(false,true));
            partButtons.Controls.Add(assignSelection);partButtons.Controls.Add(addToGroup);partButtons.Controls.Add(assignComponents);
            partButtons.Controls.Add(frameAssignment);
            frameAssignment.DefineRequested+=()=>Run(OpenFrameDefinition);frameAssignment.UseSavedRequested+=()=>Run(AddFrame);
            var ownership=Section(assignment,"Selected group","Faces select their owning body. For the frame, save the frame selection in the frame workflow before using Use saved frame.");

            Button(ownership,"Remove component",()=>Run(()=>{RemoveComponent();return Task.CompletedTask;}));
            var appearance=Section(DetailPage(details,"Appearance"),"Assign the visible mesh","Generation uses the physical CAD by default. A separate appearance assignment overrides its visible mesh. Pending means the saved appearance still needs packaging; it does not change physical mass or ownership.");
            Button(appearance,"Save visual assignment",()=>Run(ReplaceAppearance));
            Button(appearance,"Package saved appearances",()=>Run(PackageAppearances));
            Button(appearance,"Align appearance",()=>Run(AlignAppearance));
            var coiloverPage=DetailPage(details,"Coilover");coiloverPage.Controls.Add(coiloverPanel);
            var movingPieces=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
            Button(movingPieces,"Moving pieces / split for mates",()=>Run(EditMovingMembers));coiloverPage.Controls.Add(movingPieces);
            coiloverPanel.AssignRequested+=()=>Run(()=>{var c=Required();var captured=selection.Capture();var ids=selection.BodyIds(captured);CoiloverAppearance.Assign(c,coiloverPanel.Kind,captured,ids,selection.Document);Save();RefreshLists();status.Text="Coilover piece saved: "+captured.CaptureSummary(ids.Count)+". Complete the three slots, then Package saved appearances.";return Task.CompletedTask;});
            coiloverPanel.ShowRequested+=()=>Run(()=>{var piece=Required().AppearanceCoilover?.Pieces.FirstOrDefault(p=>p.Kind==coiloverPanel.Kind)??throw new InvalidOperationException("Assign this coilover piece first.");if(!ComponentAssignments.SameDocument(piece.SourceDocument,selection.Document))throw new InvalidOperationException("Activate the assembly containing this piece.");selection.Show(CoiloverAppearance.Assignment(piece));model.ViewZoomToSelection();return Task.CompletedTask;});
            coiloverPanel.ClearRequested+=()=>Run(()=>{var c=Required();c.AppearanceCoilover?.Pieces.RemoveAll(p=>p.Kind==coiloverPanel.Kind);CoiloverAppearance.Pending(c);Save();RefreshLists();return Task.CompletedTask;});
            coiloverPanel.MountChanged+=()=>Run(()=>{var c=Required();c.AppearanceCoilover=c.AppearanceCoilover??new CoiloverAppearance();c.AppearanceCoilover.HousingMount=coiloverPanel.HousingMount;CoiloverAppearance.Pending(c);Save();RefreshLists();return Task.CompletedTask;});

            continueTemplate=()=>
            {
                tabs.SelectedTab=partPage;
                details.SelectedTab=details.TabPages.Cast<TabPage>().Single(p=>p.Text=="Appearance");
                if(Selected==null||Selected.Template=="calibrated_frame")
                    components.SelectedItem=project.Components.FirstOrDefault(c=>c.MvpRole=="engine")??project.Components.FirstOrDefault();
                status.Text="Select a group and its CAD bodies, then Save visual assignment. Package saved appearances applies those saved selections to the imported physics.";
            };
            templateImport.ContinueRequested+=()=>continueTemplate();
            var properties=DetailPage(details,"Physical properties");
            var materialButtons=Section(properties,"Surface weight","Solids use native CAD mass and material. For sheets, supply thickness and material, or exclude their mass. An entirely weightless group must follow a physical parent and has no independent collision or breakaway.");
            Labeled(materialButtons,"Surface weight",surfaceMass);Labeled(materialButtons,"Thickness mm",thickness);Labeled(materialButtons,"Visual parent",visualParent);
            Labeled(materialButtons,"Component physics",representation);Labeled(materialButtons,"Mass contribution",massPolicy);Labeled(materialButtons,"Custom mass kg",customMass);Labeled(materialButtons,"Moving parent member",visualMember);
            materialButtons.Controls.Add(new Label {AutoSize=true,MaximumSize=new System.Drawing.Size(700,0),Text="Visual only follows its physical parent: no independent collision, structural response or breakaway. Its mass can still be carried by the parent. Excluded mass always stays labelled."});

            Button(materialButtons,"Accept visual only with excluded mass",()=>Run(AcknowledgeVisualMass));
            materialButtons.Controls.Add(flipAutoNormal);

            var refit=Section(properties,"Refit an existing physical graph","Use this only to apply new CAD mass, centre and inertia to an existing package. Node positions and mounts stay fixed. A frame needs the separate frame calibration workflow.");
            Button(refit,"Recalibrate properties from selection",()=>Run(RecalibrateProperties));
            var hull=DetailPage(details,"Hull preview");
            var hullButtons=Section(hull,"Representation and density","Start with Auto and zero-valued density settings. Preview one group to inspect its collision representation. Suspension physics uses the reviewed parametric template when building a complete vehicle.");
            Labeled(hullButtons,"Representation",template);Labeled(hullButtons,"Bulk method",method);
            Labeled(hullButtons,"Spacing mm (0 auto)",spacing);Labeled(hullButtons,"Alpha mm (0 auto)",alpha);Labeled(hullButtons,"Wrap offset mm",wrapOffset);

            Button(hullButtons,"Estimate from CAD",()=>Run(Suggest));Button(hullButtons,"Generate / preview",()=>Run(Preview));hullButtons.Controls.Add(visible);
            foreach(var panel in new[]{ownership,appearance,materialButtons,refit,hullButtons})
                componentActions.AddRange(panel.Controls.OfType<Button>());
            var mountButtons=Flow();mountButtons.Controls.Add(mountOwner);mountButtons.SetFlowBreak(mountOwner,true);Field(mountButtons,"Mount name",anchorName);
            mountOwner.OwnerChanged+=SelectMountOwner;
            Button(mountButtons,"Add from CAD selection",()=>Run(()=>{CaptureAnchor(false);return Task.CompletedTask;}));
            Button(mountButtons,"Repair selected point",()=>Run(()=>{CaptureAnchor(true);return Task.CompletedTask;}));
            foreach(var pair in offsets.Select((value,index)=>new{value,index}))Field(mountButtons,"Local "+"XYZ"[pair.index]+" offset mm",pair.value);
            Button(mountButtons,"Save offsets",()=>Run(()=>{SaveOffsets();return Task.CompletedTask;}));
            Button(mountButtons,"Refresh CAD points",()=>Run(()=>{ResolveAnchors();Save();RefreshLists();return Task.CompletedTask;}));
            Button(mountButtons,"Remove point",()=>Run(()=>{var a=anchors.SelectedItem as MountAnchor;if(a!=null){project.Anchors.Remove(a);project.Connections.RemoveAll(c=>c.AnchorA==a.Id||c.AnchorB==a.Id);Save();RefreshLists();}return Task.CompletedTask;}));
            mountButtons.Controls.Add(new Label {Name="MountPointHelp",AutoSize=true,MaximumSize=new System.Drawing.Size(850,0),Text="Choose the component above (type its name to jump to it), then pick a CAD vertex, reference point, 3D sketch point, circular edge, or two points for a midpoint. The list shows that component's mounting points. Assembly datum points belong to the group you choose here. Offsets follow the CAD component axes, or assembly axes for assembly datums. Points save locations; they do not create joints by themselves."});
            Layout(mountPage,mountButtons,anchors);
            var connectionButtons=Flow();Field(connectionButtons,"Name",mountName);Field(connectionButtons,"From",parentAnchor);Field(connectionButtons,"To",childAnchor);Field(connectionButtons,"Attachment",joint);
            Field(connectionButtons,"Spring N/m (0 auto)",spring);Field(connectionButtons,"Damping N s/m (0 auto)",damping);Field(connectionButtons,"Failure N per beam",strength);
            Field(connectionButtons,"Release together set (empty = independent)",releaseSet);Field(connectionButtons,"Short link mm (authored vehicle)",attachmentLength);
            connectionButtons.Controls.Add(new Label {AutoSize=true,MaximumSize=new System.Drawing.Size(480,0),Text="Short-link length applies to breakable frame mounts and mounts between other parts."});
            Button(connectionButtons,"Add connection",()=>Run(()=>{AddConnection();return Task.CompletedTask;}));
            Button(connectionButtons,"Update connection",()=>Run(()=>{UpdateConnection();return Task.CompletedTask;}));
            Button(connectionButtons,"Remove connection",()=>Run(()=>{if(connections.SelectedItem is MountConnection value){project.Connections.Remove(value);Save();RefreshLists();}return Task.CompletedTask;}));
            Button(connectionButtons,"Verify packaged attachments",()=>Run(VerifyAttachments));
            connectionButtons.Controls.Add(new Label {Name="ConnectionScopeHelp",AutoSize=true,MaximumSize=new System.Drawing.Size(850,0),Text="From is the parent; To is the panel/accessory. Capture matching CAD locations for each fastener. Independent fasteners let a panel hang from surviving mounts. The same release-set name on one panel releases those fasteners together; other panels stay independent. Use separated mounting sites to hold the assembled part.\r\nThe panel retains its own mesh, nodes and collision triangles after detachment. Failure is separate from joint motion. Breaking thresholds are per connector beam; actual fastener pull/shear loads require testing."});
            ReferenceLink(connectionButtons,()=>{referenceSkeleton.SelectRole(Selected?.MvpRole);tabs.SelectedTab=referencePage;});
            Layout(connectionPage,connectionButtons,connections);
            jointsPanel=new JointWorkspacePanel(referenceSkeleton,mountPage,connectionPage);referencePage.Controls.Add(jointsPanel);
            jointsPanel.ModeChanged+=value=>Run(()=>{project.JointWorkspace.Mode=value;Save();RefreshLists();return Task.CompletedTask;});
            jointsPanel.ParametersRequested+=()=>Run(()=>{using(var editor=new JointParametersPanel(project.JointWorkspace.Parameters))if(editor.ShowDialog(this)==DialogResult.OK){project.JointWorkspace.Parameters=editor.Values;Save();}return Task.CompletedTask;});
            jointsPanel.ScanRequested+=()=>Run(ScanJoints);
            jointsPanel.AutoConnectRequested+=()=>Run(AutoConnect);
            jointsPanel.NativeMateRequested+=()=>Run(()=>{PrepareNativeMate();return Task.CompletedTask;});
            jointsPanel.CaptureRequested+=request=>Run(()=>{CaptureJointPoint(request);return Task.CompletedTask;});
            jointsPanel.BindJointRequested+=request=>Run(()=>{BindJointCenter(request);return Task.CompletedTask;});
            jointsPanel.ApproveRequested+=id=>Run(()=>{ApproveJoint(id);return Task.CompletedTask;});
            jointsPanel.PositioningRequested+=id=>Run(async()=>{var value=project.JointWorkspace.Joints.Single(j=>j.Id==id);foreach(var mate in project.JointWorkspace.Mates.Where(m=>value.MateIds.Contains(m.Id)))mate.PositioningOnly=value.Status!="positioning_only";await ScanJoints();});
            jointsPanel.ValidateRequested+=()=>Run(async()=>{var output=NewFolder("joint-definition")+".json";await WorkerRun("joint-definition",output);status.Text="Reviewed definition is complete: "+output;});
            jointsPanel.OwnerSelected+=id=>{var item=project.Components.FirstOrDefault(c=>c.Id==id);if(item!=null)components.SelectedItem=item;};
            jointsPanel.HighlightRequested+=id=>Run(()=>{HighlightJoint(id);return Task.CompletedTask;});
            jointsPanel.MembersRequested+=()=>Run(EditMovingMembers);
            InitializeDriveline(tabs);
            var buildPage=new TabPage("Build");var buildStack=Sections();buildPage.AutoScroll=true;buildPage.Controls.Add(buildStack);tabs.TabPages.Add(buildPage);
            var refresh=Section(buildStack,"1. Export current CAD","For the first real-data pass, refresh the tagged groups and inspect the checklist. Fix missing roles, duplicate ownership and material inputs before building.");
            Button(refresh,"Refresh tagged CAD",()=>Run(RefreshTaggedCad));
            var generation=Section(buildStack,"2. Generate a fresh package","Load reviewed real hardpoints, then prepare, calibrate and package the frame with that mounting plan. This step refreshes physical CAD and builds the full vehicle.");
            Button(generation,"Regenerate physics / package",()=>Run(Build));
            Button(generation,"Package saved appearances",()=>Run(PackageAppearances));
            var verifyPage=new TabPage("Verify") {AutoScroll=true};var verifyStack=Sections();verifyPage.Controls.Add(verifyStack);tabs.TabPages.Add(verifyPage);
            var verification=Section(verifyStack,"Review the generated package","Verify package runs the full 24-scenario vehicle suite and stops on failure. Use the recorded results and captures to review the build before installing.");
            Button(verification,"Verify package",()=>Run(Verify));
            Button(verification,"Manage project mod",()=>Run(()=>{if(NavigationRequested!=null)NavigationRequested("Delivery");else new ModManager(settings.Reload(),null,VehicleProject.Load(project.FilePath)) {SolidWorksApplication=app}.Show(this);return Task.CompletedTask;}));
            var logPage=new TabPage("Log");logPage.Controls.Add(log);tabs.TabPages.Add(logPage);
            editor.Controls.Add(tabs);Controls.Add(editor);Controls.Add(progress);Controls.Add(status);Controls.Add(activeProject);
            status.Padding=new Padding(8);SizeChanged+=(s,e)=>status.MaximumSize=new System.Drawing.Size(Math.Max(200,ClientSize.Width-16),0);
            stop.Click+=(s,e)=>cancel?.Cancel();Controls.Add(stop);
            components.SelectedIndexChanged+=(s,e)=>ComponentSelectionChanged();anchors.SelectedIndexChanged+=(s,e)=>{if(anchors.SelectedItem is MountAnchor a){anchorName.Text=a.Name;for(var i=0;i<3;i++)offsets[i].Value=Clamp(offsets[i],a.Offset[i]*1000);}};
            componentSearch.TextChanged+=(s,e)=>{if(!refreshingComponents){if(ResolveDraft())RefreshComponentList();else {refreshingComponents=true;componentSearch.Text=lastSearch;refreshingComponents=false;}}lastSearch=componentSearch.Text;};
            componentSearch.KeyDown+=(s,e)=>{if(e.KeyCode==Keys.Escape){componentSearch.Clear();e.SuppressKeyPress=true;}};
            KeyPreview=true;KeyDown+=(s,e)=>{if(e.Control&&e.KeyCode==Keys.F){tabs.SelectedTab=partPage;componentSearch.Focus();componentSearch.SelectAll();e.SuppressKeyPress=true;}};
            mvpRole.SelectedIndexChanged+=(s,e)=>{referenceSkeleton.SelectRole((mvpRole.SelectedItem as MvpRole)?.Id);UpdateFrameActions();};
            connections.SelectedIndexChanged+=(s,e)=>{if(connections.SelectedItem is MountConnection c){mountName.Text=c.Name;spring.Value=Clamp(spring,c.Spring);damping.Value=Clamp(damping,c.Damping);strength.Value=Clamp(strength,c.Strength);releaseSet.Text=c.ReleaseSet??"";attachmentLength.Value=Clamp(attachmentLength,(c.AttachmentLength>0?c.AttachmentLength:.006)*1000);joint.SelectedItem=joint.Items.Cast<AnchorItem>().FirstOrDefault(a=>a.Id==c.Template);parentAnchor.SelectedItem=parentAnchor.Items.Cast<AnchorItem>().FirstOrDefault(a=>a.Id==c.AnchorA);childAnchor.SelectedItem=childAnchor.Items.Cast<AnchorItem>().FirstOrDefault(a=>a.Id==c.AnchorB);}};
            visible.CheckedChanged+=(s,e)=>{if(cancel==null)Run(async()=>{foreach(var item in previews)await item.Value.SetVisibleAsync(visible.Checked && item.Key==Selected?.Id);});};
            FormClosing+=(s,e)=>{if(cancel!=null){e.Cancel=true;closing=true;cancel.Cancel();}else if(!ResolveDraft())e.Cancel=true;};
            FormClosed+=(s,e)=>{foreach(var preview in previews.Values)preview.Dispose();};
            Activated+=(s,e)=>{if(cancel==null){RefreshFrameDefinition();RefreshCompanion();}};
            RefreshFrameDefinition();RefreshLists();InitializeDrafts();status.Text="Project package: "+project.Identity.Namespace+".zip";
        }
        private static NumericUpDown Number(decimal min,decimal max,decimal value)=>new NumericUpDown {Minimum=min,Maximum=max,Value=value,DecimalPlaces=2,Width=100};
        private static decimal Clamp(NumericUpDown field,double value)=>Math.Max(field.Minimum,Math.Min(field.Maximum,(decimal)value));
        private static FlowLayoutPanel Flow()=>new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Top,WrapContents=true};
        private static void Field(Control root,string name,Control value)
        {
            // Keep each label with its control when the window wraps to another row.
            var pair=new FlowLayoutPanel {AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,WrapContents=false,Margin=new Padding(0)};
            pair.Controls.Add(new Label {Text=name,AutoSize=true,Margin=new Padding(4,7,2,2)});pair.Controls.Add(value);root.Controls.Add(pair);
        }
        private static void Button(Control root,string name,Action action){var b=new Button {Text=name,AutoSize=true};b.Click+=(s,e)=>action();root.Controls.Add(b);}
        private static void ReferenceLink(Control root,Action action){var link=new LinkLabel {Text="Locate on reference skeleton",AutoSize=true,Margin=new Padding(3,8,3,8)};link.LinkClicked+=(s,e)=>action();root.Controls.Add(link);}
        private new static void Layout(TabPage page,Control top,Control body){page.Controls.Add(body);page.Controls.Add(top);}
        private static TableLayoutPanel Sections(){var table=new TableLayoutPanel {Dock=DockStyle.Top,AutoSize=true,ColumnCount=1,Padding=new Padding(10)};table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));return table;}
        private static TableLayoutPanel DetailPage(TabControl tabs,string title)
        {
            var page=new TabPage(title) {AutoScroll=true};var stack=Sections();page.Controls.Add(stack);tabs.TabPages.Add(page);return stack;
        }
        private static FlowLayoutPanel Section(TableLayoutPanel stack,string title,string description)
        {
            var group=new GroupBox {Text=title,AutoSize=true,Dock=DockStyle.Fill,Padding=new Padding(10),Margin=new Padding(0,0,0,12)};
            var body=Flow();body.FlowDirection=FlowDirection.TopDown;body.WrapContents=false;
            body.Controls.Add(new Label {Text=description,AutoSize=true,MaximumSize=new System.Drawing.Size(460,0),Margin=new Padding(3,4,3,12)});
            ResponsiveLayout.FlowSection(group,body);
            group.Controls.Add(body);stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));stack.Controls.Add(group,0,stack.RowCount++);return body;
        }
        private static void Labeled(Control parent,string title,Control value)
        {
            var row=new FlowLayoutPanel {AutoSize=true,WrapContents=false,Margin=new Padding(0,3,0,3)};
            row.Controls.Add(new Label {Text=title,Width=150,Height=24,TextAlign=System.Drawing.ContentAlignment.MiddleLeft});row.Controls.Add(value);parent.Controls.Add(row);
        }
        private ComponentDefinition Required()=>Selected??throw new InvalidOperationException("Assign CAD geometry first, then select its entry in the Components list.");
        private FrameAssignment Assignment(ComponentDefinition c)=>new FrameAssignment {Id=c.Id,Role=c.Template,Configuration=c.Configuration,Selections=c.Selections,Hull=c.Hull};
        private Task ShowAssignedGeometry()
        {
            var component=Required();var appearance=assignmentInspection.Appearance;
            var assignment=AssignmentInspection.Capture(component,appearance);
            AssignmentInspection.CheckDocument(component,appearance,selection.Document);
            if(assignment.Configuration!=selection.Configuration)
                throw new InvalidOperationException("Activate SolidWorks configuration '"+assignment.Configuration+"' to inspect this saved assignment.");
            selection.Show(assignment);
            if(assignmentInspection.Zoom)model.ViewZoomToSelection();
            model.GraphicsRedraw2();
            status.Text="Highlighted "+component.Name+" — "+(appearance?"appearance CAD":"physical CAD")+" ("+assignment.Selections.Count+" saved selections).";
            log.AppendText(status.Text+Environment.NewLine+string.Join(Environment.NewLine,assignment.Selections.Select(s=>s.Name))+Environment.NewLine);
            return Task.CompletedTask;
        }
        private string NewFolder(string prefix)=>Path.Combine(BuildStorage.EnsureDirectory(settings.FrameOutput),prefix+"-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,8));
        private void Save()
        {
            // Preserve packaging/profile changes made by a modeless manager.
            var latest=VehicleProject.Load(project.FilePath);project.LastBuildReceipt=latest.LastBuildReceipt;project.FrameBuildReceipt=latest.FrameBuildReceipt;project.Save();ProjectChanged?.Invoke();
        }
        private void RefreshLists()
        {
            drivelinePanel.Configure(project);
            UpdateAttachmentControls();
            activeProject.Text=project.Components.Count+" groups | Project: "+project.FilePath;
            Text="beamng.cad - "+Path.GetFileName(project.SourceDocument)+" - Components and mounts";
            ComponentAssignments.UpdateStatus(project);
            mountOwner.SetComponents(project.Components,Selected?.Id);
            RefreshComponentList();
            var choices=project.Anchors.Select(a=>new AnchorItem {Id=a.Id,Label=(project.Components.FirstOrDefault(c=>c.Id==a.ComponentId)?.Name??"Missing owner")+": "+a.Name+" ["+a.Status+"]"}).ToArray();
            parentAnchor.DataSource=choices;childAnchor.DataSource=choices.ToArray();
            // Bind endpoints before loading the selected connection; replacing
            // the choice lists afterwards used to reset both ends to the first point.
            var selectedConnection=(connections.SelectedItem as MountConnection)?.Id;
            connections.DataSource=null;connections.DisplayMember="Label";connections.DataSource=project.Connections.ToList();
            connections.SelectedItem=project.Connections.FirstOrDefault(c=>c.Id==selectedConnection)??project.Connections.FirstOrDefault();
            mvpChecklist.Text=mvpCatalog.Checklist(project);
            templateImport.SetState(project.Components.Count,project.PhysicsTemplateReceipt);
            referenceSkeleton.Configure(mvpCatalog,project);
            jointsPanel?.Configure(mvpCatalog,project);
            if(Selected!=null)referenceSkeleton.SelectRole(Selected.MvpRole);
            RefreshCompanion();
        }
        private void RefreshCompanion()
        {
            try {var path=CompanionAssemblyLink.Find(project);companionPanel.SetState(path!=null,CompanionAssemblyLink.Status(project,path));}
            catch(Exception e){companionPanel.SetState(false,"Companion link needs attention: "+e.Message);}
        }
        private void RefreshComponentList()
        {
            // Binding briefly selects null/the first row. Inspect only the final selection.
            var selected=Selected?.Id;refreshingComponents=true;
            try {components.ShowComponents(project.Components,componentSearch.Text,selected);}
            finally {refreshingComponents=false;}
            componentCount.Text=components.Items.Count+" of "+project.Components.Count+" groups"+(components.Items.Count==0?" - no matches":"");
            LoadParameters();
        }
        private Task NewTaggedGroup()
        {
            // Preserve an entered name without copying the untouched name of
            // whichever existing group happens to be selected.
            ComponentDefinition created;
            using(var dialog=new Form {Text="New CAD group",Width=480,Height=230,StartPosition=FormStartPosition.CenterParent})
            {
                var fields=new FlowLayoutPanel {Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown,WrapContents=false,Padding=new Padding(12)};
                var role=new ComboBox {Name="NewGroupRole",DropDownStyle=ComboBoxStyle.DropDownList,Width=400,DisplayMember="Label"};
                role.Items.AddRange(new[]{new MvpRole {Id="",Label="Unassigned role",Representation="auto"}}.Concat(mvpCatalog.ActiveRoles(project)).Cast<object>().ToArray());role.SelectedIndex=0;
                var name=new TextBox {Name="NewGroupName",Width=400,Text="New component"};
                fields.Controls.Add(new Label {Text="Choose this new group's role and name.",AutoSize=true});fields.Controls.Add(role);fields.Controls.Add(name);
                var add=new Button {Text="Create empty group",DialogResult=DialogResult.OK,AutoSize=true};fields.Controls.Add(add);dialog.Controls.Add(fields);dialog.AcceptButton=add;
                if(dialog.ShowDialog(this)!=DialogResult.OK)return Task.CompletedTask;
                created=ComponentAssignments.CreateNamedGroup(project,(MvpRole)role.SelectedItem,name.Text);
            }
            Save();refreshingComponents=true;
            try {componentSearch.Clear();} finally {refreshingComponents=false;}
            RefreshLists();components.SelectedItem=created;componentName.Focus();componentName.SelectAll();
            status.Text="New empty group saved. Choose its role and name, pick its CAD bodies, then Set to selected. Remove component discards an unwanted empty group.";
            return Task.CompletedTask;
        }
        private void LoadParameters()
        {
            loadingDraft=true;
            try {
            mountOwner.SelectOwner(Selected?.Id);RefreshMountAnchors();
            UpdateFrameActions();
            assignmentInspection.PreferAppearance=!string.IsNullOrEmpty(project.PhysicsTemplateReceipt) &&
                (Selected==null || ComponentAssignments.State(project,Selected,false)!="saved");
            assignmentInspection.SetComponent(Selected);
            coiloverPanel.SetComponent(Selected);
            var c=Selected;draftOwner=c;foreach(var action in componentActions)action.Enabled=c!=null;if(c==null)return;componentName.Text=c.Name;componentName.Modified=false;template.SelectedItem=c.Template;method.SelectedItem=c.Method;
            RefreshRoles(c);
            spacing.Value=Clamp(spacing,c.Spacing*1000);alpha.Value=Clamp(alpha,c.Alpha*1000);wrapOffset.Value=Clamp(wrapOffset,c.WrapOffset*1000);
            thickness.Value=Clamp(thickness,c.Thickness*1000);surfaceMass.SelectedIndex=c.SurfaceMassMode=="ignore"?1:0;
            visualParent.DataSource=new[]{new AnchorItem {Id="",Label="Choose a physical component"}}.Concat(project.Components.Where(p=>p.Id!=c.Id).Select(p=>new AnchorItem {Id=p.Id,Label=p.Name})).ToList();
            visualParent.SelectedItem=visualParent.Items.Cast<AnchorItem>().FirstOrDefault(p=>p.Id==c.VisualParentId)??visualParent.Items[0];
            representation.SelectedIndex=c.Representation=="visual_only"?1:0;massPolicy.SelectedIndex=c.MassPolicy=="custom"?1:c.MassPolicy=="exclude"?2:0;customMass.Value=Clamp(customMass,c.CustomMassKg);RefreshVisualMembers();
            flipAutoNormal.Checked=c.AutoConnectNormalFlip;
            if(cancel==null && previews.Count>0)Run(async()=>{foreach(var item in previews)await item.Value.SetVisibleAsync(visible.Checked&&item.Key==c.Id);});
            } finally {loadingDraft=false;draftBaseline=DraftKey();UpdateDraftState();}
        }
        private void RefreshRoles(ComponentDefinition component)
        {
            var roles=mvpCatalog.ActiveRoles(project);var old=mvpCatalog.Roles.FirstOrDefault(r=>r.Id==component?.MvpRole);
            if(old!=null&&!roles.Any(r=>r.Id==old.Id))roles.Add(old);
            mvpRole.Items.Clear();mvpRole.Items.AddRange(new[]{new MvpRole {Id="",Label="Unassigned role",Representation="auto"}}.Concat(roles).Cast<object>().ToArray());
            mvpRole.SelectedItem=mvpRole.Items.Cast<MvpRole>().FirstOrDefault(r=>r.Id==component?.MvpRole)??mvpRole.Items[0];
        }
        private void SaveParameters()
        {
            var c=draftOwner??Required();var nextName=componentName.Text.Trim();if(nextName.Length==0)throw new InvalidOperationException("Name the component.");c.Name=nextName;
            c.MvpRole=c.Template=="calibrated_frame"?"frame":(mvpRole.SelectedItem as MvpRole)?.Id??"";
            if(c.Template!="calibrated_frame"){c.Template=(string)template.SelectedItem??"auto";c.Method=(string)method.SelectedItem??"auto";c.Spacing=(double)spacing.Value/1000;c.Alpha=(double)alpha.Value/1000;c.WrapOffset=(double)wrapOffset.Value/1000;}
            c.Thickness=(double)thickness.Value/1000;c.SurfaceMassMode=surfaceMass.SelectedIndex==1?"ignore":"thickness";c.VisualParentId=(visualParent.SelectedItem as AnchorItem)?.Id??"";
            c.Representation=representation.SelectedIndex==1?"visual_only":"physical";c.MassPolicy=massPolicy.SelectedIndex==1?"custom":massPolicy.SelectedIndex==2?"exclude":"cad";c.CustomMassKg=(double)customMass.Value;c.VisualParentMemberId=(visualMember.SelectedItem as AnchorItem)?.Id??"";
            c.AutoConnectNormalFlip=flipAutoNormal.Checked;
            if(CoiloverAppearance.Supported(c))c.CoiloverSpring=coiloverPanel.SpringSettings;
            Save();RefreshLists();
        }
        private Task AddComponent()=>AddAssignment(false);
        private Task AddAssignment(bool wholeComponents)=>AssignGeometry(wholeComponents,false);
        private Task AssignGeometry(bool wholeComponents,bool append)
        {
            var component=Selected??new ComponentDefinition();
            var role=(mvpRole.SelectedItem as MvpRole)?.Id??"";
            if(component.Template=="calibrated_frame"||role=="frame")throw new InvalidOperationException("Frame assignment uses Define / edit frame > Use current selection, then Use saved frame here. The definition and project assignment persist between restarts.");
            var captured=wholeComponents?selection.CaptureOwningComponents():selection.Capture();
            if(append)captured=ComponentAssignments.CombinedPhysical(component,captured,selection.Document);
            var ids=selection.BodyIds(captured);
            ComponentAssignments.Physical(project,component,captured,ids,selection.Document);
            component.Name=componentName.Text.Trim();component.Template=(string)template.SelectedItem??"auto";component.Method=(string)method.SelectedItem??"auto";
            component.Spacing=(double)spacing.Value/1000;component.Alpha=(double)alpha.Value/1000;component.WrapOffset=(double)wrapOffset.Value/1000;
            component.Thickness=(double)thickness.Value/1000;component.SurfaceMassMode=surfaceMass.SelectedIndex==1?"ignore":"thickness";component.VisualParentId=(visualParent.SelectedItem as AnchorItem)?.Id??"";
            component.Representation=representation.SelectedIndex==1?"visual_only":"physical";component.MassPolicy=massPolicy.SelectedIndex==1?"custom":massPolicy.SelectedIndex==2?"exclude":"cad";
            component.CustomMassKg=(double)customMass.Value;component.VisualParentMemberId=(visualMember.SelectedItem as AnchorItem)?.Id??"";component.AutoConnectNormalFlip=flipAutoNormal.Checked;
            if(component.Name.Length==0)component.Name="Component "+(project.Components.Count+1);
            component.MvpRole=role;
            if(!project.Components.Contains(component))project.Components.Add(component);
            Save();RefreshLists();components.SelectedItem=component;assignmentInspection.Appearance=false;
            status.Text="CAD assignment saved: "+component.Name+" ("+(append?ids.Count+" unique bodies in group":captured.CaptureSummary(ids.Count))+"). Use Show in SolidWorks to inspect it. Refresh tagged CAD exports it when needed.";
            return Task.CompletedTask;
        }
        private Task AddFrame()
        {
            var saved=PreparationFile.Load(selection.Document).Frame(selection.Configuration);
            if(saved==null)throw new InvalidOperationException("Define the frame selection in the Frame workflow first.");
            var c=project.Components.SingleOrDefault(item=>item.Template=="calibrated_frame")??new ComponentDefinition {Id=saved.Id,Name="Calibrated frame",Template="calibrated_frame"};
            var ids=selection.BodyIds(saved);ComponentAssignments.Physical(project,c,saved,ids,selection.Document);c.Hull=saved.Hull;
            c.MvpRole="frame";
            if(!project.Components.Contains(c))project.Components.Add(c);Save();RefreshLists();components.SelectedItem=c;assignmentInspection.Appearance=false;
            RefreshFrameDefinition();status.Text="Frame CAD assignment saved in this project; it will reload after restarting SolidWorks. Fresh calibration is required before a physical package is generated.";return Task.CompletedTask;
        }
        private void RefreshFrameDefinition()
        {
            savedFrame=null;savedFrameError=null;otherFrameConfigurations=Array.Empty<string>();
            try
            {
                var definition=PreparationFile.Load(selection.Document);savedFrame=definition.Frame(selection.Configuration);
                otherFrameConfigurations=definition.Assignments.Where(a=>a.Role=="frame"&&a.Configuration!=selection.Configuration).Select(a=>a.Configuration).Distinct().ToArray();
            }
            catch(Exception e){savedFrameError=e.Message;}
            UpdateFrameActions();
        }
        private void UpdateFrameActions()
        {
            var isFrame=Selected?.Template=="calibrated_frame" || (mvpRole.SelectedItem as MvpRole)?.Id=="frame";
            assignSelection.Enabled=Selected!=null&&!isFrame;addToGroup.Enabled=Selected!=null&&!isFrame;assignComponents.Enabled=Selected!=null&&!isFrame;
            var component=project.Components.FirstOrDefault(c=>c.Template=="calibrated_frame");
            var state=component==null?"missing":ComponentAssignments.State(project,component,false);
            if(state=="saved"&&component.Configuration!=selection.Configuration)state="saved for configuration '"+component.Configuration+"'";
            frameAssignment.SetState(isFrame,selection.Configuration,savedFrame,state,otherFrameConfigurations,savedFrameError);
        }
        private Task OpenFrameDefinition()
        {
            if(NavigationRequested!=null){BeginInvoke(new Action(()=>NavigationRequested("Frame")));return Task.CompletedTask;}
            var existing=System.Windows.Forms.Application.OpenForms.OfType<FrameWorkflow>().FirstOrDefault(f=>f.IsForDocument(selection.Document));
            if(existing!=null){existing.Activate();return Task.CompletedTask;}
            new FrameWorkflow(app,model).Show(this);return Task.CompletedTask;
        }
        private void RemoveComponent()
        {
            var c=Required();var ids=project.Anchors.Where(a=>a.ComponentId==c.Id).Select(a=>a.Id).ToArray();
            project.Connections.RemoveAll(m=>ids.Contains(m.AnchorA)||ids.Contains(m.AnchorB));project.Anchors.RemoveAll(a=>a.ComponentId==c.Id);project.Components.Remove(c);
            if(previews.TryGetValue(c.Id,out var preview)){preview.Dispose();previews.Remove(c.Id);}Save();RefreshLists();
        }
        private async Task Export(ComponentDefinition c)
        {
            if(c.Configuration!=selection.Configuration)throw new InvalidOperationException("Activate the component's saved configuration before exporting.");
            var path=NewFolder("component-cad");var geometry=await selection.ExportAsync(Assignment(c),path,cancel.Token);
            var actual=geometry.Meshes.Select(m=>m.Id).OrderBy(v=>v).ToArray();
            if(!actual.SequenceEqual(c.BodyIds.OrderBy(v=>v)))throw new InvalidOperationException("Component body ownership changed. Replace its assignment.");
            c.GeometryDirectory=path;
            foreach(var member in project.JointWorkspace.Members.Where(m=>m.ComponentId==c.Id))
            {
                var memberPath=NewFolder("member-cad");
                var memberGeometry=await selection.ExportAsync(new FrameAssignment {Id=member.Id,Configuration=c.Configuration,Selections=member.Selections},memberPath,cancel.Token);
                if(!memberGeometry.Meshes.Select(m=>m.Id).OrderBy(id=>id).SequenceEqual(member.BodyIds.OrderBy(id=>id)))throw new InvalidOperationException(member.Name+": moving-member ownership changed. Reclassify its bodies.");
                member.GeometryDirectory=memberPath;
            }
        }
        private void ResolveAnchors()
        {
            var service=new MountAnchors(app,model);var errors=new List<string>();
            foreach(var a in project.Anchors)try{service.Update(a);}catch(Exception e){errors.Add(a.Name+": "+e.Message);}
            Save();if(errors.Count>0)throw new InvalidOperationException(string.Join(Environment.NewLine,errors));
        }
        private void SelectMountOwner(ComponentDefinition component)
        {
            if(component==null)return;
            refreshingComponents=true;
            try
            {
                if(!components.Items.Contains(component))componentSearch.Clear();
                components.ShowComponents(project.Components,componentSearch.Text,component.Id);
            }
            finally {refreshingComponents=false;}
            componentCount.Text=components.Items.Count+" of "+project.Components.Count+" groups";
            LoadParameters();
        }
        private void RefreshMountAnchors()
        {
            var previous=(anchors.SelectedItem as MountAnchor)?.Id;
            var points=project.Anchors.Where(a=>a.ComponentId==Selected?.Id).ToList();
            anchors.DataSource=null;anchors.DisplayMember="Label";anchors.DataSource=points;
            anchors.SelectedItem=points.FirstOrDefault(a=>a.Id==previous)??points.FirstOrDefault();
        }
        private void CaptureAnchor(bool repair)
        {
            var selected=repair?anchors.SelectedItem as MountAnchor:null;
            if(repair&&selected==null)throw new InvalidOperationException("Select the mounting point to repair.");
            var owner=repair?project.Components.Single(c=>c.Id==selected.ComponentId):Required();
            var replacement=new MountAnchors(app,model).Capture(owner,anchorName.Text.Trim());
            if(repair){replacement.Id=selected.Id;replacement.Offset=selected.Offset;new MountAnchors(app,model).Update(replacement);project.Anchors.Remove(selected);}
            project.Anchors.Add(replacement);Save();RefreshLists();anchors.SelectedItem=replacement;
        }
        private void SaveOffsets()
        {
            var a=anchors.SelectedItem as MountAnchor??throw new InvalidOperationException("Select a mounting point.");
            a.Name=anchorName.Text.Trim();a.Offset=offsets.Select(v=>(double)v.Value/1000).ToArray();new MountAnchors(app,model).Update(a);
            foreach(var connection in project.Connections.Where(c=>c.AnchorA==a.Id||c.AnchorB==a.Id))connection.UserEdited=true;Save();
            status.Text="Mount resolved in BeamNG metres: "+string.Join(", ",a.Position.Select(v=>v.ToString("F4",CultureInfo.InvariantCulture)));RefreshLists();
        }
        private MountConnection EditedConnection(MountConnection previous=null)
        {
            var a=(parentAnchor.SelectedItem as AnchorItem)?.Id;var b=(childAnchor.SelectedItem as AnchorItem)?.Id;
            if(a==null||b==null||project.Anchors.Single(p=>p.Id==a).ComponentId==project.Anchors.Single(p=>p.Id==b).ComponentId)throw new InvalidOperationException("Choose mounting points on two different components.");
            return new MountConnection {Id=previous?.Id??Guid.NewGuid().ToString("N"),Name=mountName.Text.Trim(),AnchorA=a,AnchorB=b,Template=(joint.SelectedItem as AnchorItem)?.Id??throw new InvalidOperationException("Choose an attachment type."),Spring=(double)spring.Value,Damping=(double)damping.Value,Strength=(double)strength.Value,ReleaseSet=releaseSet.Text.Trim(),AttachmentLength=(double)attachmentLength.Value/1000};
        }
        private void UpdateAttachmentControls()
        {
            var breaking=(joint.SelectedItem as AnchorItem)?.Id=="breakable_fastener";
            strength.Enabled=breaking;
            var anchor=project.Anchors.FirstOrDefault(a=>a.Id==(parentAnchor.SelectedItem as AnchorItem)?.Id);
            var owner=project.Components.FirstOrDefault(c=>c.Id==anchor?.ComponentId);
            var permanentFrame=!breaking&&(owner?.MvpRole=="frame"||owner?.Template=="calibrated_frame");
            attachmentLength.Enabled=project.JointWorkspace.Mode=="authored"&&!permanentFrame;
        }
        private void AddConnection(){project.Connections.Add(EditedConnection());Save();RefreshLists();}
        private void UpdateConnection(){var old=connections.SelectedItem as MountConnection??throw new InvalidOperationException("Select a connection.");var edited=EditedConnection(old);edited.GeneratedSource=old.GeneratedSource;edited.GeneratedKey=old.GeneratedKey;edited.GeneratedHash=old.GeneratedHash;edited.SupportPosition=old.SupportPosition;edited.Normal=old.Normal;edited.UserEdited=true;project.Connections[project.Connections.IndexOf(old)]=edited;Save();RefreshLists();}
        private async Task WorkerRun(string action,string output,string component=null)
        {
            var snapshot=Path.Combine(BuildStorage.EnsureDirectory(settings.FrameOutput),"project-job-"+Guid.NewGuid().ToString("N")+".json");JsonFile.Write(snapshot,project);
            try{await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Worker,action+" --project "+OwnedWorker.Quote(snapshot)+" --source-project "+OwnedWorker.Quote(project.FilePath)+" --output "+OwnedWorker.Quote(output)+(component==null?"":" --component "+OwnedWorker.Quote(component))+" --cgal "+OwnedWorker.Quote(settings.CgalPythonExecutable)+(settings.SaveBuildReports=="true"?" --save-report":""),new Progress<string>(Report),cancel.Token,null,settings.FrameOutput);}
            finally{File.Delete(snapshot);}
        }
        private void Report(string value)
        {
            if(IsDisposed)return;
            if(value.StartsWith("CAD_PROGRESS "))
            {
                if(cancel==null)return;
                var data=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(value.Substring(13));
                if((string)data["phase"]=="Test batch")batchDetail=Convert.ToString(data["detail"]);
                status.Text=(string)data["phase"]+(batchDetail.Length==0?"":" | "+batchDetail);
                if(data.ContainsKey("completed")&&data["completed"]!=null&&data.ContainsKey("total")&&data["total"]!=null){progress.Style=ProgressBarStyle.Continuous;progress.Value=Math.Max(0,Math.Min(100,(int)(100*Convert.ToDouble(data["completed"])/Math.Max(1,Convert.ToDouble(data["total"])))));}
                else progress.Style=ProgressBarStyle.Marquee;
            }
            else log.AppendText(value+Environment.NewLine);
        }
        private async Task Suggest()
        {
            var c=Required();if(c.Template=="calibrated_frame")throw new InvalidOperationException("Use the frame workflow for its calibrated representation.");
            SaveParameters();
            await Export(c);Save();var path=NewFolder("component-estimate")+".json";await WorkerRun("suggest",path,c.Id);
            log.AppendText(File.ReadAllText(path)+Environment.NewLine);status.Text="Geometry estimates are shown in the log. Zero-valued parameters use these estimates automatically.";
        }
        private async Task Preview()
        {
            var c=Required();if(c.Template=="calibrated_frame")throw new InvalidOperationException("Use the frame workflow to preview its calibrated hull.");
            SaveParameters();await Export(c);ResolveAnchors();Save();var path=NewFolder("component-preview");await WorkerRun("preview",path,c.Id);
            if(previews.TryGetValue(c.Id,out var old)){old.Dispose();previews.Remove(c.Id);}
            foreach(var item in previews.Values)await item.SetVisibleAsync(false);
            previews[c.Id]=await HullPreview.CreateAsync(app,model,Path.Combine(path,"preview.off"),AxisMapping.Standard,visible.Checked,cancel.Token,selection.ValidateDocument,Report);
            var reportText=File.ReadAllText(Path.Combine(path,"report.json"));log.AppendText(reportText+Environment.NewLine);
            var report=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(reportText);
            status.Text=Convert.ToString(report["qualification"])=="visual_only"?"Preview finished: zero added mass, visual follows its physical parent; no separate collision or breakaway.":"Component preview finished. Mass fitted; stiffness and damage remain provisional.";
        }
        private async Task Build()
        {
            if(Selected!=null)SaveParameters();
            if(project.JointWorkspace.Mode=="authored")await ScanJoints();
            var missing=project.Components.Where(c=>ComponentAssignments.State(project,c,false)!="saved").ToList();
            if(missing.Count>0)throw new InvalidOperationException("Assign this assembly's physical CAD before building: "+string.Join(", ",missing.Select(c=>c.Name))+". Visual assignments do not define physical ownership.");
            project.FrameBuildReceipt=VehicleProject.Load(project.FilePath).FrameBuildReceipt;
            var stamp=model.GetUpdateStamp();
            foreach(var c in project.Components){cancel.Token.ThrowIfCancellationRequested();await Export(c);await ExportCoilover(c);}
            ResolveAnchors();Save();if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("CAD changed between component exports. Regenerate the package.");
            var vehicle=project.Driveline!=null||project.JointWorkspace.Mode=="authored"||!string.IsNullOrWhiteSpace(project.TemplateDefinitionPath);
            if(vehicle)await EnsureCurrentFrame();
            else if(!File.Exists(project.FrameBuildReceipt))throw new InvalidOperationException("Package the calibrated frame for this project before packaging components.");
            var path=NewFolder(vehicle?"vehicle":"components");await WorkerRun(vehicle?"vehicle":"build",path);
            if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("CAD changed while generating the package. Regenerate before installing.");
            var receipt=Path.Combine(path,"static_frame_build.json");project.SelectBuild(receipt);settings.LastBuildReceipt=receipt;settings.Save();
            project.PhysicsBuildReceipt=receipt;Save();
            status.Text=(vehicle?"Vehicle":"Component")+" physics generated as a new package. Open Manage project mod to customize/install; verify the package before relying on its behavior.";
        }
        private Task ReplaceAppearance()
        {
            var component=Required();
            if(CoiloverAppearance.Active(component))throw new InvalidOperationException("This coilover uses separate moving pieces. Use the Coilover tab to update housing, shaft or spring. Clear all three slots there to return to a combined visual assignment.");
            if(project.Driveline?.Shafts.Any(s=>s.Component==component.Id&&!string.IsNullOrEmpty(s.Member))==true)throw new InvalidOperationException("This shaft uses independently moving members. Keep their physical CAD meshes, or use separate section groups for independent appearance replacement.");
            var assignment=selection.Capture();
            ComponentAssignments.Appearance(component,assignment,selection.Document);Save();RefreshLists();components.SelectedItem=component;assignmentInspection.Appearance=true;
            status.Text="Visual assignment saved: "+component.Name+" ("+assignment.Selections.Count+" selections). You can inspect/zoom now. Package saved appearances updates the mod separately.";
            log.AppendText(status.Text+Environment.NewLine+string.Join(Environment.NewLine,assignment.Selections.Select(s=>s.Name))+Environment.NewLine);
            return Task.CompletedTask;
        }
        private async Task PackageAppearances()
        {
            var targets=project.Components.Where(c=>c.AppearancePackageState=="pending"||c.AppearancePackageState=="failed").ToList();
            if(targets.Count==0)throw new InvalidOperationException("No pending visual assignments. Save a visual assignment or alignment first.");
            try
            {
                project.LastBuildReceipt=VehicleProject.Load(project.FilePath).LastBuildReceipt;
                if(string.IsNullOrWhiteSpace(project.LastBuildReceipt))throw new InvalidOperationException("Generate a physical package or import physics before packaging visuals. Your visual selections are already saved.");
                ModPackage.ArchivePath(project.LastBuildReceipt);
                var stamp=model.GetUpdateStamp();
                foreach(var component in targets)
                {
                    cancel.Token.ThrowIfCancellationRequested();
                    status.Text="Exporting saved visual "+(targets.IndexOf(component)+1)+" / "+targets.Count+": "+component.Name;
                    if(CoiloverAppearance.Active(component))await ExportCoilover(component);
                    else
                    {
                        var assignment=AssignmentInspection.Capture(component,true);AssignmentInspection.CheckDocument(component,true,selection.Document);
                        var geometryPath=NewFolder("appearance-cad");await selection.ExportAsync(assignment,geometryPath,cancel.Token);
                        component.AppearanceDirectory=geometryPath;
                    }
                }
                Save();var output=NewFolder("appearance");await WorkerRun("appearance",output);
                if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("CAD changed while packaging appearance. Retry the package update; saved selections are retained.");
                var receipt=Path.Combine(output,"static_frame_build.json");project.SelectBuild(receipt);
                foreach(var component in targets){component.AppearancePackageState="current";component.AppearancePackageError=null;}
                Save();settings.LastBuildReceipt=receipt;settings.Save();RefreshLists();
                status.Text="Packaged "+targets.Count+" saved visual groups. Physical nodes, mass and hardpoints are unchanged. Review the rendered result.";
            }
            catch(Exception error)
            {
                foreach(var component in targets){component.AppearancePackageState=error is OperationCanceledException?"pending":"failed";component.AppearancePackageError=error.Message;}
                Save();RefreshLists();
                if(error is OperationCanceledException)throw;
                throw new InvalidOperationException("Visual assignments are saved, but the package was not updated: "+error.Message,error);
            }
        }
        private async Task ExportCoilover(ComponentDefinition component)
        {
            if(!CoiloverAppearance.Active(component))return;
            CoiloverAppearance.Validate(component,selection.Document);
            foreach(var piece in component.AppearanceCoilover.Pieces)
            {
                cancel.Token.ThrowIfCancellationRequested();
                var assignment=CoiloverAppearance.Assignment(piece);
                if(!selection.BodyIds(assignment).OrderBy(v=>v).SequenceEqual(piece.BodyIds.OrderBy(v=>v)))throw new InvalidOperationException(component.Name+" / "+piece.Kind+": body ownership changed. Reassign this piece.");
                var path=NewFolder("coilover-"+piece.Kind);await selection.ExportAsync(assignment,path,cancel.Token);piece.GeometryDirectory=path;
            }
        }
        private Task StartFreshProject()
        {
            using(var dialog=new SaveFileDialog {Filter="CAD project (*.beamng-project.json)|*.beamng-project.json",Title="Save a new CAD project; current assignments will be kept separately",FileName=Path.GetFileNameWithoutExtension(selection.Document)+"-cad-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+".beamng-project.json",InitialDirectory=Path.GetDirectoryName(project.FilePath)})
                if(dialog.ShowDialog(this)==DialogResult.OK)
                {
                    var seed=VehicleProject.Load(project.FilePath);seed.MvpTemplates=templateChoices.Select(p=>new MvpTemplateChoice {Category=p.Key,Template=((MvpTemplateOption)p.Value.SelectedItem).Id}).ToList();
                    SwitchProject(seed.StartFresh(dialog.FileName,mvpCatalog,true));status.Text="Fresh CAD project saved: "+project.FilePath+". Required groups are unassigned; no physics, meshes or hardpoints were imported.";
                }
            return Task.CompletedTask;
        }
        private async Task CreateWorkingAssembly()
        {
            using(var dialog=new FolderBrowserDialog {Description="Choose a parent folder. A new dated working-assembly folder will be created inside it.",SelectedPath=Path.GetDirectoryName(project.FilePath),ShowNewFolderButton=true})
            {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                if(Selected!=null)SaveParameters();else Save();
                var folder=Path.Combine(dialog.SelectedPath,"working-assembly-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,6));
                var result=await new AssociationAssembly(app,model).Create(project,folder,(value,message)=>{
                    progress.Style=ProgressBarStyle.Continuous;progress.Value=value;status.Text=message;
                },cancel.Token);
                CompanionAssemblyLink.Register(result.ReceiptPath);
                settings.SelectProject(result.Project);settings.LastBuildReceipt="";settings.Save();
                if(ContextChanged!=null){ContextChanged(result.Project,result.Document);return;}
                var window=new ComponentWorkflow(app,result.Document,settings);
                window.status.Text="Working assembly saved. Add reference geometry to its copied parts or assembly; source CAD is unchanged. Recalibrate before building. Details: "+result.ReceiptPath;
                var incomplete=result.Project.Components.Where(c=>CoiloverAppearance.Active(c)&&AssociationAssembly.AssignedCoiloverMembers(c)==null).Select(c=>c.Name).ToArray();
                if(incomplete.Length>0)window.status.Text="Working assembly saved. These coilovers still need complete body classification in Moving members: "+string.Join(", ",incomplete)+". Source CAD is unchanged.";
                window.Show();closing=true;
            }
        }
        private string CompanionReceipt(bool choose)
        {
            var path=CompanionAssemblyLink.Find(project);if(path!=null)return path;
            if(!choose)throw new InvalidOperationException("Create or link a companion assembly first.");
            using(var dialog=new OpenFileDialog {Title="Choose the existing companion's working-assembly.json",Filter="Companion receipt (working-assembly.json)|working-assembly.json",InitialDirectory=Path.GetDirectoryName(project.FilePath)})
            {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return null;
                CompanionAssemblyLink.Attach(project,dialog.FileName);return dialog.FileName;
            }
        }
        private ModelDoc2 OpenCadAssembly(string path)
        {
            var document=app.GetOpenDocumentByName(path) as ModelDoc2;
            int error=0,warning=0;
            document=document??app.OpenDoc6(path,2,1,"",ref error,ref warning) as ModelDoc2;
            if(document==null)throw new IOException("Could not open "+path+" ("+error+").");
            app.ActivateDoc3(document.GetTitle(),false,0,ref error);return document;
        }
        private void ShowCompanion(AssociationAssembly.Result result,string message)
        {
            settings.SelectProject(result.Project);settings.LastBuildReceipt=result.Project.LastBuildReceipt??"";settings.Save();
            if(ComponentAssignments.SameDocument(model.GetPathName(),result.Document.GetPathName())){project=result.Project;RefreshLists();status.Text=message;return;}
            if(ContextChanged!=null){ContextChanged(result.Project,result.Document);return;}
            var window=new ComponentWorkflow(app,result.Document,settings);window.status.Text=message;window.Show();closing=true;
        }
        private Task OpenCompanion()
        {
            var path=CompanionReceipt(false);var receipt=CompanionAssemblyLink.Read(path);
            var companion=VehicleProject.Load(receipt.Project);
            ShowCompanion(new AssociationAssembly.Result {Document=OpenCadAssembly(receipt.Assembly),Project=companion,ReceiptPath=path},
                "Opened saved companion revision. "+CompanionAssemblyLink.Status(companion,path));
            return Task.CompletedTask;
        }
        private Task RefreshCompanionAppearances()=>RefreshCompanionAppearances(Required());
        private async Task RefreshCompanionAppearances(ComponentDefinition component)
        {
            Save();
            var path=CompanionReceipt(false);
            var backup=await new AssociationAssembly(app,model).RefreshAppearances(project,path,component.Id,(value,message)=>{
                progress.Style=ProgressBarStyle.Continuous;progress.Value=value;status.Text=message;
            },cancel.Token);
            RefreshLists();
            status.Text="Original source appearances restored for "+component.Name+". Geometry, folders and mates retained. Use Package saved appearances to update the mod. Part backups: "+backup;
        }
        private async Task UpdateWorkingAssembly()
        {
            var path=CompanionReceipt(true);if(path==null)return;var receipt=CompanionAssemblyLink.Read(path);
            if(!ComponentAssignments.SameDocument(project.FilePath,receipt.SourceProject)&&!ComponentAssignments.SameDocument(project.FilePath,receipt.Project))
                throw new InvalidOperationException("This is an earlier companion revision. Use Open companion to continue in the latest one; edits in earlier revisions are kept separately.");
            if(Selected!=null)SaveParameters();else Save();
            var sourceProject=VehicleProject.Load(receipt.SourceProject);var sourceModel=OpenCadAssembly(sourceProject.SourceDocument);
            try
            {
                var result=await new AssociationAssembly(app,sourceModel).Update(sourceProject,path,companionPanel.RefreshGeometry,(value,message)=>{
                    progress.Style=ProgressBarStyle.Continuous;progress.Value=value;status.Text=message;
                },cancel.Token);
                ShowCompanion(result,"Companion synchronized. Unchanged reference work retained; inspect mounts marked needs_repair. Fresh builds require recalibration. Details: "+result.ReceiptPath);
            }
            catch {int error=0;app.ActivateDoc3(model.GetTitle(),false,0,ref error);throw;}
        }
        private Task OpenProject()
        {
            using(var dialog=new OpenFileDialog {Filter="CAD project (*.json)|*.json",Title="Open saved CAD assignments",InitialDirectory=Path.GetDirectoryName(project.FilePath)})
                if(dialog.ShowDialog(this)==DialogResult.OK)
                {
                    var opened=VehicleProject.Load(dialog.FileName);
                    if(!ComponentAssignments.SameDocument(opened.SourceDocument,selection.Document))throw new InvalidOperationException("Activate the assembly belonging to this project: "+opened.SourceDocument);
                    SwitchProject(opened);status.Text="Opened saved project: "+project.FilePath;
                }
            return Task.CompletedTask;
        }
        private VehicleProject OpenSelectedProject()
        {
            try{return settings.ProjectForDocument(selection.Document);}
            catch(SelectedProjectUnavailableException error)
            {
                // A moved/deleted project must never silently expose an older
                // adjacent file. Let the user locate the saved work explicitly.
                using(var dialog=new OpenFileDialog {Filter="CAD project (*.json)|*.json",Title="Saved project unavailable - locate project for "+Path.GetFileName(selection.Document),
                    FileName=Path.GetFileName(error.ProjectPath),InitialDirectory=Path.GetDirectoryName(selection.Document)})
                {
                    if(dialog.ShowDialog()!=DialogResult.OK)throw;
                    var opened=VehicleProject.Load(dialog.FileName);
                    if(!ComponentAssignments.SameDocument(opened.SourceDocument,selection.Document))throw new InvalidOperationException("Activate the assembly belonging to this project: "+opened.SourceDocument);
                    settings.SelectProject(opened);settings.Save();return opened;
                }
            }
        }
        private void SwitchProject(VehicleProject value)
        {
            foreach(var preview in previews.Values)preview.Dispose();previews.Clear();project=value;
            settings.SelectProject(project);settings.LastBuildReceipt=project.LastBuildReceipt;settings.Save();ProjectChanged?.Invoke();
            foreach(var set in mvpCatalog.TemplateSets)templateChoices[set.Id].SelectedItem=mvpCatalog.Selected(project,set);
            RefreshLists();RefreshRoles(Selected);
        }
        private async Task ImportPhysicsTemplate()
        {
            if(project.Components.Count>0&&!string.IsNullOrWhiteSpace(project.PhysicsTemplateReceipt)){continueTemplate();return;}
            if(project.Components.Count>0)throw new InvalidOperationException("Import a physics template into an empty project so existing CAD assignments are preserved.");
            using(var dialog=new OpenFileDialog {Filter="Completed build receipt (static_frame_build.json)|static_frame_build.json",Title="Choose the completed template vehicle"})
            {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                ModPackage.ArchivePath(dialog.FileName);
                var baseline=JsonFile.Read<VehicleProject>(Path.Combine(Path.GetDirectoryName(dialog.FileName),"project.snapshot.json"));
                var previous=File.ReadAllBytes(project.FilePath);string receipt;
                try
                {
                    project.PhysicsTemplateReceipt=dialog.FileName;project.Components=baseline.Components;project.MvpTemplates=baseline.MvpTemplates;
                    project.TemplateDefinitionPath=baseline.TemplateDefinitionPath;
                    project.Anchors=new List<MountAnchor>();project.Connections=new List<MountConnection>();Save();
                    var output=NewFolder("template-fork");await WorkerRun("fork-template",output);
                    var definition=Path.Combine(output,"provenance","template-definition.json");
                    if(File.Exists(definition))
                    {
                        var local=project.FilePath+".template-"+Guid.NewGuid().ToString("N").Substring(0,8)+".json";
                        File.Copy(definition,local);project.TemplateDefinitionPath=local;
                    }
                    receipt=Path.Combine(output,"static_frame_build.json");project.SelectBuild(receipt);project.PhysicsBuildReceipt=receipt;Save();
                }
                catch
                {
                    File.WriteAllBytes(project.FilePath,previous);project=VehicleProject.Load(project.FilePath);RefreshLists();throw;
                }
                settings.LastBuildReceipt=receipt;settings.Save();RefreshLists();RefreshRoles(Selected);
                foreach(var set in mvpCatalog.TemplateSets)templateChoices[set.Id].SelectedItem=mvpCatalog.Selected(project,set);
                continueTemplate();
                status.Text="Template physics imported. Each row distinguishes its imported CAD from your saved visual selection. Select a group and Save visual assignment.";
            }
        }
        private async Task ResetPhysicsTemplate()
        {
            var reset=new TemplateProjectReset(project.FilePath);
            var output=NewFolder("template-reset");
            try
            {
                project=reset.Candidate;
                await WorkerRun("fork-template",output);
                cancel.Token.ThrowIfCancellationRequested();
                reset.Commit(output);
                settings.LastBuildReceipt=project.LastBuildReceipt;settings.Save();
                foreach(var preview in previews.Values)preview.Dispose();previews.Clear();
                RefreshLists();RefreshRoles(Selected);
                foreach(var set in mvpCatalog.TemplateSets)templateChoices[set.Id].SelectedItem=mvpCatalog.Selected(project,set);
                continueTemplate();
                log.AppendText("Template reset backup: "+reset.BackupPath+Environment.NewLine);
                status.Text="Original template restored. Accidental CAD assignments and appearance edits were reset. Backup: "+reset.BackupPath;
            }
            catch
            {
                project=VehicleProject.Load(project.FilePath);RefreshLists();RefreshRoles(Selected);throw;
            }
        }
        private Task AlignAppearance()
        {
            var component=Required();
            project.LastBuildReceipt=VehicleProject.Load(project.FilePath).LastBuildReceipt;
            using(var dialog=new Form {Text="Appearance alignment in BeamNG coordinates",Width=650,Height=250,StartPosition=FormStartPosition.CenterParent})
            {
                var fields=Flow();var values=Enumerable.Range(0,6).Select(i=>Number(-100000,100000,0)).ToArray();
                for(var i=0;i<3;i++)Field(fields,"XYZ"[i]+" offset mm",values[i]);
                for(var i=0;i<3;i++)Field(fields,"XYZ"[i]+" rotation degrees",values[i+3]);
                fields.Controls.Add(new Label {AutoSize=true,Text="A fresh absolute transform about the assembly origin. X left, Y rear, Z up. Physics stays unchanged."});
                var apply=new Button {Text="Apply alignment",DialogResult=DialogResult.OK,AutoSize=true};fields.Controls.Add(apply);dialog.Controls.Add(fields);dialog.AcceptButton=apply;
                if(dialog.ShowDialog(this)!=DialogResult.OK)return Task.CompletedTask;
                // In the native host, closing the last WinForms modal loop
                // restores a generic context. Reestablish UI dispatch before
                // creating progress callbacks or awaiting the package worker.
                SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
                var a=(double)values[3].Value*Math.PI/180;var b=(double)values[4].Value*Math.PI/180;var c=(double)values[5].Value*Math.PI/180;
                var ca=Math.Cos(a);var sa=Math.Sin(a);var cb=Math.Cos(b);var sb=Math.Sin(b);var cc=Math.Cos(c);var sc=Math.Sin(c);
                if(!CoiloverAppearance.Active(component)&&(component.AppearanceSelections==null||component.AppearanceSelections.Count==0))throw new InvalidOperationException("Save this group's visual assignment before aligning it.");
                component.AppearanceTransform=new[]{cc*cb,cc*sb*sa-sc*ca,cc*sb*ca+sc*sa,(double)values[0].Value/1000,sc*cb,sc*sb*sa+cc*ca,sc*sb*ca-cc*sa,(double)values[1].Value/1000,-sb,cb*sa,cb*ca,(double)values[2].Value/1000,0,0,0,1};
                component.AppearancePackageState="pending";component.AppearancePackageError=null;Save();RefreshLists();
                status.Text="Appearance alignment saved. Package saved appearances applies it; physical nodes and mounts are unchanged.";
            }
            return Task.CompletedTask;
        }
        private async Task RecalibrateProperties()
        {
            var component=Required();
            if(component.Template=="calibrated_frame")throw new InvalidOperationException("Use the frame calibration workflow for the independent material/reference fit, then regenerate vehicle physics.");
            project.LastBuildReceipt=VehicleProject.Load(project.FilePath).LastBuildReceipt;ModPackage.ArchivePath(project.LastBuildReceipt);
            SaveParameters();var previous=File.ReadAllBytes(project.FilePath);var assignment=selection.Capture();var stamp=model.GetUpdateStamp();
            var geometryPath=NewFolder("property-cad");await selection.ExportAsync(assignment,geometryPath,cancel.Token);
            try
            {
                component.GeometryDirectory=geometryPath;component.Selections=assignment.Selections;component.Configuration=assignment.Configuration;component.BodyIds=selection.BodyIds(assignment);component.CadSourceDocument=selection.Document;Save();
                var output=NewFolder("properties");await WorkerRun("properties",output,component.Id);
                if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("CAD changed during the property fit; the baseline remains selected.");
                var receipt=Path.Combine(output,"static_frame_build.json");project.SelectBuild(receipt);project.PhysicsBuildReceipt=receipt;Save();settings.LastBuildReceipt=receipt;settings.Save();
                status.Text="CAD mass, center and inertia fitted on the existing graph. Nodes and mounts are unchanged. Verify the new package; template stiffness and rupture remain provisional.";
            }
            catch{File.WriteAllBytes(project.FilePath,previous);project=VehicleProject.Load(project.FilePath);RefreshLists();throw;}
        }
        private async Task RefreshTaggedCad()
        {
            if(Selected!=null)SaveParameters();
            var stamp=model.GetUpdateStamp();var errors=new List<string>();
            for(var i=0;i<project.Components.Count;i++)
            {
                var component=project.Components[i];cancel.Token.ThrowIfCancellationRequested();
                status.Text="Refresh CAD "+(i+1)+" / "+project.Components.Count+": "+component.Name;
                try{await Export(component);}
                catch(OperationCanceledException){throw;}
                catch(Exception e){component.GeometryDirectory="";errors.Add(component.Name+": "+e.Message);}
            }
            try{ResolveAnchors();}catch(Exception e){errors.Add(e.Message);}
            Save();RefreshLists();
            if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("CAD changed during refresh; refresh again before using this inventory.");
            var inventory=project.FilePath+".inventory.json";await WorkerRun("inventory",inventory);
            log.AppendText("Reusable project: "+project.FilePath+Environment.NewLine+"Inventory: "+inventory+Environment.NewLine+string.Join(Environment.NewLine,errors)+Environment.NewLine);
            status.Text=errors.Count==0?"Tagged CAD refreshed. MVP checklist and inventory show missing roles and pending associations.":"Refresh finished with "+errors.Count+" unresolved groups/points. See the log and inventory.";
        }
        private async Task Verify()
        {
            var current=VehicleProject.Load(project.FilePath);
            var receipt=current.LastBuildReceipt;ModPackage.ArchivePath(receipt);
            var manifest=Path.Combine(Path.GetDirectoryName(receipt),"manifest.json");
            if(!File.Exists(manifest))throw new InvalidOperationException("Generate a package before verification.");
            var exported=new JavaScriptSerializer {MaxJsonLength=int.MaxValue}.Deserialize<Dictionary<string,object>>(File.ReadAllText(manifest));
            var vehicle=((System.Collections.IEnumerable)exported["capabilities"]).Cast<object>().Any(v=>Convert.ToString(v)=="vehicle");
            var arguments="verify --manifest "+OwnedWorker.Quote(manifest)+" --project "+OwnedWorker.Quote(project.FilePath)
                +" --game "+OwnedWorker.Quote(settings.GameDirectory)+" --profile "+OwnedWorker.Quote(settings.HarnessProfile)
                +(settings.SaveBuildReports=="true"?" --save-report":"");
            await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Worker,arguments,new Progress<string>(Report),cancel.Token,null,settings.FrameOutput);
            status.Text=vehicle?"Vehicle acceptance passed. Review the captures; native scenario checks do not establish real vehicle performance or material rupture.":"Component mounting checks passed. Component stiffness and real material rupture remain unqualified.";
        }
        private void Run(Func<Task> action)=>Run(action,true);
        private async void Run(Func<Task> action,bool requireActiveDocument)
        {
            if(cancel!=null||!ResolveDraft())return;cancel=new CancellationTokenSource();batchDetail="";status.ForeColor=System.Drawing.SystemColors.ControlText;editor.Enabled=false;stop.Visible=true;progress.Visible=true;progress.Style=ProgressBarStyle.Marquee;
            var previous=SynchronizationContext.Current;
            // SolidWorks owns the message loop. Establish the WinForms context
            // explicitly so CAD calls and control updates stay on this UI thread.
            if(!(previous is WindowsFormsSynchronizationContext))SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
            try{if(requireActiveDocument)selection.ValidateDocument();settings=settings.Reload();await action();}
            catch(OperationCanceledException){status.Text="Cancelled. Completed evidence retained.";}
            catch(Exception e){status.ForeColor=System.Drawing.Color.DarkRed;status.Text="Failed: "+e.Message;log.AppendText(e+Environment.NewLine);if(!HasPendingChanges){project=VehicleProject.Load(project.FilePath);RefreshLists();}}
            finally{cancel.Dispose();cancel=null;progress.Visible=false;stop.Visible=false;editor.Enabled=true;ProjectChanged?.Invoke();if(closing)Close();SynchronizationContext.SetSynchronizationContext(previous);}
        }
    }
}
