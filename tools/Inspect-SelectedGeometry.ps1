param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$Destination)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class SelectedGeometryProbe {
 static object[] Bodies(Component2 c,int kind){object info;return c.GetBodies3(kind,out info) as object[]??new object[0];}
 static object[] Features(ModelDoc2 model){var features=new List<object>();for(var f=model.FirstFeature() as Feature;f!=null&&features.Count<150;f=f.GetNextFeature() as Feature)features.Add(new{name=f.Name,type=f.GetTypeName2(),suppressed=f.IsSuppressed2((int)swInConfigurationOpts_e.swThisConfiguration,null)});return features.ToArray();}
 public static void Run(int pid,string destination){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var model=(ModelDoc2)app.ActiveDoc;var manager=(SelectionMgr)model.SelectionManager;var records=new List<object>();
  for(var i=1;i<=manager.GetSelectedObjectCount2(-1);i++){
   var component=manager.GetSelectedObject6(i,-1) as Component2??manager.GetSelectedObjectsComponent4(i,-1) as Component2;
   if(component==null)continue;var part=component.GetModelDoc2() as ModelDoc2;
   records.Add(new {name=component.Name2,path=component.GetPathName(),suppression=component.GetSuppression2(),configuration=component.ReferencedConfiguration,loaded_configuration=part==null?null:part.ConfigurationManager.ActiveConfiguration.Name,
    children=(component.GetChildren() as object[]??new object[0]).Length,all=Bodies(component,-1).Length,solid=Bodies(component,0).Length,sheet=Bodies(component,1).Length,
    part_bodies=part is PartDoc?(((PartDoc)part).GetBodies2(-1,false) as object[]??new object[0]).Cast<Body2>().Select(b=>new{name=b.Name,type=b.GetType(),visible=b.Visible}).ToArray():null,
    features=part!=null&&Bodies(component,-1).Length==0?Features(part):null});
  }
  var json=new JavaScriptSerializer().Serialize(records);File.WriteAllText(destination,json);Console.WriteLine(json);
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[SelectedGeometryProbe]::Run($SolidWorksProcessId,$Destination)
