param([int]$SolidWorksProcessId=36872,[string]$OutputDirectory='artifacts/reconciliation',
 [Parameter(Mandatory=$true)][string]$StagingDirectory)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$prefix=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$refs=@('System.Core','System.Web.Extensions','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[3..4]){[void][Reflection.Assembly]::LoadFrom($ref)}
$test=@'
public static class ReconciledCompanionTest {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static object Resolve(ModelDoc2 model,string r){int error;var o=model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(r),out error);if(error!=0||o==null)throw new Exception("Reference unavailable: "+error);return o;}
 public static void Run(int pid,string dll,string staging){
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var code=Assembly.LoadFrom(dll);var owner=code.GetType("BeamNG.Cad.Preparation.AssociationAssembly");var groupType=owner.GetNestedType("Receipt",BindingFlags.NonPublic);
  var read=code.GetType("BeamNG.Cad.Preparation.JsonFile").GetMethod("Read").MakeGenericMethod(groupType);
  var json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};var manifest=(object[])json.DeserializeObject(File.ReadAllText(Path.Combine(staging,"manifest.json")));
  var last=(Dictionary<string,object>)manifest.Last();var receipt=read.Invoke(null,new[]{last["staged"]});
  var model=app.GetOpenDocumentByName((string)Get(receipt,"Assembly")) as ModelDoc2;if(model==null)throw new Exception("Working companion must already be open");
  var active=app.ActiveDoc as ModelDoc2;var dirty=model.GetSaveFlag();var selected=((SelectionMgr)model.SelectionManager).GetSelectedObjectCount2(-1);
  var projectPath=(string)Get(receipt,"Project");var projectBefore=File.ReadAllBytes(projectPath);var nativeBefore=File.GetLastWriteTimeUtc(model.GetPathName());
  var instanceCount=((object[])((AssemblyDoc)model).GetComponents(true)).Length;
  var owns=new List<ModelDoc2>();int bodies=0,parts=0,faces=0;var documents=new Dictionary<string,ModelDoc2>(StringComparer.OrdinalIgnoreCase);
  var faceKey=owner.GetMethod("FaceKey",BindingFlags.NonPublic|BindingFlags.Static);var report=new List<object>();
  try {
   foreach(var raw in manifest.Take(manifest.Length-1)){
    var item=(Dictionary<string,object>)raw;var provenance=read.Invoke(null,new[]{item["staged"]});var group=((IEnumerable)Get(provenance,"Groups")).Cast<object>().Single();
    var path=(string)Get(group,"SourceDocument");ModelDoc2 source;
    if(!documents.TryGetValue(path,out source)){source=app.GetOpenDocumentByName(path) as ModelDoc2;if(source==null){int e=0,w=0;source=app.OpenDoc6(path,2,3,(string)Get(group,"SourceConfiguration"),ref e,ref w) as ModelDoc2;if(source==null)throw new Exception("Cannot read reviewed source: "+e);owns.Add(source);}documents.Add(path,source);}
    if(source.ConfigurationManager.ActiveConfiguration.Name!=(string)Get(group,"SourceConfiguration"))throw new Exception("Reviewed source configuration mismatch");
    var target=(Component2)Resolve(model,(string)Get(group,"ComponentReference"));if(!string.Equals(target.GetPathName(),(string)Get(group,"Part"),StringComparison.OrdinalIgnoreCase))throw new Exception("Target part mismatch");object info;
    var targetBodies=((object[])target.GetBodies3(-1,out info)).Cast<Body2>().ToDictionary(b=>b.Name);
    var keys=((IEnumerable)Get(group,"SourceBodies")).Cast<string>().ToArray();var names=((IEnumerable)Get(group,"CopiedBodies")).Cast<string>().ToArray();
    if(keys.Length!=names.Length||names.Any(n=>!targetBodies.ContainsKey(n)))throw new Exception("Incomplete body mapping");
    for(int i=0;i<keys.Length;i++){
     var k=keys[i].Split('|');var sourceInstance=(Component2)Resolve(source,k[0]);var sourceBody=(Body2)Resolve(source,k[1]);
     var sourceFaces=((object[])sourceBody.GetFaces()).Cast<Face2>().Select(f=>(string)faceKey.Invoke(null,new object[]{f})).OrderBy(s=>s).ToArray();
     var targetFaces=((object[])targetBodies[names[i]].GetFaces()).Cast<Face2>().Select(f=>(string)faceKey.Invoke(null,new object[]{f})).OrderBy(s=>s).ToArray();
     if(!sourceFaces.SequenceEqual(targetFaces))throw new Exception("Native-coordinate face mapping differs: "+Get(group,"Name")+" / "+names[i]);
     faces+=targetFaces.Length;bodies++;
    }
    parts++;report.Add(new{name=Get(group,"Name"),bodies=keys.Length});Console.WriteLine("PASS "+Get(group,"Name")+": "+keys.Length+" exact native body/face mappings");
   }
  }finally {foreach(var d in owns)app.CloseDoc(d.GetTitle());if(active!=null&&app.IsSame(app.ActiveDoc,active)!=(int)swObjectEquality.swObjectSame){int e=0;app.ActivateDoc3(active.GetTitle(),false,0,ref e);}}
  if(model.GetSaveFlag()!=dirty||((SelectionMgr)model.SelectionManager).GetSelectedObjectCount2(-1)!=selected||File.GetLastWriteTimeUtc(model.GetPathName())!=nativeBefore||!projectBefore.SequenceEqual(File.ReadAllBytes(projectPath)))throw new Exception("Read-only audit changed working state");
  File.WriteAllText(Path.Combine(staging,"native-audit.json"),json.Serialize(new{status="passed",parts=parts,bodies=bodies,faces=faces,instances=instanceCount,working_state_unchanged=true,groups=report}));Console.WriteLine("PASS native audit: "+parts+" parts, "+bodies+" bodies, "+faces+" faces; working state unchanged");
 }
}
'@
Add-Type -ReferencedAssemblies $refs -TypeDefinition ($prefix+"`r`n"+$test)
[ReconciledCompanionTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($StagingDirectory))
