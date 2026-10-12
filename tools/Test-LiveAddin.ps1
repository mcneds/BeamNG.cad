param([Parameter(Mandatory=$true)][int]$ProcessId,
      [Parameter(Mandatory=$true)][int]$AddInId,
      [Parameter(Mandatory=$true)][string]$Fixture,
      [string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '..\beamng.cad\bin\Debug\net472' }
. (Join-Path $PSScriptRoot 'Connect-SolidWorks.ps1') -ProcessId $ProcessId
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
Add-Type -ReferencedAssemblies @('System.Core', (Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll')) -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using SolidWorks.Interop.sldworks;
public static class LiveAddinSmoke {
 static void Check(bool ok,string message) {if(!ok)throw new Exception(message);Console.WriteLine("PASS "+message);}
 public static void Run(object connection,int cookie,string fixture,string dll) {
  var app=(ISldWorks)connection;
  var model=(ModelDoc2)app.ActiveDoc;
  Check(model!=null && string.Equals(model.GetPathName(),Path.GetFullPath(fixture),StringComparison.OrdinalIgnoreCase),"isolated fixture is active");
  var manager=app.GetCommandManager(cookie);
  var tabs=((object[])manager.CommandTabs(2)).Cast<CommandTab>().ToArray();
  Check(tabs.Count(t=>t.Name=="beamng.cad")==1,"exactly one beamng.cad assembly tab");
  var tab=tabs.Single(t=>t.Name=="beamng.cad");
  var ids=new System.Collections.Generic.List<int>();
  foreach(CommandTabBox box in (object[])tab.CommandTabBoxes()) {object commands,styles;box.GetCommands(out commands,out styles);ids.AddRange((int[])commands);}
  Check(ids.Count==6 && ids.Distinct().Count()==6,"six distinct toolbar actions in the assembly tab");
  Console.WriteLine("TAB_COMMANDS="+string.Join(",",ids));
  Console.WriteLine("FRAME_HWND="+((Frame)app.Frame()).GetHWndx64());
  var assembly=Assembly.LoadFrom(dll);
  var preparation=assembly.GetType("BeamNG.Cad.Preparation.PreparationFile");
  var saved=preparation.GetMethod("Load").Invoke(null,new object[]{fixture});
  var frame=preparation.GetMethod("Frame").Invoke(saved,new object[]{model.ConfigurationManager.ActiveConfiguration.Name});
  var selection=Activator.CreateInstance(assembly.GetType("BeamNG.Cad.Preparation.FrameSelection"),app,model);
  var summary=(string)selection.GetType().GetMethod("Summary").Invoke(selection,new[]{frame});
  Check(summary.StartsWith("4 bodies"),"saved persistent references resolve after document close/reopen");
  selection.GetType().GetMethod("Show").Invoke(selection,new[]{frame});
  Check(((SelectionMgr)model.SelectionManager).GetSelectedObjectCount2(-1)==5,"reopened fixture restores saved selection");
  var off=Path.Combine(Path.GetDirectoryName(fixture),"preview.off");
  File.WriteAllText(off,"OFF\n4 4 0\n1 3 5\n5 3 5\n1 5 5\n1 3 6\n3 0 2 1\n3 0 1 3\n3 0 3 2\n3 1 2 3\n");
  var featureCount=model.GetFeatureCount();var dirty=model.GetSaveFlag();
  var preview=Activator.CreateInstance(assembly.GetType("BeamNG.Cad.Preparation.HullPreview"),app,model,off,"XYZ");
  try {
   var bodies=(System.Collections.ICollection)preview.GetType().GetField("bodies",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(preview);
   Check(bodies.Count<6 && bodies.Cast<Body2>().Sum(b=>b.GetEdgeCount())==6,"temporary hull paths preserve six deduplicated edges");
   var host=preview.GetType().GetField("displayHost",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(preview) as Component2;
   Check(host!=null,"assembly preview is displayed on a part component, not the invisible assembly document target");
   var expected=new[]{new[]{1d,3d,5d},new[]{5d,3d,5d},new[]{1d,5d,5d},new[]{1d,3d,6d}};
   var utility=(MathUtility)app.GetMathUtility();
   foreach(Body2 body in bodies) foreach(Vertex vertex in (object[])body.GetVertices()) {
    var point=(MathPoint)utility.CreatePoint(vertex.GetPoint());
    if(host.Transform2!=null)point=(MathPoint)point.MultiplyTransform(host.Transform2);
    var world=(double[])point.ArrayData;
    Check(expected.Any(p=>Enumerable.Range(0,3).All(i=>Math.Abs(p[i]-world[i])<1e-7)),"preview vertex retains assembly coordinates with a transformed display host");
   }
   Check(model.GetFeatureCount()==featureCount && model.GetSaveFlag()==dirty,"preview adds no assembly features or save changes");
  } finally {((IDisposable)preview).Dispose();}
  Check(model.GetFeatureCount()==featureCount && model.GetSaveFlag()==dirty,"preview disposal preserves the assembly");
 }
}
'@
[LiveAddinSmoke]::Run([SwConnection]::Connect($ProcessId),$AddInId,$Fixture,(Join-Path $OutputDirectory 'beamng.cad.dll'))
