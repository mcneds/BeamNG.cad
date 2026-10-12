param([Parameter(Mandatory=$true)][string]$Part,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
if(Get-Process SLDWORKS -ErrorAction SilentlyContinue){throw 'Close SolidWorks before owned material inspection'}
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use PowerShell -STA'}
if(Test-Path -LiteralPath $Output){throw 'Use a fresh output path'}
$interop=Join-Path $PSScriptRoot '../artifacts/actual-cad-integration-20261010'
$refs=@('System.Core','System.Web.Extensions',(Join-Path $interop 'SolidWorks.Interop.sldworks.dll'))
[void][Reflection.Assembly]::LoadFrom($refs[2])
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;using System.IO;using System.Linq;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public static class PartMaterialReadback {
 public static void Run(string path,string output){ISldWorks app=null;try{
  app=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));app.Visible=false;app.UserControl=false;
  int e=0,w=0;var model=(ModelDoc2)app.OpenDoc6(path,1,3,"Default",ref e,ref w);if(model==null)throw new Exception("Open failed: "+e);
  var part=(PartDoc)model;var config=model.ConfigurationManager.ActiveConfiguration.Name;string db;var name=part.GetMaterialPropertyName2(config,out db);
  var bodies=((object[])part.GetBodies2(-1,false)??new object[0]).Cast<Body2>().Select(b=>{string bd;var bn=b.GetMaterialPropertyName(config,out bd);return new{body=b.Name,name=string.IsNullOrWhiteSpace(bn)?name:bn,database=string.IsNullOrWhiteSpace(bn)?db:bd};}).ToArray();
  File.WriteAllText(output,new JavaScriptSerializer{MaxJsonLength=int.MaxValue}.Serialize(new{path=path,configuration=config,name=name,database=db,bodies=bodies}));
 }finally{if(app!=null)app.ExitApp();}}
}
'@
$before=(Get-FileHash -LiteralPath $Part -Algorithm SHA256).Hash
[PartMaterialReadback]::Run([IO.Path]::GetFullPath($Part),[IO.Path]::GetFullPath($Output))
if((Get-FileHash -LiteralPath $Part -Algorithm SHA256).Hash -ne $before){throw 'Source changed during read-only inspection'}
Get-Content -LiteralPath $Output
