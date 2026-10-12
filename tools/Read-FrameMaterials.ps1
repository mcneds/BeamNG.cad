param(
 [string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\material-integration'),
 [string]$Generation='C:\Users\ak1di\AppData\Local\beamng.cad\builds\generation-verified-frame-20261005',
 [string]$Destination,
 [string]$AssemblyDocument,
 [int]$ProcessId,
 [switch]$OwnedSession,
 [switch]$ExportGeometry
)
$ErrorActionPreference='Stop'
if($OwnedSession){if(Get-Process SLDWORKS -ErrorAction SilentlyContinue){throw 'An owned read-only session requires no existing SolidWorks process'}}
else {
 if(-not $ProcessId){$instances=@(Get-Process SLDWORKS -ErrorAction Stop);if($instances.Count -ne 1){throw 'Specify the SolidWorks ProcessId when multiple instances are running'};$ProcessId=$instances[0].Id}
 . (Join-Path $PSScriptRoot 'Connect-SolidWorks.ps1') -ProcessId $ProcessId
}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
if(-not $Destination){$Destination=Join-Path $OutputDirectory ('native-materials-'+[Guid]::NewGuid().ToString('N'))}
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Xml','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Serialization.Json;
using SolidWorks.Interop.sldworks;
public static class ReadFrameMaterials {
 public static void RunOwned(string dll,string geometry,string destination,bool export,string document){var app=Create();try{Run(app,dll,geometry,destination,export,document);}finally{app.ExitApp();}}
 public static ISldWorks Create(){var app=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));app.Visible=false;return app;}
 public static void Close(object connection){((ISldWorks)connection).ExitApp();}
 public static void Run(object connection,string dll,string geometry,string destination,bool export,string document){
  var app=(ISldWorks)connection;
  var code=Assembly.LoadFrom(dll);var packageType=code.GetType("BeamNG.Cad.Preparation.GeometryPackage");
  object package=null;
  if(document==null)using(var f=File.OpenRead(geometry))package=new DataContractJsonSerializer(packageType).ReadObject(f);
  var original=document??(string)packageType.GetField("SourceDocument").GetValue(package);
  var model=(ModelDoc2)app.ActiveDoc;
  if(model==null){int errors=0,warnings=0;model=(ModelDoc2)app.OpenDoc6(original,2,3,"",ref errors,ref warnings);if(model==null)throw new Exception("Read-only assembly open failed: "+errors);}
  if(!string.Equals(model.GetPathName(),original,StringComparison.OrdinalIgnoreCase))throw new Exception("Activate the original frame assembly before reading its saved selection");
  object frame;
  if(package!=null)frame=packageType.GetField("Assignment").GetValue(package);
  else {var preparationType=code.GetType("BeamNG.Cad.Preparation.PreparationFile");object saved;
   using(var f=File.OpenRead(original+".truemesh-prep.json"))saved=new DataContractJsonSerializer(preparationType).ReadObject(f);
   frame=preparationType.GetMethod("Frame").Invoke(saved,new object[]{model.ConfigurationManager.ActiveConfiguration.Name});}
  var selectionType=code.GetType("BeamNG.Cad.Preparation.FrameSelection");
  var selection=Activator.CreateInstance(selectionType,app,model);
  int stamp=model.GetUpdateStamp();bool dirty=model.GetSaveFlag();
  var snapshot=selectionType.GetMethod("ReadMaterials").Invoke(selection,new[]{frame});
  Console.WriteLine(snapshot.GetType().GetMethod("Summary").Invoke(snapshot,null));
  using(var f=File.Create(Path.Combine(destination,"material-snapshot.json")))new DataContractJsonSerializer(snapshot.GetType()).WriteObject(f,snapshot);
  if(export)selectionType.GetMethod("Export").Invoke(selection,new[]{frame,(object)destination});
  if(model.GetUpdateStamp()!=stamp || model.GetSaveFlag()!=dirty)throw new Exception("Document state changed during read/export");
  Console.WriteLine("PASS native assignments read without changing document state");
  Console.WriteLine("MATERIAL_SNAPSHOT="+destination);
 }
}
'@
if($OwnedSession){[ReadFrameMaterials]::RunOwned((Join-Path $OutputDirectory 'beamng.cad.dll'),(Join-Path $Generation 'source\geometry.json'),$Destination,$ExportGeometry.IsPresent,$AssemblyDocument)}
else{[ReadFrameMaterials]::Run([SwConnection]::Connect($ProcessId),(Join-Path $OutputDirectory 'beamng.cad.dll'),(Join-Path $Generation 'source\geometry.json'),$Destination,$ExportGeometry.IsPresent,$AssemblyDocument)}
