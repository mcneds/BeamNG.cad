param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$Destination,[string]$ComponentPattern='spring|coil|shock|damper',[string]$DocumentPath,[int]$MaximumBodies=0,[int]$MaximumFaces=6)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
[IO.File]::WriteAllText((Join-Path $Destination 'component-pattern.txt'),$ComponentPattern)
[IO.File]::WriteAllText((Join-Path $Destination 'document-path.txt'),$DocumentPath)
[IO.File]::WriteAllText((Join-Path $Destination 'sample-limits.txt'),"$MaximumBodies,$MaximumFaces")
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class SpringAppearanceInspection {
 static object[] Renders(object values){return (values as object[]??new object[0]).Cast<RenderMaterial>().Select(r=>(object)new {file=r.FileName,primary=r.PrimaryColor,linked=r.LinkToFile,form=r.ColorForm,entities=(r.GetEntities() as object[]??new object[0]).Select(e=>e is Face2?"face":e is Body2?"body":e is Component2?"component:"+((Component2)e).Name2:e is Feature?"feature":"other").ToArray()}).ToArray();}
 public static void Run(int pid,string dll,string output){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var documentPath=File.ReadAllText(Path.Combine(output,"document-path.txt"));if(!string.IsNullOrEmpty(documentPath))documentPath=Path.GetFullPath(documentPath);
  var model=string.IsNullOrEmpty(documentPath)?app.ActiveDoc as ModelDoc2:app.GetOpenDocumentByName(documentPath) as ModelDoc2;if(model==null)throw new Exception("Requested document must already be open");
  Console.WriteLine("Reading already-open document: "+model.GetPathName());
  var dirty=model.GetSaveFlag();var code=Assembly.LoadFrom(dll);var rows=new List<object>();
  var scene=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.SolidWorksAppearances+Scene"),BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance,null,new object[]{model},null);
  var assembly=model as AssemblyDoc;var instances=assembly==null?new object[0]:(assembly.GetComponents(false) as object[]??new object[0]);
  var pattern=File.ReadAllText(Path.Combine(output,"component-pattern.txt"));
  var limits=File.ReadAllText(Path.Combine(output,"sample-limits.txt")).Split(',').Select(int.Parse).ToArray();
  foreach(var instance in instances.Cast<Component2>().Where(c=>System.Text.RegularExpressions.Regex.IsMatch(c.Name2,pattern,System.Text.RegularExpressions.RegexOptions.IgnoreCase))){
   var part=instance.GetModelDoc2() as ModelDoc2;Console.WriteLine("Component "+instance.Name2+" resolved="+(part!=null));if(part==null)continue;object info;
   // Component body queries support solid and sheet types separately.
   var bodies=(instance.GetBodies3((int)swBodyType_e.swSolidBody,out info) as object[]??new object[0]).Concat(instance.GetBodies3((int)swBodyType_e.swSheetBody,out info) as object[]??new object[0]);
   foreach(Body2 body in (limits[0]>0?bodies.Take(limits[0]):bodies)){
    var reader=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.SolidWorksAppearances"),BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance,null,new object[]{app,instance,body,scene},null);
    var bodyFaces=body.GetFaces() as object[]??new object[0];Console.WriteLine("Inspecting "+instance.Name2+" / "+body.Name+" (sample of "+bodyFaces.Length+" faces)");
    var faces=new List<object>();foreach(Face2 face in bodyFaces.Take(limits[1])){
     var sourceFace=part.Extension.GetCorresponding2(face) as Face2??face;
     faces.Add(new {captured=reader.GetType().GetMethod("Read").Invoke(reader,new object[]{face}),legacy=sourceFace.GetMaterialPropertyValues2(1,null)});
    }
    rows.Add(new {component=instance.Name2,part=part.GetPathName(),body=body.Name,body_legacy=body.MaterialPropertyValues2,part_legacy=part.MaterialPropertyValues,component_legacy=instance.GetMaterialPropertyValues2(1,null),component_renders=Renders(instance.GetRenderMaterials2(1,null)),part_renders=Renders(part.Extension.GetRenderMaterials2(1,null)),faces});
   }
  }
  if(model.GetSaveFlag()!=dirty)throw new Exception("Unexpected dirty-state change");
  var report=new {document=model.GetPathName(),documents=(app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().Select(d=>d.GetPathName()).ToArray(),assembly_renders=Renders(model.Extension.GetRenderMaterials2(1,null)),rows};
  File.WriteAllText(Path.Combine(output,"appearances.json"),new JavaScriptSerializer {MaxJsonLength=int.MaxValue}.Serialize(report));Console.WriteLine("Read-only appearance inspection: "+rows.Count+" spring/coilover bodies");
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[SpringAppearanceInspection]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
