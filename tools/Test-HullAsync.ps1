param([Parameter(Mandatory=$true)][int]$ProcessId,[Parameter(Mandatory=$true)][string]$HullFile,[Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
. (Join-Path $PSScriptRoot 'Connect-SolidWorks.ps1') -ProcessId $ProcessId
Add-Type -ReferencedAssemblies @('System.Core','System.Drawing','System.Windows.Forms',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll')) -TypeDefinition @'
using System;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
public static class AsyncHullSmoke {
 static void Check(bool value,string text){if(!value)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static void Pump(Task task){var deadline=DateTime.UtcNow.AddMinutes(2);while(!task.IsCompleted&&DateTime.UtcNow<deadline){Application.DoEvents();Thread.Sleep(1);}Check(task.IsCompleted,"async operation completed");task.GetAwaiter().GetResult();}
 public static void Run(object connection,string directory,string file){
  var app=(ISldWorks)connection;var model=(ModelDoc2)app.ActiveDoc;var dirty=model.GetSaveFlag();var features=model.GetFeatureCount();
  SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
  var type=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll")).GetType("BeamNG.Cad.Preparation.HullPreview");
  int ticks=0;var timer=new System.Windows.Forms.Timer {Interval=10};timer.Tick+=(s,e)=>ticks++;timer.Start();
  object preview=null;
  try{
   var create=(Task)type.GetMethod("CreateAsync").Invoke(null,new object[]{app,model,file,"XYZ",false,CancellationToken.None,new Action(()=>{}),new Action<string>(Console.WriteLine)});
   Pump(create);preview=create.GetType().GetProperty("Result").GetValue(create,null);
   Func<bool,Task> show=v=>(Task)type.GetMethod("SetVisibleAsync").Invoke(preview,new object[]{v});
   ticks=0;var task=show(true);show(false);show(true);show(false);Pump(task);
   Check(!(bool)type.GetProperty("Visible").GetValue(preview,null),"rapid requests end in the last requested state");
   Check(ticks>0,"menu message loop remains active during visibility updates");
   task=show(true);var dispose=(Task)type.GetMethod("DisposeAsync").Invoke(preview,null);Pump(dispose);Pump(task);
   Check(!(bool)type.GetProperty("Visible").GetValue(preview,null),"invalidation during display cleans up the preview");
   Check(((ModelView)model.ActiveView).EnableGraphicsUpdate,"graphics restored after asynchronous cleanup");
   Check(model.GetSaveFlag()==dirty&&model.GetFeatureCount()==features,"CAD features and save state preserved");
  }finally{if(preview!=null)((IDisposable)preview).Dispose();timer.Dispose();}
 }
}
'@
[AsyncHullSmoke]::Run([SwConnection]::Connect($ProcessId),$OutputDirectory,$HullFile)
