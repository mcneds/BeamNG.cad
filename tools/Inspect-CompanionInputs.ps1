param([int]$SolidWorksProcessId,[string]$ProjectPath,[string]$OutputDirectory,[string]$Destination,[string]$DebugGate)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class CompanionInputInspection {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static object New(Assembly code,string name,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation."+name),BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance,null,args,null);}
 static object Call(object o,string name,params object[] args){return o.GetType().GetMethod(name).Invoke(o,args);}
 static object[] Renders(object value){return (value as object[]??new object[0]).Cast<RenderMaterial>().Select(r=>(object)new {file=r.FileName,primary=r.PrimaryColor,texture=r.TextureFilename,entities=(r.GetEntities() as object[]??new object[0]).Select(x=>x is Component2?"component:"+((Component2)x).Name2:x is ModelDoc2?"document":x is Body2?"body":x is Face2?"face":x is Feature?"feature":"other").ToArray()}).ToArray();}
 public static void Run(int pid,string dll,string projectPath,string output){
  var code=Assembly.LoadFrom(dll);var json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};
  var project=code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Load").Invoke(null,new object[]{projectPath});
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var original=app.ActiveDoc as ModelDoc2;var source=(ModelDoc2)app.GetOpenDocumentByName((string)Get(project,"SourceDocument"));
  if(source==null)throw new Exception("Source assembly must be open for this read-only probe");
  int error=0;app.ActivateDoc3(source.GetTitle(),false,0,ref error);
  var dirty=source.GetSaveFlag();var groups=((IEnumerable)Get(project,"Components")).Cast<object>().ToArray();var rows=new List<object>();
  try {using(var preserved=(IDisposable)New(code,"SelectionSnapshot",source)){
   var selection=New(code,"FrameSelection",app,source,true);
   var assemblyRenders=Renders(source.Extension.GetRenderMaterials2(1,null));
   foreach(var name in new[]{"Engine Mount","Frame","L Seat Panel","Nose Panel"}){
    var group=groups.Single(c=>(string)Get(c,"Name")==name);
    var assignment=code.GetType("BeamNG.Cad.Preparation.AssignmentInspection").GetMethod("Capture").Invoke(null,new object[]{group,false});
    if(name=="Engine Mount"){
     try {Call(selection,"Show",assignment);Console.WriteLine("Engine Mount highlight selected="+((SelectionMgr)source.SelectionManager).GetSelectedObjectCount2(-1));}
     catch(Exception ex){Console.WriteLine("Engine Mount highlight error: "+ex);}
    }
    var bodies=((IEnumerable)Call(selection,"SnapshotBodies",assignment)).Cast<Tuple<Component2,Body2>>().ToArray();
    foreach(var pair in bodies.Take(name=="Engine Mount"?7:1)){
     var part=(ModelDoc2)pair.Item1.GetModelDoc2();var face=((object[])pair.Item2.GetFaces()).Cast<Face2>().First();
     var reader=New(code,"SolidWorksAppearances",app,pair.Item1,pair.Item2);var appearance=Call(reader,"Read",face);
     var ancestors=new List<object>();for(var parent=pair.Item1.GetParent();parent!=null;parent=parent.GetParent())ancestors.Add(new {name=parent.Name2,legacy=parent.GetMaterialPropertyValues2(1,null),renders=Renders(parent.GetRenderMaterials2(1,null))});
     rows.Add(new {group=name,component=pair.Item1.Name2,body=pair.Item2.Name,body_box=pair.Item2.GetBodyBox(),component_transform=(pair.Item1.Transform2==null?null:pair.Item1.Transform2.ArrayData),body_visible=pair.Item2.Visible,
      component_hidden=pair.Item1.IsHidden(false),body_temporary=pair.Item2.IsTemporaryBody(),appearance,component_has_appearance=pair.Item1.HasMaterialPropertyValues(),component_legacy=pair.Item1.GetMaterialPropertyValues2(1,null),part_legacy=part.MaterialPropertyValues,
      component_renders=Renders(pair.Item1.GetRenderMaterials2(1,null)),part_renders=Renders(part.Extension.GetRenderMaterials2(1,null)),assembly_renders=assemblyRenders,ancestors});
     Console.WriteLine(name+" / "+pair.Item2.Name+": "+json.Serialize(appearance));
    }
   }
  }}finally {if(original!=null)app.ActivateDoc3(original.GetTitle(),false,0,ref error);}
  if(source.GetSaveFlag()!=dirty)throw new Exception("Unexpected dirty-state change");
  File.WriteAllText(Path.Combine(output,"inputs.json"),json.Serialize(rows));
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
if($DebugGate){
 [void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
 [IO.File]::WriteAllText($DebugGate+'.pid',[string]$PID)
 $until=[DateTime]::UtcNow.AddMinutes(10)
 while(-not (Test-Path -LiteralPath $DebugGate)){if([DateTime]::UtcNow -gt $until){throw 'Debug gate timed out'};Start-Sleep -Milliseconds 100}
}
[CompanionInputInspection]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),$ProjectPath,[IO.Path]::GetFullPath($Destination))
