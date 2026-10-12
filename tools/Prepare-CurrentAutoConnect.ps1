param([int]$SolidWorksProcessId,[string]$ProjectPath,[string]$OutputDirectory,[string]$Destination,[switch]$MountsOnly,[switch]$ScanOnly,[switch]$GeometryOnly,[switch]$DisplayGeometry)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new output directory'}
[void][IO.Directory]::CreateDirectory($Destination)
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class AssistedAutoConnect {
 static object Get(object o,string key){return o.GetType().GetField(key).GetValue(o);}
 static void Set(object o,string key,object v){o.GetType().GetField(key).SetValue(o,v);}
 static object New(Assembly a,string type,params object[] args){return Activator.CreateInstance(a.GetType("BeamNG.Cad.Preparation."+type),BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance,null,args,null);}
 sealed class CadContext:System.Threading.SynchronizationContext {
  readonly System.Collections.Concurrent.ConcurrentQueue<Action> queue=new System.Collections.Concurrent.ConcurrentQueue<Action>();
  public override void Post(System.Threading.SendOrPostCallback c,object s){queue.Enqueue(()=>c(s));}
  public void Drain(){Action a;while(queue.TryDequeue(out a)){SetSynchronizationContext(this);a();}}
 }
 public static void Run(int pid,string dll,string source,string output,bool mountsOnly,bool scanOnly,bool geometryOnly,bool displayGeometry){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});var model=(ModelDoc2)app.ActiveDoc;
  var code=Assembly.LoadFrom(dll);var type=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var project=type.GetMethod("Load").Invoke(null,new object[]{source});
  if(!string.Equals(model.GetPathName(),(string)Get(project,"SourceDocument"),StringComparison.OrdinalIgnoreCase))throw new Exception("Active document differs from project");
  var stamp=model.GetUpdateStamp();var dirty=model.GetSaveFlag();var sourceBytes=File.ReadAllBytes(source);File.WriteAllBytes(Path.Combine(output,"before.beamng-project.json"),sourceBytes);
  var context=new CadContext();System.Threading.SynchronizationContext.SetSynchronizationContext(context);
  if(!geometryOnly){var scanner=New(code,"NativeMateScanner",app,model,project);var task=(System.Threading.Tasks.Task)scanner.GetType().GetMethod("Capture").Invoke(scanner,new object[]{(Action<string>)(s=>Console.WriteLine(s)),System.Threading.CancellationToken.None});
  while(!task.IsCompleted){context.Drain();System.Windows.Forms.Application.DoEvents();System.Threading.SynchronizationContext.SetSynchronizationContext(context);System.Threading.Thread.Sleep(10);}task.GetAwaiter().GetResult();
  Set(Get(project,"JointWorkspace"),"Mates",task.GetType().GetProperty("Result").GetValue(task,null));
  Set(Get(project,"JointWorkspace"),"ScanDocument",model.GetPathName());Set(Get(project,"JointWorkspace"),"ScanConfiguration",model.ConfigurationManager.ActiveConfiguration.Name);Set(Get(project,"JointWorkspace"),"ScanStamp",stamp);}
  var write=code.GetType("BeamNG.Cad.Preparation.JsonFile").GetMethod("Write").MakeGenericMethod(type);var snapshot=Path.Combine(output,"project.json");
  if(scanOnly){if(model.GetUpdateStamp()!=stamp||model.GetSaveFlag()!=dirty)throw new Exception("CAD changed while scanning");write.Invoke(null,new[]{(object)snapshot,project});Console.WriteLine("SNAPSHOT "+snapshot);return;}
  var selection=New(code,"FrameSelection",app,model,true);var capture=code.GetType("BeamNG.Cad.Preparation.AssignmentInspection").GetMethod("Capture");
  var groups=((IEnumerable)Get(project,"Components")).Cast<object>().ToArray();var errors=new List<string>();int index=0;
  var previousCommand=app.CommandInProgress;app.CommandInProgress=true;try {foreach(var component in groups){
   if(model.GetUpdateStamp()!=stamp||model.GetSaveFlag()!=dirty)throw new Exception("CAD changed during snapshot");
   Console.WriteLine("EXPORT "+(++index)+"/"+groups.Length+" "+Get(component,"Name"));
   var role=(string)Get(component,"MvpRole");var template=(string)Get(component,"Template");
   if(mountsOnly && role!="frame" && role!="panel" && role!="accessory" && template!="panel") {Console.WriteLine("DEFER geometry; native mate analysis remains available");continue;}
   try{
    var assignment=capture.Invoke(null,new object[]{component,false});var folder=Path.Combine(output,"geometry",(string)Get(component,"Id"));
    var exportMethod=displayGeometry&&role!="frame"?"ExportDisplay":"Export";
    var exported=selection.GetType().GetMethod(exportMethod).Invoke(selection,new[]{assignment,folder});
    var actual=((IEnumerable)Get(exported,"Meshes")).Cast<object>().Select(m=>(string)Get(m,"Id")).OrderBy(x=>x).ToArray();
    if(!actual.SequenceEqual(((IEnumerable)Get(component,"BodyIds")).Cast<string>().OrderBy(x=>x)))throw new Exception("CAD body ownership changed");
    Set(component,"GeometryDirectory",folder);
    foreach(var member in ((IEnumerable)Get(Get(project,"JointWorkspace"),"Members")).Cast<object>().Where(m=>(string)Get(m,"ComponentId")== (string)Get(component,"Id"))){
     var a=New(code,"FrameAssignment");Set(a,"Id",Get(member,"Id"));Set(a,"Configuration",Get(component,"Configuration"));Set(a,"Selections",Get(member,"Selections"));
     var path=Path.Combine(output,"geometry",(string)Get(member,"Id"));selection.GetType().GetMethod(exportMethod).Invoke(selection,new[]{a,path});Set(member,"GeometryDirectory",path);
    }
   }catch(Exception e){var error=Get(component,"Name")+": "+e.GetBaseException().Message;errors.Add(error);Console.WriteLine("EXPORT ERROR "+error);Set(component,"GeometryDirectory","");}
   write.Invoke(null,new[]{(object)snapshot,project});
  }}finally {app.CommandInProgress=previousCommand;}
  if(model.GetUpdateStamp()!=stamp||model.GetSaveFlag()!=dirty||!sourceBytes.SequenceEqual(File.ReadAllBytes(source)))throw new Exception("CAD/project changed while snapshotting");
  File.WriteAllLines(Path.Combine(output,"export-errors.txt"),errors);Console.WriteLine("SNAPSHOT "+snapshot+"; errors="+errors.Count);
 }
}
'@
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[AssistedAutoConnect]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),(Resolve-Path -LiteralPath $ProjectPath).Path,$Destination,[bool]$MountsOnly,[bool]$ScanOnly,[bool]$GeometryOnly,[bool]$DisplayGeometry)

