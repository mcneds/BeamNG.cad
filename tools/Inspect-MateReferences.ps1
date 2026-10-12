param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$Destination)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class MateReferenceProbe {
 static ModelDoc2 model;static List<string> lines=new List<string>();static HashSet<string> seen;
 static void Visit(object item,string indent){
  if(item==null||indent.Length>20)return;
  var bytes=model.Extension.GetPersistReference3(item) as byte[];var key=bytes==null?null:Convert.ToBase64String(bytes);
  var f=item as Feature;var e=item as Entity;var owner=e==null?null:e.GetComponent() as Component2;
  lines.Add(indent+(f==null?item.GetType().Name:f.GetTypeName2()+":"+f.Name)+" owner="+(owner==null?"none":owner.Name2));
  if(key!=null&&!seen.Add(key))return;
  if(f!=null){
   var data=f.GetDefinition();object[] refs=null;
   try {if(data is RefPointFeatureData)refs=((RefPointFeatureData)data).Selections as object[];
    else if(data is RefPlaneFeatureData)refs=((RefPlaneFeatureData)data).Selections as object[];
    else if(data is RefAxisFeatureData){object types;refs=((RefAxisFeatureData)data).GetSelections(out types) as object[];}
   }catch(Exception ex){lines.Add(indent+"READ ERROR "+ex.Message);}
   foreach(var r in refs??new object[0])Visit(r,indent+" s");
   foreach(var p in f.GetParents() as object[]??new object[0])Visit(p,indent+" p");
   var sketch=f.GetSpecificFeature2() as Sketch;
   if(sketch!=null)foreach(var p in sketch.GetSketchPoints2() as object[]??new object[0])Visit(p,indent+" k");
  }
  object[] relations=null;
  if(item is SketchPoint)relations=((SketchPoint)item).GetRelations() as object[];
  if(item is SketchSegment)relations=((SketchSegment)item).GetRelations() as object[];
  foreach(SketchRelation r in relations??new object[0]){
   foreach(var v in r.GetEntities() as object[]??new object[0])Visit(v,indent+" r");
   foreach(var v in r.GetDefinitionEntities() as object[]??new object[0])Visit(v,indent+" d");
  }
 }
 public static void Run(int pid,string output){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});model=(ModelDoc2)app.ActiveDoc;
  int stamp=model.GetUpdateStamp();bool dirty=model.GetSaveFlag();
  foreach(var name in new[]{"Axis1","PLANE1","Upper Sus Tab Mount Point","FL_mirror_Upper Sus Tab Mount Point"}){
   lines.Add("ROOT "+name);seen=new HashSet<string>();Visit(((AssemblyDoc)model).FeatureByName(name),"");
  }
  if(stamp!=model.GetUpdateStamp()||dirty!=model.GetSaveFlag())throw new Exception("CAD changed during inspection");
  File.WriteAllLines(output,lines);Console.WriteLine(string.Join("\n",lines));
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[MateReferenceProbe]::Run($SolidWorksProcessId,$Destination)
