param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\selection-materials'),[string]$Gate)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$refs=@('System.Core',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'))
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
public static class CurrentMaterialSelectionSmoke {
 static object Invoke(object value,string method,params object[] args){return value.GetType().GetMethod(method).Invoke(value,args);}
 static string[] Picks(ModelDoc2 doc){
  var manager=(SelectionMgr)doc.SelectionManager;
  return Enumerable.Range(1,manager.GetSelectedObjectCount2(-1)).Select(i=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(manager.GetSelectedObject6(i,-1)))+":"+manager.GetSelectedObjectMark(i)).ToArray();
 }
 public static void Run(string dll){
  var app=(ISldWorks)Marshal.GetActiveObject("SldWorks.Application");var model=(ModelDoc2)app.ActiveDoc;
  if(model==null)throw new Exception("Select the actual mixed frame geometry first.");
  var original=Picks(model);if(original.Length==0)throw new Exception("No current selection.");
  var prep=model.GetPathName()+".truemesh-prep.json";var saved=File.Exists(prep)?File.ReadAllBytes(prep):null;
  var code=Assembly.LoadFrom(dll);var selection=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.FrameSelection"),app,model);
  Console.WriteLine("INPUT_ITEMS="+original.Length);
  var frame=Invoke(selection,"Capture");
  Console.WriteLine("AFTER_CAPTURE_ITEMS="+Picks(model).Length+" EXACT_REFERENCES="+original.SequenceEqual(Picks(model)));
  Console.WriteLine(Invoke(selection,"Summary",frame));
  var fingerprint=Invoke(Invoke(selection,"ReadMaterials",frame),"Fingerprint");
  var targets=Invoke(selection,"MaterialBodies",frame);
  var bulk=code.GetType("BeamNG.Cad.Preparation.BulkMaterialAssignment");
  using(var operation=(IDisposable)Activator.CreateInstance(bulk,app,model,targets))
   Console.WriteLine("MATERIAL_TARGETS="+bulk.GetProperty("Count").GetValue(operation,null));
  if(!Equals(fingerprint,Invoke(Invoke(selection,"ReadMaterials",frame),"Fingerprint")))throw new Exception("Material fingerprint changed.");
  var restored=Picks(model);
  Console.WriteLine("RESTORED_ITEMS="+restored.Length+" EXACT_REFERENCES="+original.SequenceEqual(restored));
  if(!original.SequenceEqual(restored))throw new Exception("Selection changed.");
  if(app.ActiveDoc!=model)throw new Exception("Active document changed.");
  if(saved!=null && !saved.SequenceEqual(File.ReadAllBytes(prep)))throw new Exception("Saved frame assignment changed.");
  Console.WriteLine("PASS mixed current selection resolves without changing materials, saved frame, active document or selected items");
 }
}
'@
if($Gate){Write-Output "CURRENT_TEST_PID=$PID";while(-not (Test-Path -LiteralPath $Gate)){Start-Sleep -Milliseconds 250}}
[CurrentMaterialSelectionSmoke]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'))
