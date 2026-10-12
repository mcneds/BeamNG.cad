param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\bulk-material'))
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$refs=@('System.Core','System.Xml','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'))
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Serialization.Json;
using SolidWorks.Interop.sldworks;
public static class SavedMaterialTargetsSmoke {
 public static void Run(string dll){
  var app=(ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
  var model=(ModelDoc2)app.ActiveDoc;
  Console.WriteLine("CAD_VISIBLE="+app.Visible+" DOCUMENTS="+app.GetDocumentCount());
  if(model==null)throw new Exception("No active assembly; saved-frame check not run.");
  Console.WriteLine("ACTIVE_DOCUMENT="+model.GetPathName());
  var code=Assembly.LoadFrom(dll);var prep=code.GetType("BeamNG.Cad.Preparation.PreparationFile");object file;
  using(var stream=File.OpenRead(model.GetPathName()+".truemesh-prep.json"))file=new DataContractJsonSerializer(prep).ReadObject(stream);
  var frame=prep.GetMethod("Frame").Invoke(file,new object[]{model.ConfigurationManager.ActiveConfiguration.Name});
  var type=code.GetType("BeamNG.Cad.Preparation.FrameSelection");var selection=Activator.CreateInstance(type,app,model);
  var before=type.GetMethod("ReadMaterials").Invoke(selection,new object[]{frame});
  var fingerprint=(string)before.GetType().GetMethod("Fingerprint").Invoke(before,null);
  var targets=type.GetMethod("MaterialBodies").Invoke(selection,new object[]{frame});
  var bulk=code.GetType("BeamNG.Cad.Preparation.BulkMaterialAssignment");
  using(var operation=(IDisposable)Activator.CreateInstance(bulk,app,model,targets)){
   var count=(int)bulk.GetProperty("Count").GetValue(operation,null);
   if(count!=60)throw new Exception("Expected the saved 60-body frame; found "+count);
   Console.WriteLine("PASS all 60 saved frame bodies resolve to writable material targets");
  }
  var after=type.GetMethod("ReadMaterials").Invoke(selection,new object[]{frame});
  if(fingerprint!=(string)after.GetType().GetMethod("Fingerprint").Invoke(after,null))throw new Exception("Material snapshot changed during preflight.");
  if(app.ActiveDoc!=model)throw new Exception("Assembly was not restored.");
  Console.WriteLine("PASS saved-frame preflight preserves native materials and active assembly");
 }
}
'@
[SavedMaterialTargetsSmoke]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'))
