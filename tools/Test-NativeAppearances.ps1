param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$Destination,[string]$ComponentName)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class NativeAppearanceTest {
 public static void Run(int pid,string dll,string output,string requestedComponent){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var model=(ModelDoc2)app.ActiveDoc;var manager=(SelectionMgr)model.SelectionManager;var dirty=model.GetSaveFlag();var count=manager.GetSelectedObjectCount2(-1);
  var code=Assembly.LoadFrom(dll);var exporter=code.GetType("BeamNG.Cad.StlAssemblyExporter");var read=exporter.GetMethod("ExportSelectedBodyWithAppearance",BindingFlags.Static|BindingFlags.NonPublic);var records=new List<object>();
  var candidates=string.IsNullOrEmpty(requestedComponent)?Enumerable.Range(1,count).Select(i=>manager.GetSelectedObject6(i,-1) as Component2??manager.GetSelectedObjectsComponent4(i,-1) as Component2):
   (((AssemblyDoc)model).GetComponents(false) as object[]??new object[0]).Cast<Component2>().Where(c=>c.Name2.EndsWith(requestedComponent,StringComparison.Ordinal));
  foreach(var component in candidates){
   if(component==null)continue;object info;var bodies=component.GetBodies3(-1,out info) as object[]??new object[0];
   foreach(Body2 body in bodies.Take(1)){
    var id="sample_"+records.Count;var file=Path.Combine(output,id+".stl");Console.WriteLine("Capturing "+component.Name2+" / "+body.Name);
    var ranges=read.Invoke(null,new object[]{app,component,body,file,component.Transform2});
    Console.WriteLine("Appearance capture complete");var serializer=new System.Runtime.Serialization.Json.DataContractJsonSerializer(ranges.GetType());
    using(var stream=File.Create(Path.Combine(output,id+".appearance.json")))serializer.WriteObject(stream,ranges);
    exporter.GetMethod("ExportSelectedBody",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{app,body,Path.Combine(output,id+".legacy.stl"),component.Transform2});
    records.Add(new {Id=id,File=id+".stl",Component=component.Name2,Body=body.Name});Console.WriteLine("PASS native face appearances captured: "+component.Name2+" / "+body.Name);
   }
   if(records.Count>0)break;
  }
  if(records.Count==0)throw new Exception("Select an existing CAD component with bodies for this read-only test");
  if(model.GetSaveFlag()!=dirty||manager.GetSelectedObjectCount2(-1)!=count)throw new Exception("CAD state changed");
  File.WriteAllText(Path.Combine(output,"samples.json"),new JavaScriptSerializer().Serialize(records));
  Console.WriteLine("PASS original CAD selection and dirty flag preserved");
 }
}
'@
$refs=@('System.Core','System.Web.Extensions','System.Runtime.Serialization','System.Xml',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[NativeAppearanceTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination,$ComponentName)
