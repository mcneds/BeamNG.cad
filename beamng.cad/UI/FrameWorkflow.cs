using System;
using System.Drawing;
using System.IO;
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
        private readonly FrameSelection selection;
        private readonly ModelDoc2 model;
        private readonly ISldWorks app;
        private ExporterSettings settings;
        private PreparationFile preparation;
        private FrameAssignment frame;
        internal bool IsForDocument(string document)=>ComponentAssignments.SameDocument(document,selection.Document);
        private readonly TextBox summary = new TextBox { Multiline=true, ReadOnly=true, ScrollBars=ScrollBars.Vertical, Dock=DockStyle.Fill };
        private readonly TextBox log = new TextBox { Multiline=true, ReadOnly=true, ScrollBars=ScrollBars.Vertical, Dock=DockStyle.Fill };
        private readonly Label status = new Label { AutoSize=true, Dock=DockStyle.Top };
        private readonly FlowLayoutPanel controls = new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Top, FlowDirection=FlowDirection.TopDown, WrapContents=false };
        private readonly HullOptionsPanel hullOptions = new HullOptionsPanel();
        private readonly TabControl tabs = new TabControl { Dock=DockStyle.Fill };
        private readonly TabPage logTab = new TabPage("Preparation log");
        private readonly CheckBox showHull = new CheckBox {Name="ShowHullOverlay",Text="Show hull overlay",AutoSize=true,Checked=true,Enabled=false};
        private bool syncingHullVisibility;
        private readonly Button accept;
        private readonly Button stop;
        private CancellationTokenSource cancellation;
        private HullPreview preview;
        private ComponentWorkflow componentWindow;
        private string prepared;
        private string generation;
        private string requestedFixedGeneration;
        private readonly ComboBox materialCase=new ComboBox {Name="CalibrationCase",DropDownStyle=ComboBoxStyle.DropDownList,Width=160};
        private readonly TextBox materialSummary=new TextBox {Name="SolidWorksMaterials",Multiline=true,ReadOnly=true,Dock=DockStyle.Fill,ScrollBars=ScrollBars.Both,WordWrap=false};
        private string preparedMaterials;
        private readonly FlowLayoutPanel materialActions=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Fill};
        private bool materialPicking;
        private readonly ComboBox verificationMode=new ComboBox {Name="VerificationMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=200};
        private readonly Button fixtures,calibrate,package,verify,diagnostics;
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
            if(taskElapsed.IsRunning)progressText.Text=progressDetail+"\r\n"+batchDetail+" | Elapsed "+taskElapsed.Elapsed.ToString(@"hh\:mm\:ss");
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
            settings=new ExporterSettings(null);preparation=PreparationFile.Load(selection.Document);frame=preparation.Frame(selection.Configuration);
            Text="beamng.cad - Frame";Width=780;Height=900;MinimumSize=new Size(680,620);ShowInTaskbar=false;
            var layout=new TableLayoutPanel { Dock=DockStyle.Fill, ColumnCount=1, RowCount=4, Padding=new Padding(10) };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Controls.Add(layout);
            controls.Controls.Add(new Label { AutoSize=true, MaximumSize=new Size(560,0), Text="Select bodies, faces, body/cut-list folders, or components in SolidWorks. Faces select their owning body; folders select their contained bodies. Generated meshes stay external." });
            var actions=new FlowLayoutPanel { AutoSize=true };
            AddButton(actions,"Use current selection",CaptureSelection);AddButton(actions,"Show saved selection",()=>selection.Show(frame));
            AddButton(actions,"Remove assignment",()=> { preparation.Assignments.RemoveAll(a=>a.Configuration==selection.Configuration && a.Role=="frame");JsonFile.Write(PreparationFile.FileName(selection.Document),preparation);frame=null;InvalidatePreview();summary.Clear(); });
            controls.Controls.Add(actions);layout.Controls.Add(controls,0,0);
            var storage=new FlowLayoutPanel {AutoSize=true,MaximumSize=new Size(680,0)};
            var buildPath=new TextBox {Name="BuildDirectory",ReadOnly=true,Width=470,Text=settings.FrameOutput};
            storage.Controls.Add(new Label {Text="Build directory",AutoSize=true});storage.Controls.Add(buildPath);
            AddButton(storage,"Choose build directory...",()=>{
                using(var picker=new FolderBrowserDialog {Description="Store new CAD exports, builds and test evidence here",SelectedPath=settings.FrameOutput,ShowNewFolderButton=true})
                    if(picker.ShowDialog(this)==DialogResult.OK){settings.FrameOutput=BuildStorage.EnsureDirectory(picker.SelectedPath);settings.Save();buildPath.Text=settings.FrameOutput;status.Text="New builds will use "+settings.FrameOutput+". Existing generations keep their current paths.";}
            });controls.Controls.Add(storage);
            var saveReports=new CheckBox {Name="SaveBuildReports",Text="Save full build report (failures are always kept)",AutoSize=true,Checked=settings.SaveBuildReports=="true"};
            saveReports.CheckedChanged+=(s,e)=>{settings.SaveBuildReports=saveReports.Checked?"true":"false";settings.Save();};controls.Controls.Add(saveReports);
            var selectionTab=new TabPage("Selected geometry");selectionTab.Controls.Add(summary);
            var hullTab=new TabPage("Hull settings");hullTab.Controls.Add(hullOptions);
            var materialTab=new TabPage("SolidWorks materials");
            var materialLayout=new TableLayoutPanel {Dock=DockStyle.Fill,RowCount=2,ColumnCount=1};
            materialLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));materialLayout.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            AddButton(materialActions,"Set material for current selection",()=>SetMaterials(false));
            AddButton(materialActions,"Set material for saved frame",()=>SetMaterials(true));
            AddButton(materialActions,"Refresh materials",()=>{if(cancellation==null)RefreshMaterials();});
            materialActions.Controls.Add(new Label {AutoSize=true,MaximumSize=new Size(650,0),Text="Choose a material, click Apply, then Close. Shared part/configuration instances share body materials. Changes remain unsaved until you save your CAD documents."});
            materialLayout.Controls.Add(materialActions,0,0);materialLayout.Controls.Add(materialSummary,0,1);materialTab.Controls.Add(materialLayout);
            logTab.Controls.Add(log);tabs.TabPages.AddRange(new[]{selectionTab,hullTab,materialTab,logTab});tabs.SelectedTab=hullTab;
            layout.Controls.Add(tabs,0,1);
            var parameters=new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Top, MaximumSize=new Size(580,0) };
            parameters.Controls.Add(new Label { AutoSize=true, MaximumSize=new Size(560,0), Text="Physical materials come from the selected bodies' SolidWorks assignments. Select bodies/components in SolidWorks to edit their materials explicitly; Refresh reads them without changes." });
            AddButton(parameters,"Prepare / preview frame",()=>Prepare());
            AddButton(parameters,"Refit on existing frame graph",()=>{
                if(cancellation!=null)return;
                using(var picker=new OpenFileDialog {Filter="Generation review (review.json)|review.json",Title="Choose the frame generation whose nodes and beams must remain fixed"})
                    if(picker.ShowDialog(this)==DialogResult.OK){GenerationReview.Load(picker.FileName);requestedFixedGeneration=Path.GetDirectoryName(picker.FileName);Prepare();}
            });
            accept=AddButton(parameters,"Accept hull / review fixtures",()=>StartGeneration());accept.Enabled=false;
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
                    if(picker.ShowDialog(this)==DialogResult.OK){GenerationReview.Load(picker.FileName);InvalidatePreview();generation=Path.GetDirectoryName(picker.FileName);Busy(false);status.Text="Opened immutable generation: "+generation;}
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
                var current=new ExporterSettings(null);var project=current.ProjectForDocument(selection.Document);
                new ModManager(current,null,project) {SolidWorksApplication=app}.Show(this);
            });
            AddButton(parameters,"Components / mounts",()=>{
                if(componentWindow!=null&&!componentWindow.IsDisposed){componentWindow.Activate();return;}
                componentWindow=new ComponentWorkflow(app,model);componentWindow.Show(this);
            });
            parameters.Controls.Add(showHull);
            showHull.CheckedChanged+=(s,e)=> {if(!syncingHullVisibility)ToggleHull();};
            layout.Controls.Add(parameters,0,2);layout.Controls.Add(status,0,3);
            if (frame != null)
            {
                hullOptions.Value=frame.Hull;
                summary.Text=string.Join("\r\n", frame.Selections.ConvertAll(s=>s.Name));
                status.Text="Restored saved frame selection and hull settings for '"+selection.Configuration+"'. Use Components / mounts > Use saved frame to link it to your project.";
                Shown+=(s,e)=>BeginInvoke(new Action(()=>{
                    Try(()=>{
                        var timer=Stopwatch.StartNew(); summary.Text=selection.Summary(frame);
                        pendingLog.Enqueue("Selection inspection: "+timer.ElapsedMilliseconds+" ms.");
                    });
                    Try(RefreshMaterials);
                }));
            }
            hullOptions.ValueChanged+=(s,e)=>OptionsChanged();
            saveTimer.Tick+=(s,e)=> {saveTimer.Stop();if(frame!=null)Try(()=>preparation.Save(frame));};
            logTimer.Tick+=(s,e)=>FlushLog();logTimer.Start();
            FormClosing+=(s,e)=> {
                if(materialPicking) {e.Cancel=true;status.Text="Close the SolidWorks material picker first.";}
                else if(cancellation!=null) {closing=true;cancellation.Cancel();e.Cancel=true;}
                else { if(saveTimer.Enabled && frame!=null) Try(()=>preparation.Save(frame)); saveTimer.Stop();preview?.Dispose(); }
            };
            FormClosed+=(s,e)=> {saveTimer.Dispose();logTimer.Dispose();};
        }
        private Button AddButton(Control parent,string label,Action action)
        { var button=new Button { Text=label,AutoSize=true };button.Click+=(s,e)=>Try(action);parent.Controls.Add(button);return button; }
        private void Try(Action action) { try { action(); } catch(Exception e) {status.Text=e.Message;log.AppendText(e+System.Environment.NewLine);} }
        private async void SetMaterials(bool savedFrame)
        {
            if(cancellation!=null)return;
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
        private async void InvalidatePreview()
        {
            var stale=preview;preview=null;prepared=null;generation=null;
            fixtures.Enabled=calibrate.Enabled=package.Enabled=verify.Enabled=false;accept.Enabled=false;showHull.Enabled=false;
            if(stale!=null)try{await stale.DisposeAsync();}catch(Exception e){pendingLog.Enqueue("Preview cleanup: "+e.Message);}
        }
        private async void ToggleHull()
        {
            var target=preview;if(target==null)return;
            try
            {
                ValidateGeneration();var timer=Stopwatch.StartNew();await target.SetVisibleAsync(showHull.Checked);
                if(!ReferenceEquals(preview,target)||IsDisposed)return;
                ValidateGeneration();
                pendingLog.Enqueue("Hull visibility / redraw: "+timer.ElapsedMilliseconds+" ms.");
                status.Text=preview.Visible?"Hull overlay shown. Review it before accepting.":"Hull overlay hidden. The prepared hull is still available for building.";
            }
            catch(Exception e){if(!IsDisposed){status.Text=e.Message;pendingLog.Enqueue(e.ToString());}}
            finally
            {
                if(!IsDisposed && ReferenceEquals(preview,target))
                {
                    syncingHullVisibility=true;
                    try{showHull.Checked=target.Visible;}finally{syncingHullVisibility=false;}
                }
            }
        }
        private void CaptureSelection()
        {
            if(cancellation!=null) return;
            var captured=selection.Capture();var details=selection.Summary(captured);
            if(MessageBox.Show(this,details+"\r\n\r\nUse this selection as the frame?","Frame selection",MessageBoxButtons.OKCancel)!=DialogResult.OK) return;
            if(frame!=null) {captured.Id=frame.Id;captured.Hull=frame.Hull;}
            frame=captured;SaveOptions();preparation.Save(frame);InvalidatePreview();RefreshMaterials();summary.Text=details;status.Text="Frame selection and hull settings saved beside the assembly; they reload after restarting SolidWorks. In Components / mounts, choose the frame and Use saved frame.";
        }
        private void SaveOptions()
        {
            if(frame==null) return;
            frame.Hull=hullOptions.Value;
        }
        private void OptionsChanged()
        {
            if(cancellation!=null) return;InvalidatePreview();SaveOptions();
            status.Text="Hull settings changed. Prepare / preview again to review the new hull.";
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
            taskProgress.Enabled=progressText.Enabled=true;
            stop.Enabled=value;accept.Enabled=!value && prepared!=null;
            showHull.Enabled=!value && preview!=null;
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
            if(cancellation!=null) return;
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
                var vehicleProject=settings.ProjectForDocument(selection.Document);
                if(vehicleProject.JointWorkspace.Mode=="authored")
                {
                    await JointReview.Refresh(app,model,vehicleProject,settings,progress,cancellation.Token);
                    var anchors=new MountAnchors(app,model);
                    foreach(var anchor in vehicleProject.Anchors)anchors.Update(anchor);
                    vehicleProject.Save();
                }
                if(vehicleProject.JointWorkspace.Mode=="authored"||!string.IsNullOrWhiteSpace(vehicleProject.TemplateDefinitionPath))
                    await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Path.Combine(Path.GetDirectoryName(script),"component_worker.py"),
                        "mount-plan --project "+OwnedWorker.Quote(vehicleProject.FilePath)+" --output "+OwnedWorker.Quote(Path.Combine(output,"frame-mounts.json")),progress,cancellation.Token,null,settings.FrameOutput);
                if(fixedGeneration!=null)
                    await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Path.Combine(Path.GetDirectoryName(script),"calibration_worker.py"),
                        "fixed-preview --job "+OwnedWorker.Quote(fixedGeneration)+" --source "+OwnedWorker.Quote(output),progress,cancellation.Token,null,settings.FrameOutput);
                Action validate=()=> {ValidateGeneration();if(model.GetUpdateStamp()!=stamp)throw new InvalidOperationException("Assembly changed during preparation. Prepare again.");};
                validate();
                progressDetail="Creating hull preview";
                preview=await HullPreview.CreateAsync(app,model,Path.Combine(output,"mochi_hull.off"),frame.Hull.Orientation,showHull.Checked,cancellation.Token,validate,line=>pendingLog.Enqueue(line));
                prepared=output;preparedMaterials=JsonFile.Read<MaterialSnapshot>(Path.Combine(meshes,"material-snapshot.json")).Fingerprint();
                RefreshMaterials();if(prepared==null)throw new InvalidOperationException("Materials changed during preparation. Prepare again.");
                status.Text=fixedGeneration!=null?"Existing nodes and beams retained. Review this graph, accept it and calibrate against the newly captured CAD. An impossible fit will leave the old build usable.":showHull.Checked?"Review the orange hull in SolidWorks, then accept or adjust parameters. This build uses the captured geometry snapshot.":"Hull prepared. Enable Show hull overlay to review it before accepting.";
            }
            catch(OperationCanceledException){taskResult="Cancelled";status.Text="Preparation stopped.";}
            catch(Exception e){taskResult="Failed";status.Text=e.Message;log.AppendText(e+System.Environment.NewLine);}
            finally{cancellation.Dispose();cancellation=null;Busy(false);if(closing)Close();}
        }
        private IProgress<string> ProgressLog()=>new WorkerProgress(line=>pendingLog.Enqueue(line));
        private async void StartGeneration()
        {
            if(cancellation!=null||prepared==null)return;
            cancellation=new CancellationTokenSource();Busy(true);
            try{
                settings=new ExporterSettings(null);
                generation=null;
                RefreshMaterials();if(prepared==null)throw new InvalidOperationException("Materials changed; prepare the frame again.");
                generation=await CalibrationBuilder.PrepareAsync(settings,prepared,ProgressLog(),cancellation.Token);
                settings.LastCalibrationGeneration=generation;settings.Save();
                ReviewFixtures();
            }catch(OperationCanceledException){taskResult="Cancelled";status.Text="Generation stopped.";}
            catch(Exception e){taskResult="Failed";status.Text=e.Message;log.AppendText(e+System.Environment.NewLine);}
            finally{cancellation.Dispose();cancellation=null;Busy(false);if(closing)Close();}
        }
        private void ReviewFixtures()
        {
            if(generation==null)return;
            using(var review=new FixtureReview(Path.Combine(generation,"review.json")))
                status.Text=review.ShowDialog(this)==DialogResult.OK?"Orientation and fixtures approved for this generation. Calibrate next.":"Fixtures need review before calibration.";
        }
        private async void RunCalibration(bool live,bool diagnostic=false)
        {
            if(cancellation!=null||generation==null)return;
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
            if(cancellation!=null||generation==null)return;
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
