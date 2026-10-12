param([int]$SolidWorksProcessId,[string]$ProjectPath,[string]$OutputDirectory,[string]$Destination,[string]$DebugGate)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class SavedAssignmentWorkflowTest {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static object New(Assembly code,string type,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+type),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,args,null);}
 static void Set(object o,string name,object value){o.GetType().GetProperty(name).SetValue(o,value,null);}
 static object Project(System.Windows.Forms.Form form){return form.GetType().GetField("project",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(form);}
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static void Action(System.Windows.Forms.Form form,string name,params object[] args){
  var method=form.GetType().GetMethod(name,BindingFlags.Instance|BindingFlags.NonPublic);
  form.GetType().GetMethod("Run",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,new object[]{(Func<System.Threading.Tasks.Task>)(()=> (System.Threading.Tasks.Task)method.Invoke(form,args))});
  var busy=form.GetType().GetField("cancel",BindingFlags.Instance|BindingFlags.NonPublic);var until=DateTime.UtcNow.AddSeconds(30);
  while(busy.GetValue(form)!=null && DateTime.UtcNow<until){System.Windows.Forms.Application.DoEvents();System.Threading.Thread.Sleep(10);}
  Check(busy.GetValue(form)==null,"action completed: "+name);
 }
 public static void Run(int pid,string dll,string projectPath,string folder){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var model=app.ActiveDoc as ModelDoc2;var code=Assembly.LoadFrom(dll);var original=File.ReadAllBytes(projectPath);
  var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var originalProject=projectType.GetMethod("Load").Invoke(null,new object[]{projectPath});
  if(model==null || !string.Equals(model.GetPathName(),(string)Get(originalProject,"SourceDocument"),StringComparison.OrdinalIgnoreCase))throw new Exception("Activate the matching assembly");
  var path=Path.Combine(folder,"project.json");if(File.Exists(path))throw new Exception("Use a fresh owned test directory");File.WriteAllBytes(path,original);if(File.Exists(projectPath+".profile.json"))File.Copy(projectPath+".profile.json",path+".profile.json");
  var settings=New(code,"UI.ExporterSettings",Path.Combine(folder,"settings.xml"));Set(settings,"LastProjectPath",path);Set(settings,"FrameOutput",Path.Combine(folder,"builds"));Set(settings,"CalibrationPythonExecutable",@"H:\beamng project programs\BeamNG.cad\.venv\Scripts\python.exe");settings.GetType().GetMethod("Save").Invoke(settings,null);
  using(var preserved=(IDisposable)New(code,"Preparation.SelectionSnapshot",model))
  using(var form=(System.Windows.Forms.Form)New(code,"UI.ComponentWorkflow",app,model,settings)){
   var handle=form.Handle;System.Threading.SynchronizationContext.SetSynchronizationContext(new System.Windows.Forms.WindowsFormsSynchronizationContext());
   var list=(System.Windows.Forms.ListBox)form.Controls.Find("Components",true).Single();list.SelectedItem=list.Items.Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="rear_final_drive");
   var initialCount=list.Items.Count;var originalId=Get(list.SelectedItem,"Id");
   var inspectionSource=(System.Windows.Forms.ComboBox)form.Controls.Find("AssignmentSource",true).Single();
   if((string)Get(list.SelectedItem,"CadSourceDocument")==model.GetPathName() && ((IList)Get(list.SelectedItem,"AppearanceSelections")).Count==0)
    Check(inspectionSource.SelectedIndex==1,"opening a physically assigned group inspects this assembly's CAD, even with an imported template");
   if((string)Get(list.SelectedItem,"CadSourceDocument")==model.GetPathName()){
    // Use the durable group as the test input, rather than whatever transient selection the user has.
    // The enclosing SelectionSnapshot restores that original selection, including reference-only parts.
    inspectionSource.SelectedIndex=1;((System.Windows.Forms.CheckBox)form.Controls.Find("ZoomToAssignedGeometry",true).Single()).Checked=false;
    Action(form,"ShowAssignedGeometry");Check(form.Controls.Find("ComponentStatus",true).Single().Text.StartsWith("Highlighted"),"saved physical CAD supplies the regression selection");
   }
   var timer=System.Diagnostics.Stopwatch.StartNew();Action(form,"ReplaceAppearance");timer.Stop();
   var log=form.Controls.Find("ComponentLog",true).Single().Text;var status=form.Controls.Find("ComponentStatus",true).Single().Text;
   File.WriteAllText(Path.Combine(folder,"workflow.log"),status+System.Environment.NewLine+log);Console.WriteLine(status+System.Environment.NewLine+log);
   var current=projectType.GetMethod("Load").Invoke(null,new object[]{path});var group=((IEnumerable)Get(current,"Components")).Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="rear_final_drive");
   Check(((IList)Get(group,"AppearanceSelections")).Count>0 && (string)Get(group,"AppearancePackageState")=="pending","final drive visual selection is saved immediately");
   Check(!Directory.Exists(Path.Combine(folder,"builds")),"saving the assignment does not run export or packaging");Console.WriteLine("Save assignment elapsed ms: "+timer.ElapsedMilliseconds);
   ((System.Windows.Forms.CheckBox)form.Controls.Find("ZoomToAssignedGeometry",true).Single()).Checked=false;
   Action(form,"ShowAssignedGeometry");Check(form.Controls.Find("ComponentStatus",true).Single().Text.StartsWith("Highlighted"),"saved final drive can be highlighted before packaging");
   var selectedRefs=((IEnumerable)Get(group,"AppearanceSelections")).Cast<object>().Select(r=>(string)Get(r,"Reference")).ToArray();
   Get(Project(form),"Components");Project(form).GetType().GetField("LastBuildReceipt").SetValue(Project(form),"");Project(form).GetType().GetMethod("Save").Invoke(Project(form),null);
   Action(form,"PackageAppearances");
   current=projectType.GetMethod("Load").Invoke(null,new object[]{path});group=((IEnumerable)Get(current,"Components")).Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="rear_final_drive");
   Check((string)Get(group,"AppearancePackageState")=="failed" && ((IEnumerable)Get(group,"AppearanceSelections")).Cast<object>().Select(r=>(string)Get(r,"Reference")).SequenceEqual(selectedRefs),"package failure retains the saved visual selection");
   Check(form.Controls.Find("ComponentStatus",true).Single().Text.StartsWith("Failed: Visual assignments are saved"),"package failure is explicit in the visible status");
   Action(form,"AddAssignment",false);
   Check(inspectionSource.SelectedIndex==1,"physical assignment selects Physical CAD even when the group also has a visual assignment");
   Action(form,"ShowAssignedGeometry");Check(form.Controls.Find("ComponentStatus",true).Single().Text.Contains("physical CAD"),"Show immediately after physical assignment highlights the physical group");
   Action(form,"SaveParameters");Check(inspectionSource.SelectedIndex==1,"saving parameters preserves the inspection source across list refreshes");
   current=projectType.GetMethod("Load").Invoke(null,new object[]{path});group=((IEnumerable)Get(current,"Components")).Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="rear_final_drive");
   Check(((IList)Get(current,"Components")).Count==initialCount && Equals(Get(group,"Id"),originalId) && (string)Get(group,"CadSourceDocument")==model.GetPathName(),"physical assignment updates the selected row without a duplicate");
   Action(form,"ReplaceAppearance");Check(inspectionSource.SelectedIndex==0,"visual assignment switches inspection back to Appearance CAD");
   var beforeConflict=File.ReadAllBytes(path);list.SelectedItem=list.Items.Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="engine");Action(form,"AddAssignment",false);
   Check(File.ReadAllBytes(path).SequenceEqual(beforeConflict),"duplicate physical ownership leaves saved assignments unchanged");
   var catalog=code.GetType("BeamNG.Cad.Preparation.MvpCatalog").GetMethod("Load").Invoke(null,null);
   var fresh=projectType.GetMethod("StartFresh").Invoke(current,new object[]{Path.Combine(folder,"fresh.beamng-project.json"),catalog,true});
   Check(((IList)Get(fresh,"Components")).Count>20 && ((IEnumerable)Get(fresh,"Components")).Cast<object>().All(c=>((IList)Get(c,"Selections")).Count==0&&((IList)Get(c,"AppearanceSelections")).Count==0),"fresh project contains required groups with empty assignments");
   Check(new[]{"LastBuildReceipt","FrameBuildReceipt","PhysicsBuildReceipt","PhysicsTemplateReceipt","TemplateDefinitionPath"}.All(n=>string.IsNullOrEmpty((string)Get(fresh,n))),"fresh project has no imported package, physics or hardpoints");
   form.GetType().GetMethod("SwitchProject",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,new[]{fresh});
   list.SelectedItem=list.Items.Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="rear_final_drive");Action(form,"AddAssignment",false);
   Check((string)Get(list.SelectedItem,"CadSourceDocument")==model.GetPathName() && ((IList)Get(list.SelectedItem,"Selections")).Count>0,"assigning physical CAD works without any imported template");
   File.WriteAllText(Path.Combine(folder,"workflow.log"),form.Controls.Find("ComponentStatus",true).Single().Text+System.Environment.NewLine+form.Controls.Find("ComponentLog",true).Single().Text);
   Check(File.ReadAllBytes(projectPath).SequenceEqual(original),"original user project is byte-identical");
   File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS");
  }
 }
}
'@
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
if($DebugGate){
 [void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
 [IO.File]::WriteAllText($DebugGate+'.pid',[string]$PID)
 $deadline=(Get-Date).AddMinutes(3)
 while(Test-Path -LiteralPath $DebugGate){if((Get-Date) -gt $deadline){throw 'Debug gate timed out'};Start-Sleep -Milliseconds 250}
}
[SavedAssignmentWorkflowTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),$ProjectPath,[IO.Path]::GetFullPath($Destination))
