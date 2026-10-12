param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$PartPath,[string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class PartAppearanceInspection {
 public static void Run(int pid,string path,string output){
  path=Path.GetFullPath(path);
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var original=app.ActiveDoc as ModelDoc2;var originalDirty=original!=null&&original.GetSaveFlag();
  var part=app.GetOpenDocumentByName(path) as ModelDoc2;var owned=part==null;int error=0,warning=0;
  try {
   if(owned)part=app.OpenDoc6(path,1,3,"",ref error,ref warning) as ModelDoc2;
   if(part==null)throw new Exception("Could not inspect part read-only: "+error);
   var dirty=part.GetSaveFlag();
   var renders=(part.Extension.GetRenderMaterials2(1,null) as object[]??new object[0]).Cast<RenderMaterial>().Select(r=>new {file=r.FileName,primary=r.PrimaryColor,entities=(r.GetEntities() as object[]??new object[0]).Select(e=>e is Face2?"face":e is Body2?"body:"+((Body2)e).Name:e is Feature?"feature":"document").ToArray()}).ToArray();
   var bodies=((PartDoc)part).GetBodies2(-1,false) as object[]??new object[0];
   var rows=bodies.Cast<Body2>().Select(b=>new {name=b.Name,legacy=b.MaterialPropertyValues2,faces=(b.GetFaces() as object[]??new object[0]).Cast<Face2>().Take(1).Select(f=>new {legacy=f.GetMaterialPropertyValues2(1,null),feature=(f.GetFeature() as Feature)==null?null:((Feature)f.GetFeature()).Name}).ToArray()}).ToArray();
   File.WriteAllText(output,new JavaScriptSerializer{MaxJsonLength=int.MaxValue}.Serialize(new {path,legacy=part.MaterialPropertyValues,renders,rows}));
   if(part.GetSaveFlag()!=dirty)throw new Exception("Part dirty state changed");
   Console.WriteLine("Inspected "+rows.Length+" bodies and "+renders.Length+" native finishes; no saves");
  }finally{if(owned&&part!=null)app.CloseDoc(part.GetTitle());if(original!=null){app.ActivateDoc3(original.GetTitle(),false,0,ref error);if(original.GetSaveFlag()!=originalDirty)throw new Exception("Original dirty state changed");}}
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[PartAppearanceInspection]::Run($SolidWorksProcessId,$PartPath,$Destination)
