param([Parameter(Mandatory=$true)][string]$Assembly,[Parameter(Mandatory=$true)][string]$Part,
 [Parameter(Mandatory=$true)][string]$Output,[string]$ReplaceSourceInMemory)
$ErrorActionPreference='Stop'
if(Get-Process SLDWORKS -ErrorAction SilentlyContinue){throw 'Close SolidWorks before owned context inspection'}
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use PowerShell -STA'}
if(Test-Path -LiteralPath $Output){throw 'Use a new output path'}
$interop=Join-Path $PSScriptRoot '../artifacts/actual-cad-integration-20261010'
$refs=@('System.Core','System.Web.Extensions',(Join-Path $interop 'SolidWorks.Interop.sldworks.dll'),(Join-Path $interop 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;using System.IO;using System.Linq;using System.Collections.Generic;
using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public static class MirrorMaterialContext {
 static object References(ISldWorks app,ModelDoc2 part){var rows=new List<object>();
  for(var f=(Feature)part.FirstFeature();f!=null;f=(Feature)f.GetNextFeature()){
   var mirror=f.GetDefinition() as MirrorPartFeatureData;if(mirror==null)continue;
   bool access=mirror.AccessSelections(part,null);try{var source=mirror.GetModelDoc();rows.Add(new{feature=f.Name,declared=mirror.PathName,access=access,resolved=source==null?null:source.GetPathName(),materials=source==null?null:Read(source)});}finally{if(access)mirror.ReleaseSelectionAccess();}
  }
  return new{dependencies=app.GetDocumentDependencies2(part.GetPathName(),false,true,false),features=rows};
 }
 static object Read(ModelDoc2 d){return ((object[])((PartDoc)d).GetBodies2(-1,false)??new object[0]).Cast<Body2>().Select(b=>{
  string db;var name=b.GetMaterialPropertyName(d.ConfigurationManager.ActiveConfiguration.Name,out db);
  var mass=(MassProperty2)d.Extension.CreateMassProperty2();mass.UseSystemUnits=true;mass.SelectedItems=new[]{new System.Runtime.InteropServices.DispatchWrapper(b)};mass.Recalculate();
  return new{body=b.Name,material=name,database=db,density=mass.Volume>0?mass.Mass/mass.Volume:0,reference=Convert.ToBase64String((byte[])d.Extension.GetPersistReference3(b)),shape=b.GetMassProperties(1)};
 }).ToArray();}
 public static void Run(string assembly,string path,string output,string replacement){
  var j=new JavaScriptSerializer{MaxJsonLength=int.MaxValue};ISldWorks app=null;var result=new Dictionary<string,object>();
  try{app=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));app.Visible=false;app.UserControl=false;
   int e=0,w=0;var part=(ModelDoc2)app.OpenDoc6(path,1,3,"Default",ref e,ref w);if(part==null)throw new Exception("Part open: "+e);
   result["before"]=Read(part);result["references_before"]=References(app,part);File.WriteAllText(output,j.Serialize(result));Console.WriteLine("Part loaded read-only");
   for(var f=(Feature)part.FirstFeature();f!=null;f=(Feature)f.GetNextFeature()){
    var mirror=f.GetDefinition() as MirrorPartFeatureData;if(mirror==null)continue;
    var source=(ModelDoc2)app.OpenDoc6(mirror.PathName,1,3,"Default",ref e,ref w);if(source==null)throw new Exception("Declared source open: "+e);result["loaded_source"]=new{path=source.GetPathName(),materials=Read(source)};
   }
   var context=(ModelDoc2)app.OpenDoc6(assembly,2,3,"Default",ref e,ref w);if(context==null)throw new Exception("Assembly open: "+e);
   var mirrors=new List<object>();for(var f=(Feature)context.FirstFeature();f!=null;f=(Feature)f.GetNextFeature()){
    var m=f.GetDefinition() as MirrorComponentFeatureData;if(m!=null)mirrors.Add(new{name=f.Name,options=m.MirrorTransferOptions,broken=m.BreakLinksToOriginalPart,propagate=m.PropagateFromOriginalPart,folder=m.MirrorComponentsFolderLocation});
   }
   result["mirror_features"]=mirrors;
   result["components"]=((object[])((AssemblyDoc)context).GetComponents(false)??new object[0]).Cast<Component2>().Select(c=>new{name=c.Name2,path=c.GetPathName(),configuration=c.ReferencedConfiguration}).ToArray();
   if(!string.IsNullOrEmpty(replacement)){
    var source=((object[])((AssemblyDoc)context).GetComponents(false)).Cast<Component2>().Single(c=>c.Name2=="RL_wheel-1");
    app.ActivateDoc3(context.GetTitle(),false,0,ref e);context.ClearSelection2(true);if(!source.Select4(false,null,false))throw new Exception("Source component selection failed");
    result["source_replacement_in_memory"]=((AssemblyDoc)context).ReplaceComponents2(replacement,"Default",false,0,false);context.ClearSelection2(true);
    File.WriteAllText(output,j.Serialize(result));
   }
   Console.WriteLine("Context loaded; rebuilding in memory only");result["rebuild_ok"]=context.ForceRebuild3(false);part.ForceRebuild3(false);result["after"]=Read(part);
   result["references_after"]=References(app,part);result["saved"]=false;File.WriteAllText(output,j.Serialize(result));Console.WriteLine("Inspection archived; no files saved");
  }finally{if(app!=null)app.ExitApp();}
 }
}
'@
[MirrorMaterialContext]::Run((Resolve-Path -LiteralPath $Assembly).Path,(Resolve-Path -LiteralPath $Part).Path,[IO.Path]::GetFullPath($Output),$ReplaceSourceInMemory)
