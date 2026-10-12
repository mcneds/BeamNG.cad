param(
 [Parameter(Mandatory=$true)][string]$Receipt,
 [Parameter(Mandatory=$true)][string]$Destination,
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [string]$PythonExecutable='H:/beamng project programs/BeamNG.cad/.venv/Scripts/python.exe',
 [string]$DebugGate,
 [switch]$CompileOnly
)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Run with Windows PowerShell -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Receipt=(Resolve-Path -LiteralPath $Receipt).Path
$Destination=[IO.Path]::GetFullPath($Destination)
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing',
 (Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
$refs+=@('System.Runtime.Serialization','System.Xml')
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Runtime.Serialization.Json;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class VehicleTemplateUiTest {
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out IBindCtx context);
 delegate bool WindowCallback(IntPtr window,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent,WindowCallback callback,IntPtr parameter);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint process);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window,System.Text.StringBuilder text,int count);
 [DllImport("user32.dll")] static extern IntPtr GetDlgItem(IntPtr window,int id);
 [DllImport("user32.dll")] static extern int GetDlgCtrlID(IntPtr window);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern IntPtr SendMessage(IntPtr window,uint message,IntPtr w,string text);
 [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window,uint message,IntPtr w,IntPtr l);
 static readonly JavaScriptSerializer Json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};
 static System.Threading.Timer promptGuard;
 public static void GuardOwnedPrompt(int process){
  promptGuard=new System.Threading.Timer(_=>EnumWindows((window,p)=>{
   uint owner;GetWindowThreadProcessId(window,out owner);var title=new System.Text.StringBuilder(256);GetWindowText(window,title,256);
   if(owner==(uint)process && title.ToString()=="Find SOLIDWORKS Toolbox Managed in SOLIDWORKS PDM")
    EnumChildWindows(window,(button,q)=>{uint childOwner;GetWindowThreadProcessId(button,out childOwner);var text=new System.Text.StringBuilder(256);GetWindowText(button,text,256);if(childOwner==owner && text.ToString()=="No")PostMessage(button,0xF5,IntPtr.Zero,IntPtr.Zero);return true;},IntPtr.Zero);
   return true;
  },IntPtr.Zero),null,0,500);
 }
 public static ISldWorks Find(int pid){
  IRunningObjectTable table;IBindCtx context;GetRunningObjectTable(0,out table);CreateBindCtx(0,out context);IEnumMoniker list;table.EnumRunning(out list);var item=new IMoniker[1];
  try{while(list.Next(1,item,IntPtr.Zero)==0){try{string name;item[0].GetDisplayName(context,null,out name);if(name=="SolidWorks_PID_"+pid){object value;table.GetObject(item[0],out value);return (ISldWorks)value;}}finally{Marshal.ReleaseComObject(item[0]);}}return null;}
  finally{Marshal.ReleaseComObject(list);Marshal.ReleaseComObject(context);Marshal.ReleaseComObject(table);}
 }
 static object Get(object o,string name){return o.GetType().GetField(name).GetValue(o);}
 static string Snapshot(object value){using(var bytes=new MemoryStream()){new DataContractJsonSerializer(value.GetType()).WriteObject(bytes,value);return Convert.ToBase64String(bytes.ToArray());}}
 static object Create(Assembly code,string name,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+name),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,args,null);}
 static void Check(bool value,string text){if(!value)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static Dictionary<string,object> Read(string path){return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));}
 static Control ControlNamed(Control parent,string text){foreach(Control child in parent.Controls){if(child.Name==text || child.Text==text)return child;var found=ControlNamed(child,text);if(found!=null)return found;}return null;}
 static object Project(Form form){return form.GetType().GetField("project",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form);}
 static string SelectedReceipt(Form form){return (string)Get(Project(form),"LastBuildReceipt");}
 static void Click(Form form,string text){
  var button=ControlNamed(form,text) as Button;Check(button!=null && button.Enabled,"action available: "+text);
  for(Control parent=button.Parent;parent!=null;parent=parent.Parent)if(parent is TabPage)((TabControl)parent.Parent).SelectedTab=(TabPage)parent;
  button.PerformClick();var busy=form.GetType().GetField("cancel",BindingFlags.NonPublic|BindingFlags.Instance);var until=DateTime.UtcNow.AddMinutes(4);
  do{Application.DoEvents();Thread.Sleep(10);}while(busy.GetValue(form)!=null && DateTime.UtcNow<until);
  Check(busy.GetValue(form)==null,"action completed: "+text);
  Console.WriteLine(ControlNamed(form,"ComponentStatus").Text);
  Check(!ControlNamed(form,"ComponentLog").Text.Contains("System.InvalidOperationException"),"no worker/UI exception: "+text);
  Check(!form.Controls.OfType<ProgressBar>().Single().Visible,"terminal progress hidden: "+text);
 }
 static void Save(ModelDoc2 doc,string path){int e=0,w=0;Check(doc.Extension.SaveAs(path,0,1,null,ref e,ref w),"saved owned CAD fixture");}
 static void Screenshot(Form form,string path){using(var image=new System.Drawing.Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new System.Drawing.Rectangle(0,0,form.Width,form.Height));image.Save(path);}}
 static void Import(Form form,string receipt){
  bool handled=false;Exception error=null;var deadline=DateTime.UtcNow.AddSeconds(20);
  using(var timer=new System.Windows.Forms.Timer {Interval=100}){
   timer.Tick+=(s,e)=>{
    try{EnumWindows((window,p)=>{
     uint pid;GetWindowThreadProcessId(window,out pid);if(pid!=System.Diagnostics.Process.GetCurrentProcess().Id)return true;
     var title=new System.Text.StringBuilder(256);GetWindowText(window,title,256);
     if(title.ToString()!="Choose the completed template vehicle")return true;
     if(DateTime.UtcNow>deadline){PostMessage(window,0x111,new IntPtr(2),IntPtr.Zero);throw new Exception("Owned file picker timeout");}
     var entry=GetDlgItem(window,1148);if(entry==IntPtr.Zero)entry=GetDlgItem(window,1152);
     if(entry==IntPtr.Zero)EnumChildWindows(window,(child,q)=>{var id=GetDlgCtrlID(child);if(id==1148 || id==1152){entry=child;return false;}return true;},IntPtr.Zero);
     if(entry==IntPtr.Zero)return true;
     SendMessage(entry,0xC,IntPtr.Zero,receipt);PostMessage(window,0x111,new IntPtr(1),IntPtr.Zero);handled=true;timer.Stop();return false;
    },IntPtr.Zero);}catch(Exception ex){error=ex;timer.Stop();}
   };
   timer.Start();Click(form,"Import physics template");timer.Stop();
  }
  if(error!=null)throw error;Check(handled,"native template file picker exercised");
 }
 public static void Run(object application,string dll,string receipt,string folder,string python){
  var app=(ISldWorks)application;
  var code=Assembly.LoadFrom(dll);app.UserControl=true;app.Visible=true;Control.CheckForIllegalCrossThreadCalls=true;
  var part=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
  part.Extension.SelectByID2("Front Plane","PLANE",0,0,0,false,0,null,0);part.SketchManager.InsertSketch(true);
  part.SketchManager.CreateCornerRectangle(-.1,-.08,0,.1,.08,0);part.SketchManager.InsertSketch(true);
  Check(part.FeatureManager.FeatureExtrusion2(true,false,false,0,0,.13,.13,false,false,false,false,0,0,false,false,false,false,false,true,true,0,0,false)!=null,"replacement box created");
  var db=((IEnumerable)app.GetMaterialDatabases()).Cast<string>().Single(p=>Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
  ((PartDoc)part).SetMaterialPropertyName2("",db,"AISI 4130 Steel, annealed at 865C");
  var partPath=Path.Combine(folder,"replacement.SLDPRT");Save(part,partPath);
  var model=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
  var component=((AssemblyDoc)model).AddComponent5(partPath,0,"",false,"",0,0,0);Check(component!=null,"owned assembly component inserted");
  Save(model,Path.Combine(folder,"appearance.SLDASM"));
  var settings=Create(code,"UI.ExporterSettings",Path.Combine(folder,"settings.xml"));
  foreach(var item in new Dictionary<string,string>{{"FrameOutput",Path.Combine(folder,"builds")},{"CalibrationPythonExecutable",python},{"PythonExecutable",python}})
   settings.GetType().GetProperty(item.Key).SetValue(settings,item.Value,null);
  settings.GetType().GetMethod("Save").Invoke(settings,null);
  var receipts=new Dictionary<string,string>{{"baseline",receipt}};
  using(var form=(Form)Create(code,"UI.ComponentWorkflow",app,model,settings)){
   form.Show();Application.DoEvents();SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
   var pages=(TabControl)ControlNamed(form,"WorkflowPages");
   Check(pages.SelectedTab.Text=="Vehicle setup / MVP","setup is the first workflow page");
   Check(pages.TabPages.Cast<TabPage>().Any(p=>p.Text=="Log"),"log has its own page");
   Screenshot(form,Path.Combine(folder,"vehicle-setup.png"));
   Import(form,receipt);var imported=SelectedReceipt(form);Check(File.Exists(imported),"import produced a completed project package");receipts["imported"]=imported;
   Check(pages.SelectedTab.Text=="Components"&&((TabControl)ControlNamed(form,"ComponentDetails")).SelectedTab.Text=="Appearance","import opens appearance association directly");
   var importedState=Json.Serialize(Project(form));
   Click(form,"Continue with imported template");
   Check(pages.SelectedTab.Text=="Components"&&((TabControl)ControlNamed(form,"ComponentDetails")).SelectedTab.Text=="Appearance","repeat import action returns to appearance");
   Check(Json.Serialize(Project(form))==importedState&&SelectedReceipt(form)==imported,"repeat import action preserves project and package");
   Check((string)((Dictionary<string,object>)Read(imported)["identity"])["namespace"]!=(string)((Dictionary<string,object>)Read(receipt)["identity"])["namespace"],"import owns a distinct package namespace");
   var list=(ListBox)form.Controls.Find("Components",true).Single();Check(list.Items.Count>20,"imported template component inventory");
   Check(list.Items.Cast<object>().All(c=>list.GetItemText(c)==(string)c.GetType().GetProperty("AssignmentLabel").GetValue(c,null)),"component list displays names, roles and assignment status after import");
   list.SelectedItem=list.Items.Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="engine");var selected=list.SelectedItem;
   var requests=(TreeView)ControlNamed(form,"ReferenceRequests");
   Check(requests.SelectedNode.Name=="engine","CAD group selection follows reference mesh");
   var projectBefore=Json.Serialize(Project(form));
   pages.SelectedTab=pages.TabPages.Cast<TabPage>().Single(p=>p.Text=="Reference skeleton");
   requests.SelectedNode=requests.Nodes["rl_trailing_arm"].Nodes["pivot_axis_a"];requests.SelectedNode.Parent.Expand();Application.DoEvents();
   Check(ControlNamed(form,"ReferenceDetail").Text.Contains("hardpoints.RL.hinge_inner"),"reference pivot is labelled in native workflow");
   Check(Json.Serialize(Project(form))==projectBefore,"viewing reference leaves CAD assignments and physics unchanged");
   Screenshot(form,Path.Combine(folder,"reference-skeleton.png"));
   var geometry=(string)Get(selected,"GeometryDirectory");var selections=Json.Serialize(Get(selected,"Selections"));
   Check(component.Select4(false,null,false),"replacement geometry selected");Click(form,"Save visual assignment");
   Check(SelectedReceipt(form)==imported && ((IList)Get(selected,"AppearanceSelections")).Count==1,"visual assignment persists without changing the selected package");
   Click(form,"Package saved appearances");
   var replaced=SelectedReceipt(form);Check(replaced!=imported && File.Exists(replaced),"appearance revision produced");receipts["appearance"]=replaced;
   Check((string)Read(replaced)["physics_sha256"]==(string)Read(imported)["physics_sha256"],"appearance preserved physical hash");
   Check((string)Get(selected,"GeometryDirectory")==geometry && Json.Serialize(Get(selected,"Selections"))==selections,"physical CAD ownership unchanged");
   var beforeInspection=Snapshot(Project(form));model.ClearSelection2(true);
   Check(((ComboBox)ControlNamed(form,"AssignmentSource")).SelectedIndex==0,"appearance replacement becomes the default inspection source");
   Click(form,"Show in SolidWorks");
   var manager=(SelectionMgr)model.SelectionManager;
   Check(manager.GetSelectedObjectCount2(-1)==1 && app.IsSame(manager.GetSelectedObject6(1,-1),component)==(int)swObjectEquality.swObjectSame,"inspection highlights the replacement component in the real assembly");
   Check(Snapshot(Project(form))==beforeInspection && SelectedReceipt(form)==replaced,"inspection does not change assignment or package");
   bool aligned=false;using(var timer=new System.Windows.Forms.Timer {Interval=100}){
    timer.Tick+=(s,e)=>{var dialog=Application.OpenForms.Cast<Form>().FirstOrDefault(f=>f.Text=="Appearance alignment in BeamNG coordinates");if(dialog==null)return;
     var fields=dialog.Controls.Cast<Control>().SelectMany(c=>c.Controls.Cast<Control>()).OfType<NumericUpDown>().ToArray();
     if(fields.Length!=6)throw new Exception("Alignment field contract changed");fields[0].Value=25;fields[4].Value=5;
     aligned=true;timer.Stop();((Button)ControlNamed(dialog,"Apply alignment")).PerformClick();};
    timer.Start();Click(form,"Align appearance");timer.Stop();
   }
   Check(aligned && SelectedReceipt(form)==replaced && ControlNamed(form,"ComponentStatus").Text.StartsWith("Appearance alignment saved"),"alignment saved before package update");
   Click(form,"Package saved appearances");
   var alignment=SelectedReceipt(form);Check(alignment!=replaced && File.Exists(alignment),"alignment UI produced revision");receipts["alignment"]=alignment;
   Check((string)Read(alignment)["physics_sha256"]==(string)Read(imported)["physics_sha256"],"alignment preserved physical hash");
   Screenshot(form,Path.Combine(folder,"component-workflow.png"));
   // Reproduce accidental use of CAD assignment while testing appearance.
   SetFixtureMistake(selected);
   Project(form).GetType().GetMethod("Save").Invoke(Project(form),null);
   var beforeReset=File.ReadAllBytes((string)Project(form).GetType().GetProperty("FilePath").GetValue(Project(form),null));
   Click(form,"Reset to imported template");
   var resetReceipt=SelectedReceipt(form);receipts["reset"]=resetReceipt;
   Check(resetReceipt!=alignment&&File.Exists(resetReceipt),"reset produces a fresh baseline package");
   Check((string)Read(resetReceipt)["physics_sha256"]==(string)Read(imported)["physics_sha256"],"reset restores original imported physics");
   var resetEngine=list.Items.Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="engine");
   Check((string)Get(resetEngine,"Name")!="Accidental CAD edit"&&string.IsNullOrEmpty((string)Get(resetEngine,"AppearanceDirectory")),"reset removes assignment and appearance edits");
   Check(pages.SelectedTab.Text=="Components"&&((TabControl)ControlNamed(form,"ComponentDetails")).SelectedTab.Text=="Appearance","reset lands on appearance association");
   var projectFile=(string)Project(form).GetType().GetProperty("FilePath").GetValue(Project(form),null);
   Check(Directory.GetFiles(projectFile+".template-reset-backups","*.json").Any(p=>File.ReadAllBytes(p).SequenceEqual(beforeReset)),"native reset keeps exact pre-reset backup");
   File.WriteAllText(Path.Combine(folder,"receipts.json"),Json.Serialize(receipts));form.Close();Application.DoEvents();Check(form.IsDisposed,"workflow closes safely");
  }
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS");
 }
 static void SetFixtureMistake(object component){component.GetType().GetField("Name").SetValue(component,"Accidental CAD edit");}
}
'@
if($CompileOnly){Write-Output 'COMPILED';return}
if(Test-Path -LiteralPath $Destination){throw 'Use a fresh UI evidence directory'}
if(Get-Process BeamNG.drive.x64 -ErrorAction SilentlyContinue){throw 'Finish the native game session before starting SolidWorks'}
[void][IO.Directory]::CreateDirectory($Destination)
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
$ownedPid=$null
try{
 $process=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp/SOLIDWORKS/sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
 if($existing -contains $process.Id){throw 'Refusing an existing SolidWorks process'}
 $ownedPid=$process.Id;[VehicleTemplateUiTest]::GuardOwnedPrompt($ownedPid);$until=(Get-Date).AddSeconds(120)
 @{pid=$ownedPid;parent=$PID;start_utc=$process.StartTime.ToUniversalTime().ToString('O')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Destination 'owned-process.json')
 do{$app=[VehicleTemplateUiTest]::Find($ownedPid);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and (Get-Date) -lt $until)
 if(-not $app){throw 'Owned SolidWorks process did not register'}
 if($DebugGate){
  [IO.File]::WriteAllText($DebugGate+'.pid',[string]$PID)
  $deadline=(Get-Date).AddMinutes(3)
  while(Test-Path -LiteralPath $DebugGate){if((Get-Date) -gt $deadline){throw 'Debugger gate timed out'};Start-Sleep -Milliseconds 100}
 }
 [VehicleTemplateUiTest]::Run($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Receipt,$Destination,$PythonExecutable)
}finally{
 if($ownedPid){
  if($app){try{$app.ExitApp()}catch{}}
  $process.Refresh();if(-not $process.HasExited){$process.Kill()}
 }
}
