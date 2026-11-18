using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.UI
{
    // Hosted by a native SolidWorks Task Pane, not a floating parent window.
    internal sealed class ProjectWorkspace : UserControl
    {
        private readonly ISldWorks app;
        private readonly ExporterSettings preferences;
        private readonly ProjectSession session=new ProjectSession();
        private readonly Label header=new Label {Name="ProjectContext",Dock=DockStyle.Top,AutoSize=true,Padding=new Padding(6)};
        private readonly Label task=new Label {Name="WorkspaceTask",AutoSize=true};
        private readonly Label pageTitle=new Label {Name="WorkspacePage",AutoSize=true,Font=new Font(SystemFonts.MessageBoxFont,FontStyle.Bold)};
        private readonly Panel content=new Panel {Dock=DockStyle.Fill,AutoScroll=true};
        private readonly TextBox details=new TextBox {Name="WorkspaceLog",Multiline=true,ReadOnly=true,Dock=DockStyle.Bottom,Height=150,ScrollBars=ScrollBars.Both,Visible=false};
        private readonly ProgressBar progress=new ProgressBar {Width=150,Style=ProgressBarStyle.Marquee,Visible=false};
        private readonly Button stop=new Button {Text="Stop",AutoSize=true,Enabled=false};
        private readonly FlowLayoutPanel navigation=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true,WrapContents=true};
        private readonly WorkflowNextStep nextStep=new WorkflowNextStep {Visible=false};
        private readonly Lazy<MvpCatalog> catalog=new Lazy<MvpCatalog>(MvpCatalog.Load);
        private readonly Timer timer=new Timer {Interval=200};
        private VehicleReadiness readiness;
        private ComponentWorkflow components;
        private FrameWorkflow frame;
        private ModManager delivery;
        private SettingsPanel settingsPanel;
        private string stage="Overview";
        private Form activeEditor;
        private bool refreshing;
        private bool resumeAfterTask;
        private bool disposingWorkspace;
        internal bool IsBusy=>(components?.IsBusy??false)||(frame?.IsBusy??false)||(delivery?.IsBusy??false);
        internal ProjectSession Session=>session;
        internal string CurrentStage=>stage;

        public ProjectWorkspace(ISldWorks app):this(app,new ExporterSettings(null)){}
        internal ProjectWorkspace(ISldWorks app,ExporterSettings preferences)
        {
            this.preferences=preferences;
            this.app=app;Name="BeamNgProjectWorkspace";Dock=DockStyle.Fill;
            var footer=new FlowLayoutPanel {Dock=DockStyle.Bottom,AutoSize=true,WrapContents=true,Padding=new Padding(6)};
            var logs=new Button {Text="Details",AutoSize=true};logs.Click+=(s,e)=>details.Visible=!details.Visible;
            footer.Controls.Add(task);footer.Controls.Add(progress);footer.Controls.Add(stop);footer.Controls.Add(logs);
            stop.Click+=(s,e)=>{components?.StopTask();frame?.StopTask();};
            foreach(var name in new[]{"Overview","Project","Components","Joints","Driveline","Frame","Build","Verify","Delivery","Settings"})
            {var title=name;var button=new Button {Text=title,AutoSize=true,AccessibleName=title};button.Click+=(s,e)=>Navigate(title);navigation.Controls.Add(button);}
            Controls.Add(content);Controls.Add(details);Controls.Add(footer);Controls.Add(nextStep);Controls.Add(navigation);Controls.Add(header);
            nextStep.FollowRequested+=FollowNextStep;
            session.Changed+=()=>{UpdateHeader();RefreshReadiness();};
            timer.Tick+=(s,e)=>{try{if(!disposingWorkspace)UpdateTask();}catch(System.Runtime.InteropServices.COMException){task.Text="SolidWorks context unavailable. Activate the project assembly to continue.";}};timer.Start();
            Navigate("Overview");
        }
        internal bool ResolveChanges()=>!IsBusy&&(components==null||components.ResolveDraft())&&(settingsPanel==null||settingsPanel.ResolveChanges())&&(delivery==null||delivery.ResolveChanges());
        internal bool Navigate(string target)
        {
            if(!ResolveChanges()){task.Text=IsBusy?"A task is running. Stop it before changing tasks.":"Resolve pending edits to continue.";return false;}
            try
            {
                if(settingsPanel!=null){settingsPanel.Dispose();settingsPanel=null;}
                if(target!="Overview"&&target!="Project"&&target!="Settings"&&target!="Delivery"&&session.Project==null)ResumeActive();
                if(session.Project!=null&&target!="Overview"&&target!="Project"&&target!="Settings"&&target!="Delivery")
                {var problem=session.ContextProblem(app);if(problem!=null)throw new InvalidOperationException(problem);}
                if(activeEditor!=null)activeEditor.Hide();ClearContent();activeEditor=null;
                stage=target;pageTitle.Text=target;UpdateHeader();
                if(target=="Overview"){ShowOverview();return true;}
                if(target=="Settings")
                {settingsPanel=new SettingsPanel(preferences.Reload());content.Controls.Add(settingsPanel);return true;}
                if(target=="Project"){ShowProject();return true;}
                if(target=="Frame")
                {
                    if(frame==null||frame.IsDisposed){frame=new FrameWorkflow(app,session.Model);frame.NavigationRequested+=name=>Navigate(name);}
                    Host(frame);return true;
                }
                if(target=="Delivery")
                {
                    if(delivery==null||delivery.IsDisposed)
                    {
                        delivery=new ModManager(preferences.Reload(),null,session.Project) {SolidWorksApplication=app};
                        delivery.ProjectChanged+=()=>{
                            var selected=delivery.CurrentProject;if(selected==null)return;
                            if(session.Project?.FilePath!=selected.FilePath){components?.Close();frame?.Close();components=null;frame=null;session.Select(selected,session.Model);}
                            else session.Refresh();
                        };
                    }
                    delivery.RefreshForWorkspace();Host(delivery);return true;
                }
                EnsureComponents();components.ReloadProject();components.ShowStage(target);Host(components);return true;
            }
            catch(Exception error){if(activeEditor!=null)activeEditor.Hide();activeEditor=null;stage="Overview";task.Text=error.Message;ShowOverview();return false;}
            finally {UpdateNextStep();}
        }
        private void EnsureComponents()
        {
            if(components!=null&&!components.IsDisposed)return;
            components=new ComponentWorkflow(app,session.Model,preferences.Reload());
            components.FreshProjectRequested+=()=>BeginInvoke(new System.Action(NewProject));
            components.NavigationRequested+=name=>BeginInvoke(new System.Action(()=>Navigate(name)));
            components.ContextChanged+=(project,model)=>BeginInvoke(new System.Action(()=>{SelectProject(project,model);Navigate("Joints");}));
            components.ProjectChanged+=()=>
            {
                if(disposingWorkspace||refreshing)return;
                refreshing=true;
                try
                {
                    if(!ComponentAssignments.SameDocument(components.CurrentProject.SourceDocument,session.Project.SourceDocument)||components.CurrentProject.FilePath!=session.Project.FilePath)
                    {session.Select(components.CurrentProject,session.Model);frame?.Close();frame=null;delivery?.Close();delivery=null;}
                    else session.Refresh();
                }
                finally {refreshing=false;}
            };
            components.UseDockedNavigation();
        }
        private void ClearContent()
        {
            foreach(Control child in content.Controls.Cast<Control>().ToArray())
            {
                content.Controls.Remove(child);
                if(child!=components&&child!=frame&&child!=delivery)child.Dispose();
            }
        }
        private void Host(Form form)
        {
            activeEditor=form;form.TopLevel=false;form.FormBorderStyle=FormBorderStyle.None;form.MinimumSize=Size.Empty;
            form.Dock=DockStyle.Fill;content.Controls.Add(form);form.Show();
            if(form==components)components.UseDockedNavigation();
        }
        private FlowLayoutPanel Stack()
        {
            var panel=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true,FlowDirection=FlowDirection.TopDown,WrapContents=false,Padding=new Padding(8)};
            content.Controls.Add(panel);return panel;
        }
        private static void Explanation(Control parent,string text)
        {parent.Controls.Add(new Label {Text=text,AutoSize=true,MaximumSize=new Size(420,0),Margin=new Padding(3,5,3,8)});}
        private static void Action(Control parent,string text,System.Action action)
        {
            var button=new Button {Text=text,AutoSize=false,AccessibleName=text,Padding=new Padding(8,4,8,4)};
            System.Action fit=()=>{
                var available=Math.Max(100,parent.ClientSize.Width-parent.Padding.Horizontal-button.Margin.Horizontal);
                var natural=TextRenderer.MeasureText(button.Text,button.Font);
                button.Width=Math.Min(available,natural.Width+button.Padding.Horizontal+8);
                var wrapped=TextRenderer.MeasureText(button.Text,button.Font,new Size(Math.Max(1,button.Width-button.Padding.Horizontal-8),int.MaxValue),TextFormatFlags.WordBreak|TextFormatFlags.NoPrefix);
                button.Height=Math.Max((int)Math.Ceiling(32*button.DeviceDpi/96.0),wrapped.Height+button.Padding.Vertical+8);
            };
            button.Click+=(s,e)=>{try{action();}catch(Exception error){MessageBox.Show(parent,error.Message,"beamng.cad",MessageBoxButtons.OK,MessageBoxIcon.Information);}};
            parent.Controls.Add(button);parent.SizeChanged+=(s,e)=>fit();button.FontChanged+=(s,e)=>fit();fit();
        }
        private void ShowOverview()
        {
            ClearContent();var panel=Stack();panel.Controls.Add(new Label {Text="Vehicle project",AutoSize=true,Font=pageTitle.Font});
            var problem=session.ContextProblem(app);
            if(problem!=null)Explanation(panel,problem);
            if(session.Project==null)
            {
                Explanation(panel,"Start with a saved SolidWorks assembly. New from CAD creates a separate project with unassigned groups; no physics is imported or generated.");
                Action(panel,"New from CAD…",NewProject);Action(panel,"Resume current assembly",()=>{ResumeActive();Navigate("Overview");});Action(panel,"Open saved project…",OpenProject);return;
            }
            var project=session.Project;
            if(File.Exists(project.LastBuildReceipt))
            {Explanation(panel,"A package exists. Review verification evidence for its exact revision before relying on its behavior. Generation success does not establish physical qualification.");Action(panel,"Verify package",()=>Navigate("Verify"));Action(panel,"Review delivery",()=>Navigate("Delivery"));}
            var pending=project.Components.Count(c=>c.AppearancePackageState=="pending"||c.AppearancePackageState=="failed");
            if(pending>0){Explanation(panel,pending+" groups have pending appearance updates. These are separate from physical CAD and spring changes.");Action(panel,"Update saved appearances",()=>Navigate("Build"));}
            Action(panel,"Project setup / start fresh",()=>Navigate("Project"));
        }
        private void ShowProject()
        {
            var panel=Stack();Explanation(panel,"Project setup. Starting fresh preserves all earlier projects and packages.");
            Action(panel,"New from CAD…",NewProject);Action(panel,"Open saved project…",OpenProject);Action(panel,"Resume current assembly",()=>{ResumeActive();Navigate("Project");});
            if(session.Project!=null)
            {
                Action(panel,"Vehicle layout and project tools...",OpenProjectTools);
                Explanation(panel,"Reviewed JSON definitions and physics imports remain supported. Use the layout/import editor for those routes; they do not infer hardpoints from visible geometry.");
            }
        }
        private void OpenProjectTools()
        {
            var problem=session.ContextProblem(app);
            if(problem!=null)throw new InvalidOperationException(problem);
            EnsureComponents();components.ReloadProject();
            ClearContent();components.ShowStage("Project");Host(components);
        }
        private void RefreshReadiness()
        {
            try {readiness=session.Project==null?null:VehicleReadiness.Evaluate(session.Project,catalog.Value,session.Configuration);}
            catch(Exception error) when(error is IOException||error is InvalidOperationException||error is ArgumentException||error is System.Runtime.Serialization.SerializationException)
            {
                readiness=new VehicleReadiness {Title="Review vehicle setup",Detail=error.Message,Stage="Project",ActionText="Open project tools"};
            }
            UpdateNextStep();
        }
        private VehicleReadiness CurrentNextStep()
        {
            if(readiness==null||stage=="Settings"||stage=="Verify"||stage=="Delivery"||stage=="Log")return null;
            if(stage=="Frame"&&frame!=null)return frame.NextFrameStep(readiness,session.Project);
            return readiness;
        }
        private void UpdateNextStep()
        {
            var state=CurrentNextStep();
            nextStep.ShowState(state,stage=="Frame"?frame?.PreviewStatus:null,IsBusy);
        }
        private void FollowNextStep()
        {
            var state=CurrentNextStep();
            if(state==null)return;
            try
            {
                if(stage!=state.Stage||activeEditor==null)
                {
                    if(!Navigate(state.Stage))return;
                }
                else if(!ResolveChanges())return;
                if(state.Stage=="Project"&&session.Project!=null&&activeEditor!=components)OpenProjectTools();
                if(state.OpenAppearances)components.ShowAppearanceAssignments();
                else if(state.Stage=="Components"&&!string.IsNullOrEmpty(state.ComponentId))components.FocusComponent(state.ComponentId);
                if(state.Stage=="Frame")frame?.OpenNextFrameAction();
            }
            catch(Exception error) {task.Text=error.Message;MessageBox.Show(this,error.Message,"beamng.cad",MessageBoxButtons.OK,MessageBoxIcon.Information);}
        }
        private ModelDoc2 ActiveAssembly()
        {
            var model=app.ActiveDoc as ModelDoc2;
            if(model==null)throw new InvalidOperationException("Open and save your top-level assembly first.");
            new FrameSelection(app,model).ValidateDocument();return model;
        }
        private void ResumeActive()
        {
            var model=ActiveAssembly();var settings=preferences.Reload();SelectProject(settings.ProjectForDocument(model.GetPathName()),model);
        }
        private void NewProject()
        {
            if(!ResolveChanges())return;
            var model=ActiveAssembly();
            using(var mode=new Form {Text="New CAD project — authoring method",Width=480,Height=210,StartPosition=FormStartPosition.CenterParent})
            {
                var native=new RadioButton {Text="Native CAD mates and hardpoints (recommended)",Checked=true,Dock=DockStyle.Top,Height=35};
                var reviewed=new RadioButton {Text="Reviewed template JSON mounting definition",Dock=DockStyle.Top,Height=35};
                var next=new Button {Text="Choose project location…",Dock=DockStyle.Bottom,DialogResult=DialogResult.OK,Height=32};
                mode.Controls.Add(reviewed);mode.Controls.Add(native);mode.Controls.Add(next);mode.AcceptButton=next;
                if(mode.ShowDialog(this)!=DialogResult.OK)return;
                using(var picker=new SaveFileDialog {Filter="Vehicle project|*.beamng-project.json",FileName=Path.GetFileNameWithoutExtension(model.GetPathName())+"-new.beamng-project.json",InitialDirectory=Path.GetDirectoryName(model.GetPathName())})
                {
                    if(picker.ShowDialog(this)!=DialogResult.OK)return;
                    var project=VehicleProject.CreateFresh(model.GetPathName(),picker.FileName,MvpCatalog.Load(),native.Checked?"authored":"legacy");
                    SelectProject(project,model);Navigate("Project");
                }
            }
        }
        private void OpenProject()
        {
            if(!ResolveChanges())return;
            using(var picker=new OpenFileDialog {Filter="Vehicle project|*.beamng-project.json;*.json"})
            {
                if(picker.ShowDialog(this)!=DialogResult.OK)return;
                var project=VehicleProject.Load(picker.FileName);var model=app.ActiveDoc as ModelDoc2;
                if(model!=null&&!ComponentAssignments.SameDocument(model.GetPathName(),project.SourceDocument))model=null;
                SelectProject(project,model);Navigate("Overview");
            }
        }
        private void SelectProject(VehicleProject project,ModelDoc2 model)
        {
            if(IsBusy)throw new InvalidOperationException("Wait for the running task to finish.");
            components?.Close();frame?.Close();delivery?.Close();components=null;frame=null;delivery=null;activeEditor=null;
            var settings=preferences.Reload();settings.SelectProject(project);settings.LastBuildReceipt=project.LastBuildReceipt;settings.Save();session.Select(project,model);
        }
        private void UpdateHeader()
        {
            var project=session.Project;
            header.Text=project==null?"beamng.cad — choose a vehicle project":stage+" | "+Path.GetFileName(project.FilePath)+"\r\n"+Path.GetFileName(project.SourceDocument)+" | "+(session.Configuration??"source assembly inactive")+"\r\nPackage: "+session.PackageLabel+"\r\n"+(session.ContextProblem(app)??"CAD context current");
            header.MaximumSize=new Size(Math.Max(180,ClientSize.Width-12),0);
        }
        private void UpdateTask()
        {
            var busy=IsBusy;navigation.Enabled=!busy;stop.Enabled=busy&&!(delivery?.IsBusy??false);progress.Visible=busy;
            if(activeEditor!=null&&activeEditor==components){task.Text=components.TaskMessage;details.Text=components.TaskLog;}
            else if(activeEditor!=null&&activeEditor==frame){task.Text=frame.TaskMessage;details.Text=frame.TaskLog;}
            else if(activeEditor!=null&&activeEditor==delivery){task.Text=delivery.TaskMessage;details.Text=delivery.TaskLog;}
            if(busy)resumeAfterTask=true;
            else if(resumeAfterTask){resumeAfterTask=false;session.Refresh();}
            UpdateHeader();
            UpdateNextStep();
            task.MaximumSize=new Size(Math.Max(180,ClientSize.Width-24),0);
            if(components!=null)components.HideDockedTaskControls();
            if(frame!=null)frame.HideDockedTaskControls();
        }
        internal bool PrepareToClose()
        {
            if(IsBusy){StopTask();task.Text="Stopping. Wait for cleanup before closing the add-in.";return false;}
            return ResolveChanges();
        }
        internal void StopTask(){components?.StopTask();frame?.StopTask();}
        protected override void OnResize(EventArgs e){base.OnResize(e);if(header!=null)UpdateHeader();}
        protected override void Dispose(bool disposing)
        {
            if(disposing){disposingWorkspace=true;timer.Dispose();components?.Dispose();frame?.Dispose();delivery?.Dispose();settingsPanel?.Dispose();}
            base.Dispose(disposing);
        }
    }
}
