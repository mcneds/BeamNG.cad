param([Parameter(Mandatory=$true)][int]$SolidWorksProcessId,
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
$source=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$helper=$source.Substring($source.IndexOf('using System;'))
$helper=$helper.Substring(0,$helper.IndexOf(' static object Get(')).Replace('CurrentAssignmentInspectionTest','GeometryPickKindsTest')
$helper+=@'
 public static void Run(int pid,string dll,string output){
  var app=Find(pid);var model=(ModelDoc2)app.ActiveDoc;var code=Assembly.LoadFrom(dll);var manager=(SelectionMgr)model.SelectionManager;
  var type=code.GetType("BeamNG.Cad.Preparation.FrameSelection");var selection=Activator.CreateInstance(type,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,new object[]{app,model,true},null);
  var original=Enumerable.Range(1,manager.GetSelectedObjectCount2(-1)).Select(i=>Convert.ToBase64String((byte[])model.Extension.GetPersistReference3(manager.GetSelectedObject6(i,-1)))).ToArray();
  var dirty=model.GetSaveFlag();var config=model.ConfigurationManager.ActiveConfiguration.Name;var cases=new List<object>();
  using(var preserved=(IDisposable)Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.SelectionSnapshot"),new object[]{model})){
   var capture=type.GetMethod("Capture").Invoke(selection,null);
   // Resolve the first saved body directly so sheets are tested too.
   var refs=(System.Collections.IList)capture.GetType().GetField("Selections").GetValue(capture);var first=refs[refs.Count-1];int err;
   var body=(Body2)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String((string)first.GetType().GetField("Reference").GetValue(first)),out err);
   var faces=(body.GetFaces() as object[]).Cast<Face2>().ToArray();var edges=((object[])body.GetEdges()).Cast<Edge>().ToArray();var edge=edges.FirstOrDefault(e=>e.GetStartVertex()!=null)??edges.First();var vertex=edge.GetStartVertex() as Vertex;
   var variants=new List<Tuple<string,object[]>>{Tuple.Create("body",new object[]{body}),Tuple.Create("face",new object[]{faces[0]}),Tuple.Create("edge",new object[]{edge})};
   if(faces.Length>1)variants.Add(Tuple.Create("overlapping faces",new object[]{faces[0],faces[faces.Length-1]}));
   if(vertex!=null)variants.Add(Tuple.Create("vertex",new object[]{vertex}));
   foreach(var test in variants){
    model.ClearSelection2(true);foreach(var item in test.Item2){var data=manager.CreateSelectData();var selected=item is Body2?((Body2)item).Select2(true,data):item is Entity?((Entity)item).Select4(true,data):manager.AddSelectionListObject(item,data);if(!selected)throw new Exception("Cannot select "+test.Item1);}
    var result=type.GetMethod("Capture").Invoke(selection,null);var ids=(List<string>)type.GetMethod("BodyIds").Invoke(selection,new[]{result});
    if(ids.Count!=1)throw new Exception(test.Item1+" captured "+ids.Count+" bodies");cases.Add(new {kind=test.Item1,selected_items=manager.GetSelectedObjectCount2(-1),unique_bodies=ids.Count});
   }
  }
  var after=Enumerable.Range(1,manager.GetSelectedObjectCount2(-1)).Select(i=>Convert.ToBase64String((byte[])model.Extension.GetPersistReference3(manager.GetSelectedObject6(i,-1)))).ToArray();
  if(!original.SequenceEqual(after)||dirty!=model.GetSaveFlag()||config!=model.ConfigurationManager.ActiveConfiguration.Name)throw new Exception("User CAD state changed");
  var json=new JavaScriptSerializer().Serialize(new {status="passed",cases=cases,selection_preserved=true,dirty_unchanged=true,configuration_unchanged=true});File.WriteAllText(Path.Combine(output,"verification.json"),json);Console.WriteLine(json);
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $helper
[GeometryPickKindsTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
