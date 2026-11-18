param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\session-progress'))
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
Add-Type -ReferencedAssemblies @('System.Core','System.Windows.Forms','System.Drawing') -TypeDefinition @'
using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.Serialization;
using System.Windows.Forms;
public static class WorkflowProgressSmoke {
 public static void Run(string directory) {
  var assembly=Assembly.LoadFrom(System.IO.Path.Combine(directory,"beamng.cad.dll"));
  var type=assembly.GetType("BeamNG.Cad.UI.FrameWorkflow");
  var instance=FormatterServices.GetUninitializedObject(type);
  var flags=BindingFlags.Instance|BindingFlags.NonPublic;
  var bar=new ProgressBar {Visible=false};var queue=new ConcurrentQueue<string>();
  var label=new Label();var status=new Label();var log=new TextBox {Multiline=true};var elapsed=new Stopwatch();
  type.GetField("taskProgress",flags).SetValue(instance,bar);
  type.GetField("pendingLog",flags).SetValue(instance,queue);
  type.GetField("progressText",flags).SetValue(instance,label);
  type.GetField("status",flags).SetValue(instance,status);
  type.GetField("log",flags).SetValue(instance,log);
  type.GetField("taskElapsed",flags).SetValue(instance,elapsed);
  var method=type.GetMethod("ShowProgress",flags);
  var lifecycle=type.GetMethod("UpdateTaskProgress",flags);
  var flush=type.GetMethod("FlushLog",flags);
  lifecycle.Invoke(instance,new object[]{false});
  if(bar.Visible||elapsed.IsRunning||label.Text!="")throw new Exception("Idle workflow must not show progress");
  lifecycle.Invoke(instance,new object[]{true});
  if(!bar.Visible||!elapsed.IsRunning||bar.Value!=0||label.Text!="Working...")throw new Exception("Task did not start with fresh progress");
  var instruction="Choose a material for 66 unique bodies; click Apply, then Close.";
  status.Text=instruction;
  type.GetField("progressDetail",flags).SetValue(instance,instruction);
  for(var tick=0;tick<2;tick++) {
   flush.Invoke(instance,null);
   var message=(string)type.GetProperty("TaskMessage",flags).GetValue(instance,null);
   if(message.IndexOf(instruction,StringComparison.Ordinal)!=message.LastIndexOf(instruction,StringComparison.Ordinal)||!message.StartsWith(instruction+"\r\nElapsed ")||!label.Text.StartsWith("Elapsed "))throw new Exception("Material instruction duplicated or elapsed time has an empty prefix");
  }
  type.GetField("progressDetail",flags).SetValue(instance,"Inspecting material targets...");
  flush.Invoke(instance,null);
  if(!label.Text.StartsWith("Inspecting material targets...\r\nElapsed "))throw new Exception("Distinct progress detail lost or elapsed time has an empty batch separator");
  type.GetField("batchDetail",flags).SetValue(instance,"Test batch 1 / 2");
  flush.Invoke(instance,null);
  if(!label.Text.StartsWith("Inspecting material targets...\r\nTest batch 1 / 2 | Elapsed "))throw new Exception("Batch detail or elapsed time lost");
  type.GetField("batchDetail",flags).SetValue(instance,"");
  status.Text="";
  method.Invoke(instance,new object[]{"CAD_PROGRESS {\"phase\":\"recording\",\"completed\":4,\"total\":8}"});
  if(bar.Value!=50||bar.Style!=ProgressBarStyle.Continuous)throw new Exception("Measured progress not displayed");
  method.Invoke(instance,new object[]{"CAD_PROGRESS {\"phase\":\"Material fit\",\"completed\":null,\"total\":null}"});
  if(bar.Style!=ProgressBarStyle.Marquee)throw new Exception("Unknown duration must remain indeterminate");
  method.Invoke(instance,new object[]{"CAD_PROGRESS {\"phase\":\"Calibration rejected\",\"detail\":\"Combine11\",\"outcome\":\"rejected\"}"});
  if(!((string)type.GetField("studyOutcome",flags).GetValue(instance)).Contains("Combine11"))throw new Exception("Rejection detail lost");
  method.Invoke(instance,new object[]{"CAD_PROGRESS broken"});
  if(queue.Count!=1)throw new Exception("Malformed progress must be logged without crashing");
  status.Text=(string)type.GetField("studyOutcome",flags).GetValue(instance);
  queue.Enqueue("CAD_PROGRESS {\"phase\":\"recording\",\"completed\":7,\"total\":8}");
  lifecycle.Invoke(instance,new object[]{false});
  if(bar.Visible||bar.Value!=0||bar.Style!=ProgressBarStyle.Continuous||elapsed.IsRunning)throw new Exception("Rejected task left active progress");
  if(!label.Text.StartsWith("Finished - Calibration rejected")||!label.Text.Contains("Combine11")||!label.Text.Contains("Elapsed "))throw new Exception("Rejection result or elapsed time lost");
  if(!log.Text.Contains("Invalid progress record"))throw new Exception("Progress cleanup discarded log output");
  var rejectedLabel=label.Text;
  queue.Enqueue("CAD_PROGRESS {\"phase\":\"late update\",\"outcome\":\"stale\"}");
  queue.Enqueue("Late worker log retained");
  flush.Invoke(instance,null);
  if(bar.Visible||bar.Style==ProgressBarStyle.Marquee||label.Text!=rejectedLabel||!log.Text.Contains("Late worker log retained"))throw new Exception("Late output revived progress or lost evidence");
  foreach(var result in new[]{"Finished","Cancelled","Failed"}) {
   queue.Enqueue("CAD_PROGRESS {\"phase\":\"old batch\",\"outcome\":\"stale\"}");
   lifecycle.Invoke(instance,new object[]{true});
   if(!bar.Visible||bar.Value!=0||bar.Style!=ProgressBarStyle.Marquee||!elapsed.IsRunning||label.Text!="Working..."||type.GetField("studyOutcome",flags).GetValue(instance)!=null||!Equals(type.GetField("batchDetail",flags).GetValue(instance),"")||!Equals(type.GetField("taskResult",flags).GetValue(instance),"Finished"))throw new Exception("Restart retained old task state");
   method.Invoke(instance,new object[]{"CAD_PROGRESS {\"phase\":\"Test batch\",\"completed\":1,\"total\":2}"});
   type.GetField("taskResult",flags).SetValue(instance,result);
   status.Text=result=="Finished"?"Package created.":result=="Cancelled"?"Build stopped.":"Worker failed.";
   lifecycle.Invoke(instance,new object[]{false});
   if(bar.Visible||bar.Value!=0||elapsed.IsRunning||!label.Text.StartsWith(result+" - "+status.Text)||!label.Text.Contains("Elapsed "))throw new Exception(result+" did not retain a terminal result");
   var finalText=label.Text;
   method.Invoke(instance,new object[]{"CAD_PROGRESS {\"phase\":\"late\"}"});
   flush.Invoke(instance,null);
   if(bar.Visible||label.Text!=finalText||elapsed.IsRunning)throw new Exception("Terminal result changed after "+result);
  }
  bar.Dispose();label.Dispose();status.Dispose();log.Dispose();
  Console.WriteLine("PASS: material instruction deduplication, detail/batch/elapsed formatting, measured/indeterminate progress, rejection, completion, cancellation, failure, late output, restart, and retained logs/results");
 }
}
'@
[WorkflowProgressSmoke]::Run($OutputDirectory)
