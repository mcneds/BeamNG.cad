param(
 [string]$OutputDirectory=(Join-Path $PSScriptRoot '../beamng.cad/bin/Debug/net472'),
 [string]$Destination=(Join-Path $PSScriptRoot ('../artifacts/project-workspace-'+[Guid]::NewGuid().ToString('N'))),
 [switch]$Native
)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Run with 64-bit Windows PowerShell -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a fresh owned fixture directory'}
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Drawing','System.Windows.Forms','System.Web.Extensions',
 (Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Drawing;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class ProjectWorkspaceTest {
 const BindingFlags Flags=BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic;
 static Assembly code;static string output;static List<string> passed=new List<string>();static List<string> uiErrors=new List<string>();
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int r,out IRunningObjectTable t);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int r,out IBindCtx c);
 delegate bool WindowCallback(IntPtr window,IntPtr data);
 [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback,IntPtr data);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint process);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr window,System.Text.StringBuilder text,int size);
 [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window,uint message,IntPtr w,IntPtr l);
 public static ISldWorks Find(int pid){
  IRunningObjectTable table;IBindCtx ctx;GetRunningObjectTable(0,out table);CreateBindCtx(0,out ctx);IEnumMoniker list;table.EnumRunning(out list);var m=new IMoniker[1];
  try{while(list.Next(1,m,IntPtr.Zero)==0){try{string n;m[0].GetDisplayName(ctx,null,out n);if(n=="SolidWorks_PID_"+pid){object app;table.GetObject(m[0],out app);return (ISldWorks)app;}}finally{Marshal.ReleaseComObject(m[0]);}}return null;}
  finally{Marshal.ReleaseComObject(list);Marshal.ReleaseComObject(ctx);Marshal.ReleaseComObject(table);}
 }
 static object New(string name,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+name),Flags,null,args,null);}
 static object Field(object obj,string name){return obj.GetType().GetField(name,Flags).GetValue(obj);}
 static void SetField(object obj,string name,object value){obj.GetType().GetField(name,Flags).SetValue(obj,value);}
 static object Call(object obj,string name,params object[] args){return obj.GetType().GetMethod(name,Flags).Invoke(obj,args);}
 static object Prop(object obj,string name){return obj.GetType().GetProperty(name,Flags).GetValue(obj,null);}
 static IEnumerable<Control> All(Control root){foreach(Control c in root.Controls){yield return c;foreach(var nested in All(c))yield return nested;}}
 static Control Named(Control root,string name){return All(root).Single(c=>c.Name==name);}
 static void Check(bool ok,string text){if(!ok)throw new Exception(text);passed.Add(text);Console.WriteLine("PASS "+text);}
 static void Pump(int ms){var end=DateTime.UtcNow.AddMilliseconds(ms);while(DateTime.UtcNow<end){Application.DoEvents();System.Threading.Thread.Sleep(10);}}
 static void Answer(int answer,Action action){
  using(var timer=new System.Windows.Forms.Timer {Interval=30}){
   var found=false;timer.Tick+=(s,e)=>EnumWindows((window,data)=>{uint owner;GetWindowThreadProcessId(window,out owner);var name=new System.Text.StringBuilder(80);GetClassName(window,name,80);if(owner==(uint)System.Diagnostics.Process.GetCurrentProcess().Id&&name.ToString()=="#32770"){found=true;PostMessage(window,0x111,new IntPtr(answer),IntPtr.Zero);}return true;},IntPtr.Zero);
   timer.Start();action();timer.Stop();Check(found,"owned pending-change prompt appeared");
  }
 }
 static void Show(Form form){form.StartPosition=FormStartPosition.Manual;form.Location=new Point(-20000,-20000);form.ShowInTaskbar=false;form.Show();Pump(30);}
 static void Capture(Control control,string name){using(var image=new Bitmap(control.Width,control.Height)){control.DrawToBitmap(image,new Rectangle(0,0,control.Width,control.Height));image.Save(Path.Combine(output,name+".png"));}}
 static object Catalog(){return code.GetType("BeamNG.Cad.Preparation.MvpCatalog").GetMethod("Load").Invoke(null,null);}
 static object Fresh(string document,string name){return code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("CreateFresh").Invoke(null,new object[]{document,Path.Combine(output,name+".json"),Catalog(),"authored"});}
 static object Settings(string name){return New("UI.ExporterSettings",Path.Combine(output,name+".xml"));}
 public static void Init(string dll,string folder){code=Assembly.LoadFrom(dll);output=folder;Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);Application.ThreadException+=(sender,args)=>{uiErrors.Add(args.Exception.ToString());Console.WriteLine("UI EXCEPTION: "+args.Exception);};Application.EnableVisualStyles();Control.CheckForIllegalCrossThreadCalls=true;}
 public static void Offline(){
  var settings=Settings("offline-settings");var path=Path.Combine(output,"offline-settings.xml");
  using(var form=new Form {Width=650,Height=700}){
   var panel=(Control)New("UI.SettingsPanel",settings);form.Controls.Add(panel);Show(form);
   var python=(TextBox)Named(panel,"PythonExecutable");python.Text="invalid-draft";Pump(650);
   Check(!File.Exists(path),"typing and timer do not persist settings");
   Check(!(bool)Call(panel,"ApplyChanges")&&!File.Exists(path),"invalid changed executable cannot be applied");
   python.Text=System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName;
   Check((bool)Call(panel,"ApplyChanges")&&File.Exists(path),"explicit Apply persists a valid changed field without requiring unrelated optional tools");
   var saved=File.ReadAllBytes(path);python.Text="cancelled-draft";Answer(2,()=>Check(!(bool)Call(panel,"ResolveChanges"),"Cancel retains pending settings"));
   Answer(7,()=>Check((bool)Call(panel,"ResolveChanges"),"Discard resolves settings"));
   Check(File.ReadAllBytes(path).SequenceEqual(saved),"Discard settings leaves saved bytes unchanged");
   var other=Call(settings,"Reload");other.GetType().GetProperty("LastBuildReceipt").SetValue(other,"other-panel-receipt",null);Call(other,"Save");
   ((TextBox)Named(panel,"SettingsFrameOutput")).Text=Path.Combine(output,"new-builds");
   Check((bool)Call(panel,"ApplyChanges")&&(string)Prop(Call(settings,"Reload"),"LastBuildReceipt")=="other-panel-receipt","Apply preserves another panel's unrelated settings");
   Capture(form,"settings-explicit-apply");
  }
  var document=Path.Combine(output,"persistence-only.SLDASM");File.WriteAllText(document,"Never opened in CAD");var project=Fresh(document,"offline-project");
  Check((string)Field(Field(project,"JointWorkspace"),"Mode")=="authored"&&((IList)Field(project,"Components")).Count>0,"fresh CAD project has unassigned groups and explicit native authoring");
  Check(string.IsNullOrEmpty((string)Field(project,"LastBuildReceipt"))&&string.IsNullOrEmpty((string)Field(project,"PhysicsTemplateReceipt")),"fresh project does not import or generate physics");
  var guide=(Control)New("UI.ReferenceSkeleton");
  using(var panel=(Control)New("UI.JointWorkspacePanel",guide,new TabPage(),new TabPage()))
  using(var host=new Form {Width=650,Height=700}){
   host.Controls.Add(panel);Call(panel,"Configure",Catalog(),project);Show(host);
   var list=(ListBox)Named(panel,"JointRequests");list.SelectedIndex=0;
   var bind=All(panel).OfType<Button>().Single(b=>b.Text=="Bind reviewed joint");Check(!bind.Enabled,"binding explains missing approved joint prerequisite");
   var request=Prop(panel,"SelectedRequest");var owner=((IEnumerable)Field(project,"Components")).Cast<object>().Single(c=>(string)Field(c,"MvpRole")==((string)Field(request,"Role")));
   var joint=New("Preparation.JointDefinition");SetField(joint,"Id","audit-joint");SetField(joint,"Name","Reviewed fixture joint");SetField(joint,"Status","approved");SetField(joint,"Parent",(string)Field(owner,"Id"));SetField(joint,"Center",new double[]{0,0,0});
   ((IList)Field(Field(project,"JointWorkspace"),"Joints")).Add(joint);Call(panel,"Configure",Catalog(),project);list.SelectedIndex=0;
   Check(bind.Enabled,"reviewed-joint binding is enabled for an eligible request");
   int calls=0;Action<object> handler=r=>calls++;panel.GetType().GetEvent("BindJointRequested").AddEventHandler(panel,handler);bind.PerformClick();Check(calls==1,"request binding invokes the handler");
   list.SelectedItem=list.Items.Cast<object>().Single(entry=>Field(entry,"Joint")==joint);Check(!bind.Enabled,"joint-only rows cannot invoke request binding");
   Capture(host,"joint-eligibility");
  }
  using(var form=new Form {Width=450,Height=800}){
   var dock=(Control)New("UI.DockedProjectHost");form.Controls.Add(dock);
   var panel=(Control)New("UI.ProjectWorkspace",null,Settings("workspace-settings"));dock.Controls.Add(panel);Show(form);
   foreach(var width in new[]{320,670,450}){
    form.ClientSize=new Size(width,800);dock.Hide();dock.Show();Call(dock,"RefreshAfterDocking");Pump(50);
    Check(dock.Bounds==form.ClientRectangle&&panel.Bounds==dock.ClientRectangle,"reopened dock fills its host at width "+width);
   }
   Check((bool)Call(panel,"Navigate","Settings"),"workspace opens Settings without a CAD assembly");
   Check((bool)Call(panel,"Navigate","Overview"),"workspace returns to project start without creating a project");
   Pump(450);Check(Prop(Prop(panel,"Session"),"Project")==null,"opening the workspace does not select or create a CAD project");Capture(form,"workspace-start");
  }
 }
 public static void Native(int pid){
  var app=Find(pid);var model=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
  if(model==null)throw new Exception("No assembly template");var document=Path.Combine(output,"native-fixture.SLDASM");int err=0,warn=0;
  Check(model.Extension.SaveAs(document,0,1,null,ref err,ref warn),"owned native assembly saved");
  var project=Fresh(document,"native-project");var settings=Settings("native-settings");Call(settings,"SelectProject",project);Call(settings,"Save");
  using(var form=(Form)New("UI.ComponentWorkflow",app,model,settings)){
   Show(form);Call(form,"ShowStage","Components");
   var list=(ListBox)Named(form,"Components");list.SelectedIndex=1;var original=list.SelectedItem;var name=(TextBox)Named(form,"ComponentName");var originalName=name.Text;name.Text="Pending engine";
   Check((bool)Prop(form,"HasPendingChanges"),"component edits are visibly pending");Answer(2,()=>list.SelectedIndex=2);
   Check(list.SelectedItem==original&&name.Text=="Pending engine","cancelled selection change preserves owner and draft");
   var thickness=(NumericUpDown)Named(form,"SurfaceThickness");thickness.Value=2;
   ((Button)Named(form,"ApplyComponentChanges")).PerformClick();
   Check(!(bool)Prop(form,"HasPendingChanges")&&(string)Field(list.SelectedItem,"Name")=="Pending engine"&&Math.Abs((double)Field(list.SelectedItem,"Thickness")-.002)<1e-9,"Apply commits the complete named component draft");
   name.Text="Discard me";((Button)Named(form,"DiscardComponentChanges")).PerformClick();Check(name.Text=="Pending engine","Discard restores saved component fields");
   name.Text="Keep me";var search=(TextBox)Named(form,"ComponentSearch");Answer(2,()=>search.Text="no-match");Check(search.Text==""&&name.Text=="Keep me","cancelled search retains selection and pending edit");
   Answer(7,()=>list.SelectedIndex=2);Check(list.SelectedItem!=original&&!(bool)Prop(form,"HasPendingChanges"),"discard permits selection change");
   name.Text="";((Button)Named(form,"ApplyComponentChanges")).PerformClick();Check((bool)Prop(form,"HasPendingChanges"),"invalid Apply preserves the draft");((Button)Named(form,"DiscardComponentChanges")).PerformClick();
   var previousCount=list.Items.Count;var previousOwner=list.SelectedItem;var previousName=(string)Field(previousOwner,"Name");
   using(var dialogTimer=new System.Windows.Forms.Timer {Interval=30}){
    dialogTimer.Tick+=(sender,args)=>{var dialog=Application.OpenForms.Cast<Form>().FirstOrDefault(f=>f.Text=="New CAD group");if(dialog==null)return;((TextBox)Named(dialog,"NewGroupName")).Text="Manual panel";All(dialog).OfType<Button>().Single(b=>b.Text=="Create empty group").PerformClick();};
    dialogTimer.Start();Call(form,"NewTaggedGroup");dialogTimer.Stop();
   }
   Check(list.Items.Count==previousCount+1&&(string)Field(previousOwner,"Name")==previousName,"new-group dialog creates a separate owner without renaming the old group");
   form.MinimumSize=Size.Empty;form.Size=new Size(450,800);Pump(100);
   var footer=(Control)Field(form,"draftFooter");Check(footer.Visible&&footer.Height>0&&footer.Bottom<=form.ClientSize.Height,"draft footer remains reachable at narrow width");Capture(form,"components-narrow");
  }
  using(var form=(Form)New("UI.FrameWorkflow",app,model)){
   Show(form);var diagnostics=All(form).OfType<Button>().Single(b=>b.Text=="Run diagnostics in BeamNG");Check(!diagnostics.Enabled,"empty Frame disables diagnostics immediately");
  }
  using(var form=new Form {Width=500,Height=850}){
   var panel=(Control)New("UI.ProjectWorkspace",app,settings);form.Controls.Add(panel);Show(form);Call(panel,"SelectProject",project,model);
   foreach(var stage in new[]{"Components","Joints","Build","Verify","Frame","Delivery","Overview"}){Check((bool)Call(panel,"Navigate",stage),"workspace routes "+stage);Capture(form,"workspace-"+stage);}
   Capture(form,"native-workspace-overview");
   var pane=app.CreateTaskpaneView2("","beamng.cad isolated UI test");
   try{Check(pane.DisplayWindowFromHandlex64(panel.Handle.ToInt64()),"native SolidWorks Task Pane accepts the workspace control");pane.ShowView();Pump(100);}
   finally{pane.DeleteView();}
  }
 }
 public static void Finish(){if(uiErrors.Count>0)throw new Exception(string.Join("\n",uiErrors));File.WriteAllText(Path.Combine(output,"results.local.json"),new System.Web.Script.Serialization.JavaScriptSerializer().Serialize(new {passed=passed,scope="Isolated UI fixtures; no geometry export, calibration, game launch, package installation or user project changes"}));}
}
'@
[ProjectWorkspaceTest]::Init((Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination)
try{
 [ProjectWorkspaceTest]::Offline()
 if($Native){
  if(Get-Process SLDWORKS -ErrorAction SilentlyContinue){throw 'Close SolidWorks before running the isolated native test; existing processes are never terminated'}
  $ownedProcess=$null;$ownedApp=$null
  try{
   $ownedProcess=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp/SOLIDWORKS/sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
   $deadline=(Get-Date).AddSeconds(90)
   do{$ownedApp=[ProjectWorkspaceTest]::Find($ownedProcess.Id);if(-not $ownedApp){Start-Sleep -Milliseconds 500}}while(-not $ownedApp -and (Get-Date) -lt $deadline)
   if(-not $ownedApp){throw 'Owned SolidWorks process unavailable'}
   [ProjectWorkspaceTest]::Native($ownedProcess.Id)
  }finally{
   if($ownedProcess){if($ownedApp){try{$ownedApp.ExitApp()}catch{}};$ownedProcess.Refresh();if(-not $ownedProcess.HasExited){$ownedProcess.Kill()}}
  }
 }
}finally{[ProjectWorkspaceTest]::Finish()}
