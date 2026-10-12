param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$Destination)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new snapshot path'}
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public class CurrentJointReadiness {
 sealed class CadContext:System.Threading.SynchronizationContext {
  readonly System.Collections.Concurrent.ConcurrentQueue<Action> queue=new System.Collections.Concurrent.ConcurrentQueue<Action>();
  public override void Post(System.Threading.SendOrPostCallback callback,object state){queue.Enqueue(()=>callback(state));}
  public void Drain(){Action a;while(queue.TryDequeue(out a)){SetSynchronizationContext(this);a();}}
 }
 public static void Run(int pid,string dll,string destination){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});var model=(ModelDoc2)app.ActiveDoc;
  if(!(model is AssemblyDoc))throw new Exception("Open the working assembly first");var stamp=model.GetUpdateStamp();var dirty=model.GetSaveFlag();var code=Assembly.LoadFrom(dll);
  var type=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var project=type.GetMethod("Load").Invoke(null,new object[]{model.GetPathName()+".beamng-project.json"});var context=new CadContext();System.Threading.SynchronizationContext.SetSynchronizationContext(context);
  var scannerType=code.GetType("BeamNG.Cad.Preparation.NativeMateScanner");var scanner=Activator.CreateInstance(scannerType,new[]{(object)app,model,project});
  var task=(System.Threading.Tasks.Task)scannerType.GetMethod("Capture").Invoke(scanner,new object[]{(Action<string>)(s=>Console.WriteLine(s)),System.Threading.CancellationToken.None});
  while(!task.IsCompleted){context.Drain();System.Windows.Forms.Application.DoEvents();System.Threading.SynchronizationContext.SetSynchronizationContext(context);System.Threading.Thread.Sleep(10);}task.GetAwaiter().GetResult();
  var workspace=type.GetField("JointWorkspace").GetValue(project);workspace.GetType().GetField("Mates").SetValue(workspace,task.GetType().GetProperty("Result").GetValue(task,null));
  if(stamp!=model.GetUpdateStamp()||dirty!=model.GetSaveFlag())throw new Exception("CAD changed during scan");
  code.GetType("BeamNG.Cad.Preparation.JsonFile").GetMethod("Write").MakeGenericMethod(type).Invoke(null,new[]{(object)destination,project});Console.WriteLine("PASS read-only native snapshot: "+destination);
 }
}
'@
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[CurrentJointReadiness]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination)
