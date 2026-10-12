param([Parameter(Mandatory=$true)][int]$SolidWorksProcessId,
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [Parameter(Mandatory=$true)][string]$Destination,[string]$Gate,[string]$InspectFeature,[switch]$AppendInspectedBody)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
$source=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$helper=$source.Substring($source.IndexOf('using System;'))
$helper=$helper.Substring(0,$helper.IndexOf(' static object Get('))
$helper=$helper.Replace('CurrentAssignmentInspectionTest','CurrentGeometrySelectionTest')
$helper+=@'
 static string Label(object item){return item is Feature?((Feature)item).Name:item is Body2?((Body2)item).Name:item is Face2?((Body2)((Face2)item).GetBody()).Name:item==null?null:item.GetType().Name;}
 static object SelectionInfo(ModelDoc2 model){
  if(model==null)return null;var s=(SelectionMgr)model.SelectionManager;
  return new {document=model.GetPathName(),count=s.GetSelectedObjectCount2(-1),items=Enumerable.Range(1,s.GetSelectedObjectCount2(-1)).Select(i=>Label(s.GetSelectedObject6(i,-1))).ToArray(),preselected=Label(s.GetPreSelectedObject())};
 }
 public static void Run(int pid,string dll,string output,string inspectFeature,bool appendBody){
  var app=Find(pid);var model=app.ActiveDoc as ModelDoc2;
  if(model==null)throw new Exception("No active assembly");
  var manager=(SelectionMgr)model.SelectionManager;var rows=new List<object>();
  var dirty=model.GetSaveFlag();var config=model.ConfigurationManager.ActiveConfiguration.Name;
  var edit=model is AssemblyDoc?((AssemblyDoc)model).GetEditTarget() as ModelDoc2:null;
  var context=new {assembly=SelectionInfo(model),edit=SelectionInfo(edit)};
  object inspected=null;
  if(!string.IsNullOrEmpty(inspectFeature)){
   var owner=manager.GetSelectedObjectsComponent4(1,-1) as Component2;
   var feature=owner.FeatureByName(inspectFeature) as Feature;
   var source=((PartDoc)owner.GetModelDoc2()).FeatureByName(inspectFeature) as Feature;
   object bodyInfo;var available=(owner.GetBodies3((int)swBodyType_e.swAllBodies,out bodyInfo) as object[] ?? new object[0]).Cast<Body2>().Where(b=>b.Name==inspectFeature).ToArray();
   inspected=new {name=inspectFeature,instance_feature=feature==null?null:feature.GetTypeName2(),source_feature=source==null?null:source.GetTypeName2(),suppressed=feature==null?(bool?)null:feature.IsSuppressed(),
    faces=feature==null?0:feature.GetFaceCount(),source_faces=source==null?0:source.GetFaceCount(),available_bodies=available.Select(b=>new{name=b.Name,type=b.GetType(),visible=b.Visible}).ToArray()};
   if(appendBody){if(available.Length!=1||!available[0].Visible)throw new Exception("Requested body is not uniquely visible");if(!available[0].Select2(true,manager.CreateSelectData()))throw new Exception("SolidWorks rejected explicit body selection");}
  }
  for(int i=1;i<=manager.GetSelectedObjectCount2(-1);i++){
   var item=manager.GetSelectedObject6(i,-1);var owner=item as Component2 ?? manager.GetSelectedObjectsComponent4(i,-1) as Component2;
   if(item is Feature && ((Feature)item).GetSpecificFeature2() is Component2)owner=(Component2)((Feature)item).GetSpecificFeature2();
   var faces=item is Feature?(((Feature)item).GetFaces() as object[] ?? new object[0]):new object[0];
   rows.Add(new {index=i,kind=((swSelectType_e)manager.GetSelectedObjectType3(i,-1)).ToString(),feature=item is Feature?((Feature)item).GetTypeName2():null,
    component=owner==null?null:owner.Name2,state=owner==null?-1:owner.GetSuppression2(),body=item is Body2?((Body2)item).Name:null,
    feature_bodies=faces.Cast<Face2>().Select(f=>f.GetBody() as Body2).Where(b=>b!=null).Select(b=>new{name=b.Name,type=b.GetType()}).Distinct().ToArray()});
  }
  var code=Assembly.LoadFrom(dll);var selection=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.FrameSelection"),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,new object[]{app,model,true},null);
  string error=null,summary=null;
  try{var capture=selection.GetType().GetMethod("Capture").Invoke(selection,null);summary=(string)selection.GetType().GetMethod("Summary").Invoke(selection,new[]{capture});}
  catch(TargetInvocationException e){error=e.InnerException.ToString();}
  var result=new {context=context,inspected=inspected,selection=rows,error=error,summary=summary,dirty_unchanged=model.GetSaveFlag()==dirty,configuration_unchanged=model.ConfigurationManager.ActiveConfiguration.Name==config};
  var json=new JavaScriptSerializer().Serialize(result);File.WriteAllText(Path.Combine(output,"selection.json"),json);Console.WriteLine(json);
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $helper
if($Gate){Write-Output "GEOMETRY_PROBE_PID=$PID";while(-not (Test-Path -LiteralPath $Gate)){Start-Sleep -Milliseconds 250}}
[CurrentGeometrySelectionTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination),$InspectFeature,[bool]$AppendInspectedBody)
