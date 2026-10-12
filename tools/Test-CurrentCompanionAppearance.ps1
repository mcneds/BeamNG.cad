param([int]$SolidWorksProcessId,[string]$ProjectPath,[string]$OutputDirectory,[string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
if(Test-Path -LiteralPath $Destination){throw 'Choose a new owned evidence folder'}
[void][IO.Directory]::CreateDirectory($Destination)
$helper=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class CurrentCompanionAppearanceTest {
 sealed class Context : System.Threading.SynchronizationContext {
  readonly System.Collections.Concurrent.ConcurrentQueue<Action> queue=new System.Collections.Concurrent.ConcurrentQueue<Action>();
  public override void Post(System.Threading.SendOrPostCallback callback,object state){queue.Enqueue(()=>callback(state));}
  public void Drain(){Action call;while(queue.TryDequeue(out call)){System.Threading.SynchronizationContext.SetSynchronizationContext(this);call();}}
 }
 static object Get(object o,string name){return o.GetType().GetField(name).GetValue(o);}
 static void Put(object o,string name,object value){o.GetType().GetField(name).SetValue(o,value);}
 static object New(Assembly code,string name,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation."+name),BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance,null,args,null);}
 static object Call(object o,string name,params object[] args){return o.GetType().GetMethod(name).Invoke(o,args);}
 static object Assignment(Assembly code,object group){return code.GetType("BeamNG.Cad.Preparation.AssignmentInspection").GetMethod("Capture").Invoke(null,new object[]{group,false});}
 static Tuple<Component2,Body2>[] Bodies(object selector,object assignment){return ((IEnumerable)Call(selector,"SnapshotBodies",assignment)).Cast<Tuple<Component2,Body2>>().ToArray();}
 static string Hash(string path){using(var sha=System.Security.Cryptography.SHA256.Create())return Convert.ToBase64String(sha.ComputeHash(File.ReadAllBytes(path)));}
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 public static void Run(int pid,string dll,string projectPath,string folder){
  var code=Assembly.LoadFrom(dll);var type=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var sourceProject=type.GetMethod("Load").Invoke(null,new object[]{projectPath});
  var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});
  var original=app.ActiveDoc as ModelDoc2;var source=(ModelDoc2)app.GetOpenDocumentByName((string)Get(sourceProject,"SourceDocument"));
  if(source==null){int openError=0,openWarning=0;source=(ModelDoc2)app.OpenDoc6((string)Get(sourceProject,"SourceDocument"),2,3,"",ref openError,ref openWarning);if(source==null)throw new Exception("Could not open source read-only: "+openError);}
  var projectHash=Hash(projectPath);var cadHash=Hash(source.GetPathName());var dirty=source.GetSaveFlag();int error=0,warning=0;ModelDoc2 output=null;
  var previousContext=System.Threading.SynchronizationContext.Current;var context=new Context();System.Threading.SynchronizationContext.SetSynchronizationContext(context);
  var project=Call(sourceProject,"Fork",Path.Combine(folder,"sample-project.json"));var groups=(IList)Get(project,"Components");
  foreach(var group in groups.Cast<object>().Where(g=>!new[]{"Engine Mount","Frame","L Seat Panel","Nose Panel"}.Contains((string)Get(g,"Name"))).ToArray())groups.Remove(group);
  ((IList)Get(project,"Anchors")).Clear();((IList)Get(project,"Connections")).Clear();Put(project,"TemplateDefinitionPath","");
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);
  var expected=new Dictionary<string,Tuple<double[],string,int>>();
  try {using(var preserved=(IDisposable)New(code,"SelectionSnapshot",source)){
   var selector=New(code,"FrameSelection",app,source,true);
   foreach(var group in groups){
    var name=(string)Get(group,"Name");var assignment=Assignment(code,group);var bodies=Bodies(selector,assignment);var pair=bodies[0];
    if(name!="Engine Mount"){
     var refs=(IList)Get(group,"Selections");refs.Clear();var reference=New(code,"SelectionReference");Put(reference,"Kind","body");Put(reference,"Name",pair.Item2.Name);
     Put(reference,"Reference",Convert.ToBase64String((byte[])source.Extension.GetPersistReference3(pair.Item2)));Put(reference,"ComponentReference",Convert.ToBase64String((byte[])source.Extension.GetPersistReference3(pair.Item1)));refs.Add(reference);
     Put(group,"BodyIds",Call(selector,"BodyIds",Assignment(code,group)));
    } else {Call(selector,"Show",assignment);Check(((SelectionMgr)source.SelectionManager).GetSelectedObjectCount2(-1)==7,"all seven real engine-mount bodies highlight");}
    var reader=New(code,"SolidWorksAppearances",app,pair.Item1,pair.Item2);var face=((object[])pair.Item2.GetFaces()).Cast<Face2>().First();var appearance=Call(reader,"Read",face);var texture=(string)Get(appearance,"TextureFile");
    expected[name]=Tuple.Create((double[])Get(appearance,"BaseColor"),string.IsNullOrEmpty(texture)?null:Hash(texture),name=="Engine Mount"?7:1);
   }
   Call(project,"Save");
   Console.WriteLine("Source resolution dirty state: before="+dirty+" after="+source.GetSaveFlag());
   dirty=source.GetSaveFlag();
   var service=New(code,"AssociationAssembly",app,source);var task=(System.Threading.Tasks.Task)Call(service,"Create",project,Path.Combine(folder,"working"),new Action<int,string>((p,s)=>Console.WriteLine(p+"% "+s)),System.Threading.CancellationToken.None);
   while(!task.IsCompleted){context.Drain();System.Windows.Forms.Application.DoEvents();System.Threading.Thread.Sleep(15);}task.GetAwaiter().GetResult();
   var result=task.GetType().GetProperty("Result").GetValue(task,null);output=(ModelDoc2)Get(result,"Document");var copied=Get(result,"Project");
   var outputPath=output.GetPathName();app.CloseDoc(output.GetTitle());output=(ModelDoc2)app.OpenDoc6(outputPath,2,1,"",ref error,ref warning);app.ActivateDoc3(output.GetTitle(),false,0,ref error);
   selector=New(code,"FrameSelection",app,output,true);
   foreach(var group in (IList)Get(copied,"Components")){
    var name=(string)Get(group,"Name");var bodies=Bodies(selector,Assignment(code,group));Check(bodies.Length==expected[name].Item3,name+" body count survives copying and reopen");
    var pair=bodies[0];var reader=New(code,"SolidWorksAppearances",app,pair.Item1,pair.Item2);var face=((object[])pair.Item2.GetFaces()).Cast<Face2>().First();var actual=Call(reader,"Read",face);
    Check(((double[])Get(actual,"BaseColor")).Zip(expected[name].Item1,(a,b)=>Math.Abs(a-b)<1e-8).All(v=>v),name+" effective render colour matches source after reopen; actual="+string.Join(",",(double[])Get(actual,"BaseColor"))+" expected="+string.Join(",",expected[name].Item1));
    if(expected[name].Item2!=null){var texture=(string)Get(actual,"TextureFile");Check(!string.IsNullOrEmpty(texture)&&Hash(texture)==expected[name].Item2&&texture.StartsWith(folder,StringComparison.OrdinalIgnoreCase),name+" texture bytes are carried into the working folder");}
   }
   output.ClearSelection2(true);output.ShowNamedView2("*Isometric",7);output.ViewZoomtofit2();output.GraphicsRedraw2();System.Windows.Forms.Application.DoEvents();
   var bitmap=Path.Combine(folder,"working.bmp");if(output.SaveBMP(bitmap,0,0)){using(var image=new System.Drawing.Bitmap(bitmap))image.Save(Path.Combine(folder,"working.png"),System.Drawing.Imaging.ImageFormat.Png);File.Delete(bitmap);}
  }}finally {if(output!=null)app.CloseDoc(output.GetTitle());if(original!=null)app.ActivateDoc3(original.GetTitle(),false,0,ref error);System.Threading.SynchronizationContext.SetSynchronizationContext(previousContext);}
  Check(projectHash==Hash(projectPath),"source project bytes preserved");
  Check(cadHash==Hash(source.GetPathName()),"source CAD file bytes preserved");
  Check(source.GetSaveFlag()==dirty,"copy preserves source dirty state after component resolution");
 }
}
'@
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
$owned=$null
try {
 if(-not $SolidWorksProcessId){
  $existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
  $owned=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp/SOLIDWORKS/sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
  if($existing -contains $owned.Id){$owned=$null;throw 'Refusing an existing process'}
  $SolidWorksProcessId=$owned.Id
  $until=[DateTime]::UtcNow.AddMinutes(2);$app=$null
  do {try{$app=[CurrentAssignmentInspectionTest].GetMethod('Find',[Reflection.BindingFlags]'Static,NonPublic').Invoke($null,@([int]$SolidWorksProcessId))}catch{Start-Sleep -Milliseconds 500}}while(-not $app -and [DateTime]::UtcNow -lt $until)
  if(-not $app){throw 'Owned SolidWorks did not register'}
  Write-Output ('OWNED_CAD_PROCESS='+$owned.Id)
 }
 [CurrentCompanionAppearanceTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),$ProjectPath,[IO.Path]::GetFullPath($Destination))
} finally {
 if($owned){try{$app.ExitApp()}catch{};if(-not $owned.WaitForExit(10000)){Stop-Process -Id $owned.Id -Force -ErrorAction SilentlyContinue}}
}
