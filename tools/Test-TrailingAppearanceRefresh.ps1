param([int]$SolidWorksProcessId,[string]$OutputDirectory,[string]$SourcePart,[string]$Destination,[string]$AbandonedFixture)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
if(Test-Path -LiteralPath $Destination){throw 'Use a new evidence directory'}
[void][IO.Directory]::CreateDirectory($Destination)
$copy=Join-Path ([IO.Path]::GetFullPath($Destination)) 'TrailingAppearanceFixture.SLDPRT'
Copy-Item -LiteralPath $SourcePart -Destination $copy
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class TrailingAppearanceRefreshTest {
 public static void CloseFixture(int pid,string path){
  if(string.IsNullOrEmpty(path))return;
  path=Path.GetFullPath(path);if(Path.GetFileName(path)!="TrailingAppearanceFixture.SLDPRT")throw new Exception("Only the disposable fixture may be closed");
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var part=app.GetOpenDocumentByName(path) as ModelDoc2;if(part!=null)app.CloseDoc(part.GetTitle());
 }
 static object New(Type type,params object[] args){return Activator.CreateInstance(type,BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance,null,args,null);}
 static void Set(object o,string name,object value){o.GetType().GetField(name).SetValue(o,value);}
 public static void Run(int pid,string dll,string path){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var original=(ModelDoc2)app.ActiveDoc;var dirty=original.GetSaveFlag();var code=Assembly.LoadFrom(dll);int error=0,warning=0;ModelDoc2 part=null;
  try {
   part=(ModelDoc2)app.OpenDoc6(path,1,1,"",ref error,ref warning);if(part==null)throw new Exception("Open fixture failed: "+error);
   var serviceType=code.GetType("BeamNG.Cad.Preparation.AssociationAssembly");var service=New(serviceType,app,original);
   var paintType=serviceType.GetNestedType("FacePaint",BindingFlags.NonPublic);var changeType=serviceType.GetNestedType("PaintChange",BindingFlags.NonPublic);
   var visual=code.GetType("BeamNG.Cad.Preparation.SolidWorksAppearances").GetMethod("Legacy",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{new[]{64.0/255,64.0/255,64.0/255,1,1,.5,.3125,0,0},"component"});
   var faces=((object[])((PartDoc)part).GetBodies2(-1,false)).Cast<Body2>().SelectMany(b=>((object[])b.GetFaces()).Cast<Face2>()).ToArray();
   var references=faces.Select(f=>Convert.ToBase64String((byte[])part.Extension.GetPersistReference3(f))).ToArray();
   var changes=Array.CreateInstance(changeType,faces.Length);
   for(int i=0;i<faces.Length;i++){var paint=New(paintType);Set(paint,"Visual",visual);var change=New(changeType);Set(change,"Part",part);Set(change,"Face",faces[i]);Set(change,"After",paint);changes.SetValue(change,i);}
   Console.WriteLine("Refreshing "+faces.Length+" fixture faces through production Paint");
   var timer=System.Diagnostics.Stopwatch.StartNew();serviceType.GetMethod("Paint",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(service,new object[]{part,changes,false,Path.GetDirectoryName(path),new List<string>()});Console.WriteLine("Paint finished in "+timer.Elapsed.TotalSeconds+" seconds");
   if(!part.Save3(1,ref error,ref warning)||error!=0)throw new Exception("Save fixture failed: "+error);
   app.ActivateDoc3(original.GetTitle(),false,0,ref error);app.CloseDoc(part.GetTitle());part=null;
   part=(ModelDoc2)app.OpenDoc6(path,1,3,"",ref error,ref warning);if(part==null)throw new Exception("Reopen fixture failed");
   int count=0;foreach(var reference in references){int state;var face=part.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out state) as Face2;if(face==null||state!=0)throw new Exception("Face identity changed");var color=face.GetMaterialPropertyValues2(1,null) as double[];if(color==null||color.Take(3).Any(c=>Math.Abs(c-64.0/255)>1e-9))throw new Exception("Refreshed colour did not survive reopen");count++;}
   // SolidWorks may synthesize native face render entries from the legacy
   // setters on save. Their presence is valid; their effective colour must match.
   var renders=part.Extension.GetRenderMaterials2(1,null) as object[]??new object[0];if(renders.Cast<RenderMaterial>().Any(r=>r.PrimaryColor!=0x404040&&(r.GetEntities() as object[]??new object[0]).Any(e=>e is Face2)))throw new Exception("Conflicting face render overrides remain");
   File.WriteAllText(Path.Combine(Path.GetDirectoryName(path),"result.json"),new JavaScriptSerializer().Serialize(new {passed=true,faces=count,face_identity_preserved=true,colour_survives_reopen=true,scope="Production paint on a disposable part copy; not full source-provenance refresh"}));
   Console.WriteLine("PASS "+count+" face identities and dark-grey colours survive save/reopen; stale render overrides removed");
  }finally {app.ActivateDoc3(original.GetTitle(),false,0,ref error);if(part!=null)app.CloseDoc(part.GetTitle());if(original.GetSaveFlag()!=dirty)throw new Exception("Original dirty state changed");}
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[TrailingAppearanceRefreshTest]::CloseFixture($SolidWorksProcessId,$AbandonedFixture)
[TrailingAppearanceRefreshTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),$copy)
