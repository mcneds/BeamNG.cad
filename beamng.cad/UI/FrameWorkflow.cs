using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using System.Threading;
using System.Diagnostics;
using System.Collections.Concurrent;
using System.Text;
using System.Web.Script.Serialization;
using BeamNG.Cad.Preparation;
using BeamNG.Cad.FramePipeline;
using SolidWorks.Interop.sldworks;
namespace BeamNG.Cad.UI
{
    internal sealed class FrameWorkflow : Form
    {
        private FrameSelection selection;
        private ModelDoc2 model;
        private readonly string sourceDocument;
        private readonly string sourceConfiguration;
        private readonly ISldWorks app;
        private ExporterSettings settings;
        private PreparationFile preparation;
        private FrameAssignment frame;
        internal bool IsForDocument(string document)=>ComponentAssignments.SameDocument(document,sourceDocument);
        private readonly TextBox summary = new TextBox { Multiline=true, ReadOnly=true, ScrollBars=ScrollBars.Vertical, Dock=DockStyle.Fill };
        private readonly TextBox log = new TextBox { Multiline=true, ReadOnly=true, ScrollBars=ScrollBars.Vertical, Dock=DockStyle.Fill };
        private readonly Label status = new Label { AutoSize=true, Dock=DockStyle.Top };
        private readonly FlowLayoutPanel controls = new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Top, FlowDirection=FlowDirection.TopDown, WrapContents=false };
        private readonly HullOptionsPanel hullOptions = new HullOptionsPanel();
        private readonly FramePreviewPane previewPane=new FramePreviewPane();
        private TabControl tabs=>previewPane.Editors;
        private readonly TabPage logTab = new TabPage("Preparation log");
        private readonly Button accept;
        private readonly Button viewPrepared;
        private readonly Button stop;
        private CancellationTokenSource cancellation;
        private FramePreviewWindow previewWindow;
        private int? previewStamp;
        private int preparedStamp;
        private ComponentWorkflow componentWindow;
        private string prepared;
        private string generation;
        private string requestedFixedGeneration;
        private string preparedFixedGeneration;
        private readonly ComboBox materialCase=new ComboBox {Name="CalibrationCase",DropDownStyle=ComboBoxStyle.DropDownList,Width=160};
        private readonly TextBox materialSummary=new TextBox {Name="SolidWorksMaterials",Multiline=true,ReadOnly=true,Dock=DockStyle.Fill,ScrollBars=ScrollBars.Both,WordWrap=false};
        private string preparedMaterials;
        private readonly FlowLayoutPanel materialActions=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Fill};
        private bool materialPicking;
        private readonly ComboBox verificationMode=new ComboBox {Name="VerificationMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=200};
        private readonly Button fixtures,calibrate,package,verify,diagnostics;
        private bool fixturesApproved;
        private string mountPlanProblem;
        internal bool IsBusy=>cancellation!=null||(previewWindow?.IsOptimizing??false);
        internal string PreviewStatus=>prepared!=null?"Prepared hull ready":previewStamp.HasValue&&previewWindow.HasSnapshot?"Proxy preview ready":null;
        internal string TaskMessage=>(previewWindow?.IsOptimizing??false)?previewWindow.SearchMessage:status.Text+"\r\n"+progressText.Text;
        internal string TaskLog=>log.Text;
        internal event Action<string> NavigationRequested;
        internal void StopTask(){cancellation?.Cancel();previewWindow?.StopSearch();}
        internal void HideDockedTaskControls(){status.Visible=false;taskProgress.Visible=false;progressText.Visible=false;stop.Visible=false;}
        internal VehicleReadiness NextFrameStep(VehicleReadiness projectStep,VehicleProject project)
        {
            if(generation!=null)
            {
                if(!fixturesApproved)return FrameStep("Fixtures need review","Review orientation, supports and loads before calibrating.","Review fixtures");
                if(package.Enabled)return FrameStep("Calibration accepted","Package the calibrated frame from Build / calibration.","Open packaging controls");
                return FrameStep("Fixtures approved","Run calibration using the frame's CAD materials.","Open calibration controls");
            }
            if(projectStep.CanGenerateFrame&&!string.IsNullOrEmpty(mountPlanProblem))
            {
                var destination=projectStep.Stage=="Frame"?(project.JointWorkspace.Mode=="authored"?"Joints":"Project"):projectStep.Stage;
                return new VehicleReadiness {Title="Mounting preflight needs attention",
                    Detail=mountPlanProblem,Stage=destination,ActionText="Review mounting inputs"};
            }
            if(projectStep.Stage!="Frame")return projectStep;
            if(prepared!=null)return FrameStep("Accept the prepared hull","Acceptance checks the current mounting inputs and opens fixture review.","Open hull acceptance");
            if(frame!=null)return FrameStep("Prepare the actual hull","Use the preview to review the shape, then prepare the hull for generation.","Open hull preparation");
            return FrameStep("Assign the frame bodies","Select the frame bodies in SolidWorks and save the selection in Selected geometry.","Open frame selection");
        }
        private static VehicleReadiness FrameStep(string title,string detail,string action)=>new VehicleReadiness {
            Title=title,Detail=detail,ActionText=action,Stage="Frame",CanGenerateFrame=true};
        internal void OpenNextFrameAction()
        {
            if(generation!=null)
            {
                tabs.SelectedTab=(TabPage)calibrate.Parent.Parent;
                if(!fixturesApproved)Try(ReviewFixtures);
                else if(package.Enabled)package.Focus();
                else calibrate.Focus();
            }
            else if(frame!=null)
            {
                tabs.SelectedTab=(TabPage)accept.Parent.Parent;
                if(prepared!=null)accept.Focus();
                else accept.Parent.Controls.OfType<Button>().First().Focus();
            }
            else tabs.SelectedTab=(TabPage)controls.Parent;
        }
        private bool closing;
        private readonly ProgressBar taskProgress=new ProgressBar {Name="TaskProgress",Width=540,Height=18,Style=ProgressBarStyle.Continuous,Visible=false};
        private readonly Label progressText=new Label {AutoSize=true,MaximumSize=new Size(560,0)};
        private readonly Stopwatch taskElapsed=new Stopwatch();
        private string progressPhase;
        private string progressDetail="";
        private string batchDetail="";
        private string studyOutcome;
        private string taskResult="Finished";
        private void ShowProgress(string line)
        {
            // Worker output can still be queued when a task ends. It must not revive its UI.
            if(!taskElapsed.IsRunning)return;
            try {
                var data=new JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string,object>>(line.Substring(13));
                progressPhase=Convert.ToString(data["phase"]);
                var detail=data.ContainsKey("detail")?Convert.ToString(data["detail"]):"";
                var done=data.ContainsKey("completed")&&data["completed"]!=null?Convert.ToDouble(data["completed"]):(double?)null;
                var total=data.ContainsKey("total")&&data["total"]!=null?Convert.ToDouble(data["total"]):(double?)null;
                taskProgress.Style=done.HasValue&&total>0?ProgressBarStyle.Continuous:ProgressBarStyle.Marquee;
                if(done.HasValue&&total>0)taskProgress.Value=(int)Math.Max(0,Math.Min(100,done.Value/total.Value*100));
                progressDetail=progressPhase+(done.HasValue&&total>0?" "+done.Value.ToString("0.##")+" / "+total.Value.ToString("0.##"):"")+" - "+detail;
                if(progressPhase=="Test batch")batchDetail=progressDetail;
                if(data.ContainsKey("outcome"))studyOutcome=progressDetail;
            } catch(Exception) { pendingLog.Enqueue("Invalid progress record: "+line); }
        }
        private readonly System.Windows.Forms.Timer saveTimer = new System.Windows.Forms.Timer { Interval=300 };
        private readonly System.Windows.Forms.Timer logTimer = new System.Windows.Forms.Timer { Interval=100 };
        private readonly ConcurrentQueue<string> pendingLog = new ConcurrentQueue<string>();
        private void FlushLog()
        {
            var text=new StringBuilder();
            while(pendingLog.TryDequeue(out var line)) { if(line.StartsWith("CAD_PROGRESS "))ShowProgress(line);else text.AppendLine(line); }
            if(taskElapsed.IsRunning)
            {
                var detail=progressDetail==status.Text?"":progressDetail;
                progressText.Text=(string.IsNullOrEmpty(detail)?"":detail+"\r\n")+
                    (string.IsNullOrEmpty(batchDetail)?"":batchDetail+" | ")+"Elapsed "+taskElapsed.Elapsed.ToString(@"hh\:mm\:ss");
            }
            if(text.Length>0 && !IsDisposed) log.AppendText(text.ToString());
        }
        private void UpdateTaskProgress(bool running)
        {
            // Drain the previous task before starting the next, and the final records before stopping.
            FlushLog();
            if(running)
            {
                studyOutcome=null;taskResult="Finished";progressPhase=null;
                progressDetail="Working...";batchDetail="";
                taskProgress.Value=0;taskProgress.Style=ProgressBarStyle.Marquee;taskProgress.Visible=true;
                taskElapsed.Restart();progressText.Text="Working...";
            }
            else
            {
                var wasRunning=taskElapsed.IsRunning;
                taskElapsed.Stop();taskProgress.Visible=false;taskProgress.Style=ProgressBarStyle.Continuous;taskProgress.Value=0;
                if(wasRunning)
                    progressText.Text=taskResult+" - "+status.Text+"\r\nElapsed "+taskElapsed.Elapsed.ToString(@"hh\:mm\:ss");
            }
        }
        private sealed class WorkerProgress : IProgress<string>
        {
            private readonly Action<string> report;
            public WorkerProgress(Action<string> report) { this.report=report; }
            public void Report(string value) => report(value);
        }
        private void ValidateGeneration()
        {
            selection.ValidateDocument();
            if(frame != null && frame.Configuration != selection.Configuration)
                throw new InvalidOperationException("Configuration changed. Reopen the frame workflow and prepare again.");
        }
        public FrameWorkflow(ISldWorks app, ModelDoc2 model)
        {
            this.app=app;this.model=model;selection=new FrameSelection(app,model);selection.ValidateDocument();
            sourceDocument=selection.Document;sourceConfiguration=selection.Configuration;
            settings=new ExporterSettings(null);preparation=PreparationFile.Load(selection.Document);frame=preparation.Frame(selection.Configuration);
            Text="beamng.cad - Frame";Width=780;Height=900;MinimumSize=new Size(680,620);ShowInTaskbar=false;
            var layout=new TableLayoutPanel { Dock=DockStyle.Fill, ColumnCount=1, RowCount=2, Padding=new Padding(4) };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Controls.Add(layout);
            controls.Controls.Add(new Label { AutoSize=true, MaximumSize=new Size(560,0), Text="Select bodies, faces, body/cut-list folders, or components in SolidWorks. Faces select their owning body; folders select their contained bodies. Generated meshes stay external." });
            var actions=new FlowLayoutPanel { AutoSize=true };
            AddButton(actions,"Use current selection",CaptureSelection);AddButton(actions,"Show saved selection",()=>selection.Show(frame));
            AddButton(actions,"Load frame data",()=>{
                if(cancellation!=null)return;
                selection.SnapshotBodies(frame);
                InspectSavedFrame();
                status.Text="Saved frame data loaded and inspected.";
            });
            AddButton(actions,"Remove assignment",()=> { preparation.Assignments.RemoveAll(a=>a.Configuration==selection.Configuration && a.Role=="frame");JsonFile.Write(PreparationFile.FileName(selection.Document),preparation);frame=null;InvalidatePreview();previewStamp=null;if(previewWindow!=null&&!previewWindow.IsDisposed)previewWindow.MarkStale("Frame assignment removed.");summary.Clear(); });
            controls.Controls.Add(actions);
            var storage=new FlowLayoutPanel {AutoSize=true,MaximumSize=new Size(680,0)};
            var buildPath=new TextBox {Name="BuildDirectory",ReadOnly=true,Width=470,Text=settings.FrameOutput};
            storage.Controls.Add(new Label {Text="Build directory",AutoSize=true});storage.Controls.Add(buildPath);
            AddButton(storage,"Choose build directory...",()=>{
                using(var picker=new FolderBrowserDialog {Description="Store new CAD exports, builds and test evidence here",SelectedPath=settings.FrameOutput,ShowNewFolderButton=true})
                    if(picker.ShowDialog(this)==DialogResult.OK){settings.FrameOutput=BuildStorage.EnsureDirectory(picker.SelectedPath);settings.Save();buildPath.Text=settings.FrameOutput;status.Text="New builds will use "+settings.FrameOutput+". Existing generations keep their current paths.";}
            });controls.Controls.Add(storage);
            var saveReports=new CheckBox {Name="SaveBuildReports",Text="Save full build report (failures are always kept)",AutoSize=true,Checked=settings.SaveBuildReports=="true"};
            saveReports.CheckedChanged+=(s,e)=>{settings.SaveBuildReports=saveReports.Checked?"true":"false";settings.Save();};controls.Controls.Add(saveReports);
            var selectionTab=new TabPage("Selected geometry") {AutoScroll=true};
            summary.Dock=DockStyle.Top;summary.Height=140;
            selectionTab.Controls.Add(summary);selectionTab.Controls.Add(controls);
            var hullTab=new TabPage("Hull settings");hullTab.Controls.Add(hullOptions);
            var hullActions=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Top};hullTab.Controls.Add(hullActions);
            var buildTab=new TabPage("Build / calibration") {AutoScroll=true};
            var materialTab=new TabPage("SolidWorks materials");
            var materialLayout=new TableLayoutPanel {Dock=DockStyle.Fill,RowCount=2,ColumnCount=1};
            materialLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));materialLayout.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            AddButton(materialActions,"Set material for current selection",()=>SetMaterials(false));
            AddButton(materialActions,"Set material for saved frame",()=>SetMaterials(true));
            AddButton(materialActions,"Refresh materials",()=>{if(cancellation==null)RefreshMaterials();});
            materialActions.Controls.Add(new Label {AutoSize=true,MaximumSize=new Size(650,0),Text="Choose a material, click Apply, then Close. Shared part/configuration instances share body materials. Changes remain unsaved until you save your CAD documents."});
            materialLayout.Controls.Add(materialActions,0,0);materialLayout.Controls.Add(materialSummary,0,1);materialTab.Controls.Add(materialLayout);
            logTab.Controls.Add(log);tabs.TabPages.AddRange(new[]{hullTab,selectionTab,materialTab,buildTab,logTab});tabs.SelectedTab=hullTab;
            layout.Controls.Add(previewPane,0,0);
            previewWindow=previewPane.Preview;
            previewWindow.RefreshRequested+=()=>OpenLivePreview(true);
            previewWindow.SettingsRequested+=()=>tabs.SelectedTab=hullTab;
            previewWindow.Measured+=line=>pendingLog.Enqueue(line);
            previewWindow.CheckContextRequested+=()=>{if(cancellation!=null)throw new InvalidOperationException("Wait for the running frame task before searching or checking candidates.");ValidateGeneration();if(!previewStamp.HasValue||model.GetUpdateStamp()!=previewStamp.Value)throw new InvalidOperationException("CAD changed since preview capture. Refresh CAD before searching or checking candidates.");};
            previewWindow.ApplyRequested+=value=>{if(IsBusy)return;hullOptions.Value=value;OptionsChanged();};
            previewWindow.SearchBusyChanged+=running=>{
                foreach(Control control in accept.Parent.Controls)control.Enabled=!running;
                foreach(Control control in stop.Parent.Controls)control.Enabled=!running;
                controls.Enabled=materialActions.Enabled=!running;
                stop.Enabled=running;
                if(!running){Busy(cancellation!=null);if(closing&&cancellation==null)Close();}
            };
            var parameters=new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Top, MaximumSize=new Size(580,0) };
            parameters.Controls.Add(new Label { AutoSize=true, MaximumSize=new Size(560,0), Text="Physical materials come from the selected bodies' SolidWorks assignments. Select bodies/components in SolidWorks to edit their materials explicitly; Refresh reads them without changes." });
            AddButton(hullActions,"Live proxy preview",()=>OpenLivePreview());
            AddButton(hullActions,"Prepare actual hull",()=>Prepare());
            viewPrepared=AddButton(hullActions,"View prepared hull",ShowPreparedHull);
            AddButton(parameters,"Refit on existing frame graph",()=>{
                if(cancellation!=null)return;
                using(var picker=new OpenFileDialog {Filter="Generation review (review.json)|review.json",Title="Choose the frame generation whose nodes and beams must remain fixed"})
                    if(picker.ShowDialog(this)==DialogResult.OK){GenerationReview.Load(picker.FileName);requestedFixedGeneration=Path.GetDirectoryName(picker.FileName);Prepare();}
            });
            accept=AddButton(hullActions,"Accept hull / review fixtures",()=>StartGeneration());accept.Enabled=false;
            fixtures=AddButton(parameters,"Review fixtures",()=>ReviewFixtures());
            calibrate=AddButton(parameters,"Calibrate CAD frame",()=>RunCalibration(false));
            package=AddButton(parameters,"Package calibrated mod",()=>Package());
            verify=AddButton(parameters,"Verify in BeamNG",()=>RunCalibration(true));
            verificationMode.Items.AddRange(new object[]{"Quick check (4 tests)","Full verification (22 tests)"});
            verificationMode.SelectedIndex=settings.VerificationMode=="full"?1:0;
            verificationMode.SelectedIndexChanged+=(s,e)=>{settings.VerificationMode=verificationMode.SelectedIndex==0?"quick":"full";settings.Save();};
            parameters.Controls.Add(verificationMode);
            diagnostics=AddButton(parameters,"Run diagnostics in BeamNG",()=>RunCalibration(true,true));
            parameters.Controls.Add(taskProgress);parameters.Controls.Add(progressText);
            materialCase.Items.Add("solidworks-assigned");materialCase.SelectedIndex=0;materialCase.Visible=false;
            parameters.Controls.Add(materialCase);
            AddButton(parameters,"Open generation...",()=>{
                using(var picker=new OpenFileDialog {Filter="Generation fixtures|review.json",InitialDirectory=settings.LastCalibrationGeneration})
                    if(picker.ShowDialog(this)==DialogResult.OK){var review=GenerationReview.Load(picker.FileName);InvalidatePreview();generation=Path.GetDirectoryName(picker.FileName);fixturesApproved=review.approved;Busy(false);status.Text="Opened immutable generation: "+generation;}
            });
            AddButton(parameters,"Open calibration report",()=>{
                if(generation==null)throw new InvalidOperationException("Create or open a generation first.");
                var report=Path.Combine(generation,"study","index.html");
                if(verificationMode.SelectedIndex==0 && File.Exists(Path.Combine(generation,"study","quick-verification.json")))report=Path.Combine(generation,"study","quick-verification.json");
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(File.Exists(report)?report:Path.Combine(generation,"study","build-result.json")){UseShellExecute=true});
            });
            fixtures.Enabled=calibrate.Enabled=package.Enabled=verify.Enabled=false;
            stop=AddButton(parameters,"Stop",()=>cancellation?.Cancel());stop.Enabled=false;
            AddButton(parameters,"Manage Mod",()=>{
                if(NavigationRequested!=null){NavigationRequested("Delivery");return;}
                var current=new ExporterSettings(null);var project=current.ProjectForDocument(selection.Document);
                new ModManager(current,null,project) {SolidWorksApplication=app}.Show(this);
            });
            AddButton(parameters,"Components / mounts",()=>{
                if(NavigationRequested!=null){NavigationRequested("Components");return;}
                if(componentWindow!=null&&!componentWindow.IsDisposed){componentWindow.Activate();return;}
                componentWindow=new ComponentWorkflow(app,model);componentWindow.Show(this);
            });
            buildTab.Controls.Add(parameters);layout.Controls.Add(status,0,1);
            if (frame != null)
            {
                hullOptions.Value=frame.Hull;
                summary.Text=string.Join("\r\n", frame.Selections.ConvertAll(s=>s.Name));
                status.Text="Restored saved frame selection and hull settings for '"+selection.Configuration+"'. Use Components / mounts > Use saved frame to link it to your project.";
                Shown+=(s,e)=>BeginInvoke(new Action(()=>{
                    Try(InspectSavedFrame);
                }));
            }
            hullOptions.ValueChanged+=(s,e)=>OptionsChanged();
            saveTimer.Tick+=(s,e)=> {saveTimer.Stop();if(frame!=null)Try(()=>preparation.Save(frame));};
            logTimer.Tick+=(s,e)=>{FlushLog();CheckPreviewContext();};logTimer.Start();
            FormClosing+=(s,e)=> {
                if(materialPicking) {e.Cancel=true;status.Text="Close the SolidWorks material picker first.";}
                else if(IsBusy) {closing=true;StopTask();e.Cancel=true;}
                else { if(saveTimer.Enabled && frame!=null) Try(()=>preparation.Save(frame)); saveTimer.Stop();previewWindow?.Dispose(); }
            };
            FormClosed+=(s,e)=> {saveTimer.Dispose();logTimer.Dispose();};
            Disposed+=(s,e)=>{saveTimer.Dispose();logTimer.Dispose();previewWindow?.Dispose();};
            tabs.SizeChanged+=(s,e)=>{
                var width=Math.Max(230,tabs.ClientSize.Width-30);controls.MaximumSize=new Size(width,0);actions.MaximumSize=new Size(width,0);parameters.MaximumSize=new Size(width,0);storage.MaximumSize=new Size(width,0);buildPath.Width=Math.Max(180,width-30);taskProgress.Width=Math.Min(540,width-20);
                foreach(var label in controls.Controls.OfType<Label>())label.MaximumSize=new Size(width-12,0);
                foreach(var label in parameters.Controls.OfType<Label>())label.MaximumSize=new Size(width-12,0);
            };
            Busy(false);
        }
        private Button AddButton(Control parent,string label,Action action)
        { var button=new Button { Text=label,AutoSize=true };button.Click+=(s,e)=>Try(action);parent.Controls.Add(button);return button; }
        private void Try(Action action) { try { action(); } catch(Exception e) {status.Text=e.Message;log.AppendText(e+System.Environment.NewLine);} }
        private void InspectSavedFrame()
        {
            try
            {
                var timer=Stopwatch.StartNew();summary.Text=selection.Summary(frame);
                pendingLog.Enqueue("Selection inspection: "+timer.ElapsedMilliseconds+" ms.");
                RefreshMaterials();
            }
            catch(Exception e) when(e.GetBaseException() is LightweightComponentException)
            {
                // Opening the workspace must not resolve CAD or report a normal
                // unloaded state as a failed assignment. Keep saved names visible.
                summary.Text=string.Join("\r\n",frame.Selections.ConvertAll(s=>s.Name));
                materialSummary.Text="Materials have not been inspected. "+e.GetBaseException().Message;
                status.Text="Saved frame restored; some component data is lightweight. Choose Live proxy preview for an approximation, Load frame data to inspect materials, or Prepare actual hull for full preparation.";
            }
        }
        private async void SetMaterials(bool savedFrame)
        {
            if(IsBusy)return;
            if(savedFrame && frame==null){status.Text="Define the frame selection first.";return;}
            cancellation=new CancellationTokenSource();
            var attempted=false;
            string previousFrameMaterials=null;
            try
            {
                Busy(true);
                progressDetail="Loading selected component data and inspecting material targets...";
                status.Text=progressDetail;
                System.Collections.Generic.List<Tuple<Component2,Body2>> targets;
                using(var quiet=new MaterialUiUpdateScope(app))
                {
                    quiet.Track(model);
                    targets=selection.MaterialBodies(savedFrame?frame:null);
                }
                // An unrelated stale/lightweight saved frame must not prevent a
                // valid current selection from reaching the native picker.
                if(frame!=null)
                    try
                    {
                        var before=selection.ReadMaterials(frame);
                        if(before.Bodies.TrueForAll(b=>b.Error==null))previousFrameMaterials=before.Fingerprint();
                    }
                    catch(Exception e) { pendingLog.Enqueue("Saved frame material snapshot unavailable: "+e.Message); }
                using(var assignment=new BulkMaterialAssignment(app,model,targets))
                {
                    assignment.Status=message=>{
                        progressDetail=message;status.Text=message;
                        progressText.Refresh();status.Refresh();
                    };
                    status.Text="Choose a material for "+assignment.Count+" unique bodies; click Apply, then Close.";
                    progressDetail=status.Text;
                    materialPicking=true;stop.Enabled=false;
                    NativeMaterialChoice choice;
                    try { choice=await assignment.PickAsync(this); }
                    finally { materialPicking=false;stop.Enabled=true; }
                    if(choice==null){status.Text="Material picker closed without applying; bodies unchanged.";taskResult="Cancelled";return;}
                    attempted=true;
                    var result=await assignment.ApplyAsync(choice,(done,total,label)=>{
                        taskProgress.Style=ProgressBarStyle.Continuous;taskProgress.Value=done*100/total;
                        progressDetail="Assigning "+choice.Name+": "+done+" / "+total+" bodies";
                        status.Text=progressDetail;
                    },cancellation.Token);
                    status.Text=result.Summary;
                    taskResult=result.Error!=null?"Failed":result.Cancelled?"Cancelled":"Finished";
                    pendingLog.Enqueue(choice.Name+": "+result.Summary);
                    foreach(var detail in result.Diagnostics)pendingLog.Enqueue(detail);
                    foreach(var label in result.Applied)pendingLog.Enqueue("Assigned: "+label);
                    foreach(var label in result.Remaining)pendingLog.Enqueue("Not confirmed: "+label);
                }
            }
            catch(Exception e){taskResult="Failed";status.Text=e.Message;pendingLog.Enqueue(e.ToString());}
            finally
            {
                materialPicking=false;
                var outcome=status.Text;
                // Even a rejected readback may follow a successful native write.
                if(attempted)
                {
                    try
                    {
                        if(frame!=null)
                        {
                            var after=selection.ReadMaterials(frame);
                            var unverifiable=previousFrameMaterials==null || after.Bodies.Exists(b=>b.Error!=null);
                            if(unverifiable || previousFrameMaterials!=after.Fingerprint())
                            {
                                InvalidatePreview();
                                outcome+=unverifiable?" Saved frame could not be verified; prepare it again before building.":" Frame materials changed; prepare the frame again.";
                            }
                        }
                        RefreshMaterials();
                    }
                    catch(Exception e)
                    {
                        InvalidatePreview();
                        materialSummary.Text="Saved frame materials could not be checked: "+e.Message;
                        outcome+=" Saved frame could not be checked; prepare it again before building.";
                        pendingLog.Enqueue("Saved frame invalidated after material assignment: "+e.Message);
                    }
                }
                status.Text=outcome;
                cancellation.Dispose();cancellation=null;
                Busy(false);
                if(closing)Close();
            }
        }
        private void RefreshMaterials()
        {
            if(frame==null){materialSummary.Text="Define the frame selection first.";return;}
            MaterialSnapshot snapshot;
            try { snapshot=selection.ReadMaterials(frame); }
            catch(Exception e) { materialSummary.Text=e.Message;throw; }
            materialSummary.Text=snapshot.Summary();
            if(prepared!=null && preparedMaterials!=null && preparedMaterials!=snapshot.Fingerprint())
            {
                InvalidatePreview();if(cancellation==null)Busy(false);status.Text="SolidWorks materials changed. Prepare again to capture and calibrate the new assignments.";
            }
        }
        private void RefreshCases()
        {
            if(generation==null)return;
            var selected=materialCase.SelectedItem as string;
            var choices=new System.Collections.Generic.List<string>();
            var study=Path.Combine(generation,"study","calibration-study.json");
            if(File.Exists(study))
            {
                var data=new JavaScriptSerializer {MaxJsonLength=int.MaxValue}.Deserialize<System.Collections.Generic.Dictionary<string,object>>(File.ReadAllText(study));
                choices.AddRange(((System.Collections.Generic.Dictionary<string,object>)data["candidates"]).Keys);
            }
            else if(File.Exists(Path.Combine(generation,"source","material-snapshot.json")))choices.Add("solidworks-assigned");
            else choices.AddRange(new[]{"4130-annealed","4130-normalized"});
            if(choices.Count==0)return;
            materialCase.Items.Clear();materialCase.Items.AddRange(choices.ConvertAll(c=>(object)c).ToArray());
            materialCase.SelectedItem=choices.Contains(selected)?selected:choices[0];materialCase.Visible=choices.Count>1;
        }
        private void InvalidatePreview()
        {
            prepared=null;generation=null;preparedFixedGeneration=null;
            mountPlanProblem=null;fixturesApproved=false;
            fixtures.Enabled=calibrate.Enabled=package.Enabled=verify.Enabled=false;accept.Enabled=viewPrepared.Enabled=false;
            if(previewWindow!=null&&!previewWindow.IsDisposed)previewWindow.UpdateOptions(hullOptions.Value);
        }
        private FramePreviewWindow PreviewWindow()
        {
            return previewWindow;
        }
        private async void OpenLivePreview(bool refresh=false)
        {
            if(IsBusy)return;
            var window=PreviewWindow();
            try{RefreshDocumentContext();ValidateGeneration();}
            catch(Exception error){status.Text=error.Message;window.MarkStale(error.Message);return;}
            if(window.HasSnapshot&&!refresh){window.UpdateOptions(hullOptions.Value);return;}
            cancellation=new CancellationTokenSource();Busy(true);previewStamp=null;
            window.MarkStale("Capturing saved frame display geometry…");
            try
            {
                ValidateGeneration();if(frame==null)throw new InvalidOperationException("Define the frame selection first.");
                var stamp=model.GetUpdateStamp();
                var points=await selection.CapturePreviewAsync(frame,cancellation.Token,line=>{status.Text=line;window.SetMessage(line);});
                cancellation.Token.ThrowIfCancellationRequested();ValidateGeneration();
                if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("CAD changed during capture. Refresh the live preview.");
                if(!window.IsDisposed){previewStamp=stamp;window.SetSnapshot(points,hullOptions.Value);}
                status.Text="Proxy preview ready. Use Hull settings to adjust the shape.";
            }
            catch(OperationCanceledException){taskResult="Cancelled";status.Text="Preview capture stopped.";}
            catch(Exception error){taskResult="Failed";status.Text=error.Message;window.SetMessage(error.Message);pendingLog.Enqueue(error.ToString());}
            finally{cancellation.Dispose();cancellation=null;Busy(false);if(closing)Close();}
        }
        private void CheckPreviewContext()
        {
            if(cancellation!=null)return;
            try{RefreshDocumentContext();}
            catch(Exception error)
            {
                if(previewStamp.HasValue||prepared!=null)
                {previewStamp=null;InvalidatePreview();previewWindow.MarkStale(error.Message);}
                return;
            }
            if(!previewStamp.HasValue)return;
            try
            {
                ValidateGeneration();
                if(model.GetUpdateStamp()==previewStamp.Value)return;
            }
            catch(Exception) { }
            previewStamp=null;InvalidatePreview();
            if(previewWindow!=null&&!previewWindow.IsDisposed)previewWindow.MarkStale("CAD document, configuration or geometry changed.");
        }
        private void RefreshDocumentContext()
        {
            // Never replace the document underneath an in-flight export/capture.
            if(IsBusy)return;
            var active=app.ActiveDoc as ModelDoc2;
            if(active==null||!ComponentAssignments.SameDocument(active.GetPathName(),sourceDocument))
                throw new InvalidOperationException("Activate the frame's source assembly to refresh CAD.");
            if(active.ConfigurationManager.ActiveConfiguration.Name!=sourceConfiguration)
                throw new InvalidOperationException("Activate configuration '"+sourceConfiguration+"' to refresh this frame.");
            bool same;
            try{same=app.IsSame(active,model)==(int)SolidWorks.Interop.swconst.swObjectEquality.swObjectSame;}
            catch(System.Runtime.InteropServices.COMException error) when(error.ErrorCode==unchecked((int)0x80010108)){same=false;}
            if(same)return;
            var replacement=new FrameSelection(app,active);replacement.ValidateDocument();
            if(saveTimer.Enabled&&frame!=null){preparation.Save(frame);saveTimer.Stop();}
            previewStamp=null;InvalidatePreview();previewWindow.MarkStale("Source assembly reopened. Capture fresh display geometry.");
            model=active;selection=replacement;
            preparation=PreparationFile.Load(sourceDocument);frame=preparation.Frame(sourceConfiguration);
            if(frame!=null){hullOptions.Value=frame.Hull;summary.Text=string.Join("\r\n",frame.Selections.ConvertAll(s=>s.Name));}
            else summary.Clear();
            status.Text="Source assembly reopened. Saved frame restored; refresh CAD for a new preview.";
        }
        private async void ShowPreparedHull()
        {
            if(IsBusy||prepared==null)return;
            cancellation=new CancellationTokenSource();Busy(true);
            try
            {
                ValidateGeneration();
                if(model.GetUpdateStamp()!=preparedStamp){InvalidatePreview();throw new InvalidOperationException("CAD changed since preparation. Prepare the frame again.");}
                await PreviewWindow().ShowExactAsync(Path.Combine(prepared,"mochi_hull.off"),cancellation.Token);
                status.Text="Showing the actual prepared hull. Live proxy preview returns to the approximation.";
            }
            catch(OperationCanceledException){taskResult="Cancelled";status.Text="Preview display stopped; prepared hull retained.";}
            catch(Exception error){taskResult="Failed";status.Text=error.Message;pendingLog.Enqueue(error.ToString());}
            finally{cancellation.Dispose();cancellation=null;Busy(false);if(closing)Close();}
        }
        private void CaptureSelection()
        {
            if(IsBusy) return;
            var captured=selection.Capture();var details=selection.Summary(captured);
            if(MessageBox.Show(this,details+"\r\n\r\nUse this selection as the frame?","Frame selection",MessageBoxButtons.OKCancel)!=DialogResult.OK) return;
            if(frame!=null) {captured.Id=frame.Id;captured.Hull=frame.Hull;}
            frame=captured;SaveOptions();preparation.Save(frame);InvalidatePreview();previewStamp=null;
            if(previewWindow!=null&&!previewWindow.IsDisposed)previewWindow.MarkStale("Frame selection changed.");
            RefreshMaterials();summary.Text=details;status.Text="Frame selection and hull settings saved beside the assembly; they reload after restarting SolidWorks. In Components / mounts, choose the frame and Use saved frame.";
        }
        private void SaveOptions()
        {
            if(frame==null) return;
            frame.Hull=hullOptions.Value;
        }
        private void OptionsChanged()
        {
            if(cancellation!=null) return;InvalidatePreview();SaveOptions();
            status.Text="Hull settings changed. Live approximation updates from its CAD snapshot; prepare again to review the actual hull.";
            saveTimer.Stop();if(frame!=null)saveTimer.Start();
        }
        private void Busy(bool value)
        {
            if(!value)RefreshCases();
            UpdateTaskProgress(value);
            controls.Enabled=!value;
            materialActions.Enabled=!value;
            hullOptions.Enabled=!value;
            // Freeze all generation inputs while a snapshot or build is in progress.
            var parent=accept.Parent;
            foreach(Control control in parent.Controls) control.Enabled=!value;
            foreach(Control control in stop.Parent.Controls) control.Enabled=!value;
            taskProgress.Enabled=progressText.Enabled=true;
            stop.Enabled=value;accept.Enabled=!value && prepared!=null;
            viewPrepared.Enabled=!value&&prepared!=null;
            fixtures.Enabled=!value && generation!=null && !Directory.Exists(Path.Combine(generation,"study"));
            calibrate.Enabled=!value && generation!=null;
            var accepted=AcceptedCalibration();
            package.Enabled=verify.Enabled=!value && accepted;
            diagnostics.Enabled=!value && generation!=null && File.Exists(Path.Combine(generation,"study","calibration-study.json"));
        }
        private bool AcceptedCalibration()
        {
            try {
                if(generation==null)return false;
                var data=new JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string,object>>(File.ReadAllText(Path.Combine(generation,"study","calibration-study.json")));
                var candidates=(System.Collections.Generic.Dictionary<string,object>)data["candidates"];
                if(candidates.Count==0)return false;
                foreach(var candidate in candidates.Values)
                    if(!Convert.ToBoolean(((System.Collections.Generic.Dictionary<string,object>)candidate)["offline_accepted"]))return false;
                return true;
            } catch(IOException){return false;} catch(ArgumentException){return false;} catch(System.Collections.Generic.KeyNotFoundException){return false;}
        }
        private async void Prepare()
        {
            if(IsBusy) return;
            var fixedGeneration=requestedFixedGeneration;requestedFixedGeneration=null;
            saveTimer.Stop();cancellation=new CancellationTokenSource();Busy(true);InvalidatePreview();
            try
            {
                settings=new ExporterSettings(null); selection.ValidateDocument();if(frame==null)throw new InvalidOperationException("Define the frame selection first.");
                SaveOptions();frame.Hull.Validate();preparation.Save(frame);settings.Save();
                BuildStorage.EnsureDirectory(settings.FrameOutput);
                var run=Path.Combine(settings.FrameOutput,"cad-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,8));
                var meshes=Path.Combine(run,"meshes");status.Text="Exporting selected frame bodies...";progressDetail="CAD export";
                var timer=Stopwatch.StartNew();
                var stamp=model.GetUpdateStamp();
                if(previewStamp!=stamp&&previewWindow!=null&&!previewWindow.IsDisposed)previewWindow.MarkStale("Preparing a fresh CAD snapshot.");
                await selection.ExportAsync(frame,meshes,cancellation.Token);
                pendingLog.Enqueue("CAD export: "+timer.ElapsedMilliseconds+" ms.");
                var output=Path.Combine(run,"prepared");var script=Path.Combine(Path.GetDirectoryName(typeof(FrameWorkflow).Assembly.Location),"FramePipeline","prepare_frame.py");
                var fileLogGate=new object();
                var progress=new WorkerProgress(line=> {pendingLog.Enqueue(line);lock(fileLogGate)File.AppendAllText(Path.Combine(run,"preparation.log"),line+System.Environment.NewLine);});
                status.Text="Preparing hull in background...";
                tabs.SelectedTab=logTab;
                progressDetail="Hull preparation";
                await OwnedWorker.RunWithScratch(settings.PythonExecutable,script,"--geometry "+OwnedWorker.Quote(Path.Combine(meshes,"geometry.json"))
                    +" --materials "+OwnedWorker.Quote(settings.FrameSource)+" --output "+OwnedWorker.Quote(output)
                    +" --blender "+OwnedWorker.Quote(settings.BlenderExecutable)+" --cgal "+OwnedWorker.Quote(settings.CgalPythonExecutable),progress,cancellation.Token,null,settings.FrameOutput);
                if(fixedGeneration!=null)
                {
                    // Explicit fixed-graph refitting must still verify the old
                    // mount contract before presenting that graph for reuse.
                    await PrepareMountPlan(output,cancellation.Token);
                    await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Path.Combine(Path.GetDirectoryName(script),"calibration_worker.py"),
                        "fixed-preview --job "+OwnedWorker.Quote(fixedGeneration)+" --source "+OwnedWorker.Quote(output),progress,cancellation.Token,null,settings.FrameOutput);
                }
                Action validate=()=> {ValidateGeneration();if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("Assembly changed during preparation. Prepare again.");};
                validate();
                progressDetail="Loading prepared hull viewport";
                // A failed/closed viewport must not discard a successfully prepared hull.
                string previewError=null;
                try {await PreviewWindow().ShowExactAsync(Path.Combine(output,"mochi_hull.off"),cancellation.Token);}
                catch(OperationCanceledException) when(!cancellation.IsCancellationRequested){previewError="Preview window closed. Prepared hull retained.";}
                catch(Exception error) when(!(error is OperationCanceledException)){previewError="Preview unavailable: "+error.Message;pendingLog.Enqueue(error.ToString());}
                cancellation.Token.ThrowIfCancellationRequested();validate();
                prepared=output;preparedStamp=stamp;previewStamp=stamp;preparedFixedGeneration=fixedGeneration;
                preparedMaterials=JsonFile.Read<MaterialSnapshot>(Path.Combine(meshes,"material-snapshot.json")).Fingerprint();
                RefreshMaterials();if(prepared==null)throw new InvalidOperationException("Materials changed during preparation. Prepare again.");
                status.Text=previewError??(fixedGeneration!=null?"Prepared hull ready. Existing nodes and beams retained for refitting.":"Prepared hull ready for review.");
            }
            catch(OperationCanceledException){taskResult="Cancelled";status.Text="Preparation stopped.";}
            catch(Exception e){taskResult="Failed";status.Text=e.Message;log.AppendText(e+System.Environment.NewLine);}
            finally{cancellation.Dispose();cancellation=null;Busy(false);if(closing)Close();}
        }
        private IProgress<string> ProgressLog()=>new WorkerProgress(line=>pendingLog.Enqueue(line));
        private async System.Threading.Tasks.Task PrepareMountPlan(string output,CancellationToken token)
        {
            status.Text="Checking vehicle hardpoints for generation…";progressDetail="Mounting definition";
            var vehicleProject=settings.ProjectForDocument(selection.Document);
            var progress=ProgressLog();
            if(vehicleProject.JointWorkspace.Mode=="authored")
            {
                await JointReview.Refresh(app,model,vehicleProject,settings,progress,token);
                var anchors=new MountAnchors(app,model);
                foreach(var anchor in vehicleProject.Anchors){token.ThrowIfCancellationRequested();anchors.Update(anchor);}
                vehicleProject.Save();
            }
            if(vehicleProject.JointWorkspace.Mode=="authored"||!string.IsNullOrWhiteSpace(vehicleProject.TemplateDefinitionPath))
                await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Path.Combine(Path.GetDirectoryName(typeof(FrameWorkflow).Assembly.Location),"FramePipeline","component_worker.py"),
                    "mount-plan --project "+OwnedWorker.Quote(vehicleProject.FilePath)+" --output "+OwnedWorker.Quote(Path.Combine(output,"frame-mounts.json")),progress,token,null,settings.FrameOutput);
            else if(File.Exists(Path.Combine(output,"frame-mounts.json")))
                throw new InvalidOperationException("Mounting definition changed since the previous generation attempt. Prepare the frame again.");
        }
        private async void StartGeneration()
        {
            if(IsBusy||prepared==null)return;
            var reviewAfterBuild=false;
            mountPlanProblem=null;fixturesApproved=false;
            cancellation=new CancellationTokenSource();Busy(true);
            try{
                settings=new ExporterSettings(null);
                generation=null;
                ValidateGeneration();
                if(model.GetUpdateStamp()!=preparedStamp){InvalidatePreview();throw new InvalidOperationException("CAD changed since preparation. Prepare the frame again.");}
                RefreshMaterials();if(prepared==null)throw new InvalidOperationException("Materials changed; prepare the frame again.");
                try {await PrepareMountPlan(prepared,cancellation.Token);}
                catch(InvalidOperationException error)
                {
                    var reason=error.Message.Split(new[]{'\r','\n'},StringSplitOptions.RemoveEmptyEntries).FirstOrDefault()??"Check the current mounting definition.";
                    mountPlanProblem=reason.StartsWith("Bind required CAD hardpoints",StringComparison.Ordinal)
                        ?"Bind the missing CAD hardpoints in Joints. The Preparation log lists them."
                        :reason.Length>240?reason.Substring(0,237)+"... See Preparation log.":reason;
                    throw;
                }
                ValidateGeneration();
                if(model.GetUpdateStamp()!=preparedStamp){InvalidatePreview();throw new InvalidOperationException("CAD changed during mounting review. Prepare the frame again.");}
                if(preparedFixedGeneration!=null)
                    await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Path.Combine(Path.GetDirectoryName(typeof(FrameWorkflow).Assembly.Location),"FramePipeline","calibration_worker.py"),
                        "fixed-preview --job "+OwnedWorker.Quote(preparedFixedGeneration)+" --source "+OwnedWorker.Quote(prepared),ProgressLog(),cancellation.Token,null,settings.FrameOutput);
                generation=await CalibrationBuilder.PrepareAsync(settings,prepared,ProgressLog(),cancellation.Token);
                settings.LastCalibrationGeneration=generation;settings.Save();
                status.Text="Generation prepared. Orientation and fixtures need review.";
                reviewAfterBuild=true;
            }catch(OperationCanceledException){taskResult="Cancelled";status.Text="Generation stopped.";}
            catch(Exception e){taskResult="Failed";status.Text=e.Message.IndexOf("Bind required CAD hardpoints",StringComparison.Ordinal)>=0?
                "Required vehicle hardpoints are missing. Open Joints to bind them, then accept this prepared hull again. Details are in Preparation log.":e.Message;log.AppendText(e+System.Environment.NewLine);}
            finally
            {
                cancellation.Dispose();cancellation=null;Busy(false);
                if(closing)Close();
                else if(reviewAfterBuild)Try(ReviewFixtures);
            }
        }
        private void ReviewFixtures()
        {
            if(IsBusy||generation==null)return;
            using(var review=new FixtureReview(Path.Combine(generation,"review.json")))
                if(review.ShowDialog(this)==DialogResult.OK)fixturesApproved=true;
            status.Text=fixturesApproved?"Orientation and fixtures approved for this generation. Calibrate next.":"Fixtures need review before calibration.";
        }
        private async void RunCalibration(bool live,bool diagnostic=false)
        {
            if(IsBusy||generation==null)return;
            cancellation=new CancellationTokenSource();Busy(true);tabs.SelectedTab=logTab;
            try{
                status.Text=live?"Verifying this generation in the isolated BeamNG profile...":"Auditing CAD bodies and fitting this generation's graph...";
                var selected=(string)materialCase.SelectedItem;
                if(live)await CalibrationBuilder.VerifyModeAsync(settings,generation,selected,diagnostic?"full":verificationMode.SelectedIndex==0?"quick":"full",ProgressLog(),cancellation.Token,diagnostic);
                else await CalibrationBuilder.CalibrateSelectedAsync(settings,generation,selected,ProgressLog(),cancellation.Token);
                FlushLog();
                status.Text=studyOutcome??"Study finished. Open the build result for generation, recording and qualification results.";
                var report=Path.Combine(generation,"study","index.html");
                if(File.Exists(report) && (!live || diagnostic || verificationMode.SelectedIndex==1))System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(report){UseShellExecute=true});
            }catch(OperationCanceledException){taskResult="Cancelled";status.Text="Calibration / verification stopped; completed evidence retained.";}
            catch(Exception e){taskResult="Failed";status.Text=e.Message;log.AppendText(e+System.Environment.NewLine);}
            finally{cancellation.Dispose();cancellation=null;Busy(false);if(closing)Close();}
        }
        private async void Package()
        {
            if(IsBusy||generation==null)return;
            var selected=(string)materialCase.SelectedItem;
            cancellation=new CancellationTokenSource();Busy(true);
            try{
                settings=new ExporterSettings(null);
                var project=settings.ProjectForDocument(selection.Document);
                settings.LastBuildReceipt=await CalibrationBuilder.PackageProjectAsync(settings,generation,selected,project,ProgressLog(),cancellation.Token);
                project.SelectFrameBuild(settings.LastBuildReceipt);settings.LastProjectPath=project.FilePath;settings.Save();
                status.Text="Calibrated package created. Qualification is shown in Manage Mod; use it to customize or install.";
            }catch(OperationCanceledException){taskResult="Cancelled";status.Text="Packaging stopped.";}
            catch(Exception e){taskResult="Failed";status.Text=e.Message;log.AppendText(e+System.Environment.NewLine);}
            finally{cancellation.Dispose();cancellation=null;Busy(false);if(closing)Close();}
        }
    }
}
