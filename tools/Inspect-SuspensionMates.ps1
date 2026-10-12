param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$Destination,[string]$ComponentPattern='(^|_)FL_|steering|Frame',[switch]$Fast)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Choose a new evidence file'}
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class SuspensionMateInspection {
 static object Dofs(Component2 c){try {int a,b,d,e,f,g;MathPoint p,q;MathVector u,v,w,x;int result=c.GetRemainingDOFs(out a,out p,out b,out u,out d,out q,out e,out v,out f,out w,out g,out x);return new {result,rpoint1_status=a,rpoint1=p==null?null:p.ArrayData,rdirection1_status=b,rdirection1=u==null?null:u.ArrayData,rpoint2_status=d,rpoint2=q==null?null:q.ArrayData,rdirection2_status=e,rdirection2=v==null?null:v.ArrayData,tdirection1_status=f,tdirection1=w==null?null:w.ArrayData,tdirection2_status=g,tdirection2=x==null?null:x.ArrayData};}catch(Exception ex){return new {error=ex.Message};}}
 static string Kind(object entity){
  if(entity is Face2){var surface=(Surface)((Face2)entity).GetSurface();return surface.IsPlane()?"plane":surface.IsCylinder()?"cylinder":surface.IsSphere()?"sphere":"face";}
  if(entity is Edge){var curve=(Curve)((Edge)entity).GetCurve();return curve.IsCircle()?"circle":curve.IsLine()?"line":"edge";}
  if(entity is Vertex)return "point";
  if(entity is Feature)return "feature:"+((Feature)entity).GetTypeName2()+":"+((Feature)entity).Name;
  return entity==null?"missing":entity.GetType().Name;
 }
 static IEnumerable<Feature> Children(Feature p){for(var f=p.GetFirstSubFeature() as Feature;f!=null;f=f.GetNextSubFeature() as Feature){yield return f;foreach(var child in Children(f))yield return child;}}
 public static void Run(int pid,string output,string pattern,bool fast){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var model=app.ActiveDoc as ModelDoc2;var assembly=model as AssemblyDoc;if(assembly==null)throw new Exception("Active document must be the assembly");
  var dirty=model.GetSaveFlag();var stamp=model.GetUpdateStamp();var configuration=model.ConfigurationManager.ActiveConfiguration.Name;
  var selected=((SelectionMgr)model.SelectionManager).GetSelectedObjectCount2(-1);var rows=new List<object>();var mates=new List<object>();
  foreach(Component2 c in assembly.GetComponents(false) as object[]??new object[0]){
   var name=c.Name2;var interested=System.Text.RegularExpressions.Regex.IsMatch(name,pattern,System.Text.RegularExpressions.RegexOptions.IgnoreCase);
   rows.Add(new {name,path=c.GetPathName(),parent=c.GetParent()==null?null:c.GetParent().Name2,is_fixed=c.IsFixed(),suppression=c.GetSuppression2(),constraint_status=fast?-1:c.GetConstrainedStatus(),solving=fast?-1:c.Solving,transform=c.Transform2==null?null:c.Transform2.ArrayData,dofs=interested&&!fast?Dofs(c):null});
   if(interested||rows.Count%25==0)Console.WriteLine("Read component: "+name);
  }
  var seen=new HashSet<int>();
  for(var top=model.FirstFeature() as Feature;top!=null;top=top.GetNextFeature() as Feature){
   if(top.GetTypeName2()!="MateGroup")continue;
   foreach(var f in Children(top)){
    var mate=f.GetSpecificFeature2() as Mate2;if(mate==null||!seen.Add(f.GetID()))continue;
    var entities=new List<object>();for(int i=0;i<mate.GetMateEntityCount();i++){var e=mate.MateEntity(i);var c=e.ReferenceComponent as Component2;entities.Add(new {component=c==null?null:c.Name2,kind=Kind(e.Reference),reference_type=e.ReferenceType2,parameters=e.EntityParams});}
    bool warning;var error=f.GetErrorCode2(out warning);var definition=f.GetDefinition();object settings=null;
    if(definition is ConcentricMateFeatureData)settings=new {lock_rotation=((ConcentricMateFeatureData)definition).LockRotation};
    if(definition is DistanceMateFeatureData){var data=(DistanceMateFeatureData)definition;settings=new {distance=data.Distance,limits=data.IsAdvancedMate,minimum=data.MinimumDistance,maximum=data.MaximumDistance};}
    if(definition is AngleMateFeatureData){var data=(AngleMateFeatureData)definition;settings=new {angle=data.Angle,limits=data.IsAdvancedMate,minimum=data.MinimumAngle,maximum=data.MaximumAngle};}
    mates.Add(new {name=f.Name,type=((swMateType_e)mate.Type).ToString(),alignment=mate.Alignment,suppressed=f.IsSuppressed(),error,warning,settings,entities});
   }
  }
  var unchanged=dirty==model.GetSaveFlag()&&stamp==model.GetUpdateStamp()&&configuration==model.ConfigurationManager.ActiveConfiguration.Name&&selected==((SelectionMgr)model.SelectionManager).GetSelectedObjectCount2(-1);
  File.WriteAllText(output,new JavaScriptSerializer{MaxJsonLength=int.MaxValue}.Serialize(new {document=model.GetPathName(),configuration,dirty_before=dirty,read_only_state_unchanged=unchanged,components=rows,mates}));
  Console.WriteLine("Recorded "+rows.Count+" components and "+mates.Count+" mates; unchanged="+unchanged);
  if(!unchanged)throw new Exception("Assembly changed while reading; repeat the scan before drawing conclusions");
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[SuspensionMateInspection]::Run($SolidWorksProcessId,$Destination,$ComponentPattern,$Fast.IsPresent)
