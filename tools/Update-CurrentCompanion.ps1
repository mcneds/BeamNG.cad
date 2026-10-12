param([Parameter(Mandatory=$true)][string]$OutputDirectory,
      [Parameter(Mandatory=$true)][string]$ReceiptPath,
      [Parameter(Mandatory=$true)][string]$Destination,
      [switch]$RefreshGeometry)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$ReceiptPath=(Resolve-Path -LiteralPath $ReceiptPath).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new evidence folder'}
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[5..6]){[void][Reflection.Assembly]::LoadFrom($ref)}
$helper=Get-Content -Raw (Join-Path $PSScriptRoot 'New-SyntheticVehicle.ps1')
$start=$helper.IndexOf('using System;');$end=$helper.IndexOf("'@",$start)
$code=$helper.Substring($start,$end-$start)+@'

public static class CurrentCompanionUpdate {
 static object appearanceScene;
 sealed class Context : System.Threading.SynchronizationContext {
  readonly System.Collections.Concurrent.ConcurrentQueue<Action> queue=new System.Collections.Concurrent.ConcurrentQueue<Action>();
  public override void Post(System.Threading.SendOrPostCallback callback,object state){queue.Enqueue(()=>callback(state));}
  public void Drain(){Action call;while(queue.TryDequeue(out call)){System.Threading.SynchronizationContext.SetSynchronizationContext(this);call();}}
 }
 static object Get(object o,string name){return o.GetType().GetField(name).GetValue(o);}
 static object Call(object o,string name,params object[] args){return o.GetType().GetMethod(name).Invoke(o,args);}
 static object New(Assembly code,string name,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation."+name),BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance,null,args,null);}
 static string Hash(string path){using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite))using(var sha=System.Security.Cryptography.SHA256.Create())return Convert.ToBase64String(sha.ComputeHash(stream));}
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static object[] Groups(object project){return ((IEnumerable)Get(project,"Components")).Cast<object>().ToArray();}
 static Tuple<Component2,Body2>[] Bodies(Assembly code,object selector,object group){
  var assignment=code.GetType("BeamNG.Cad.Preparation.AssignmentInspection").GetMethod("Capture").Invoke(null,new[]{group,(object)false});
  return ((IEnumerable)Call(selector,"SnapshotBodies",assignment)).Cast<Tuple<Component2,Body2>>().ToArray();
 }
 static string Appearance(Assembly code,ISldWorks app,Tuple<Component2,Body2> pair){
  var reader=New(code,"SolidWorksAppearances",app,pair.Item1,pair.Item2,appearanceScene);
  var appearance=Call(reader,"Read",((object[])pair.Item2.GetFaces()).Cast<Face2>().First());
  var texture=(string)Get(appearance,"TextureFile");
  return string.Join(",",((double[])Get(appearance,"BaseColor")).Select(v=>Math.Round(v,6).ToString(System.Globalization.CultureInfo.InvariantCulture)))+"|"+(string.IsNullOrEmpty(texture)?"":Hash(texture));
 }
 public static void Run(object application,string dll,string receiptPath,string folder,bool refreshGeometry){
  var app=(ISldWorks)application;app.CommandInProgress=true;var code=Assembly.LoadFrom(dll);var links=code.GetType("BeamNG.Cad.Preparation.CompanionAssemblyLink");
  var receipt=links.GetMethod("Read").Invoke(null,new object[]{receiptPath});var projectPath=(string)Get(receipt,"SourceProject");
  var project=code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Load").Invoke(null,new object[]{projectPath});
  var preserved=new[]{projectPath,(string)Get(project,"SourceDocument"),(string)Get(receipt,"Assembly"),(string)Get(receipt,"Project")}
   .Concat(((IEnumerable)Get(receipt,"Groups")).Cast<object>().Select(g=>(string)Get(g,"Part"))).Distinct().ToDictionary(p=>p,Hash);
  File.Copy(receiptPath,Path.Combine(folder,"previous-working-assembly.json"));
  int error=0,warning=0;
  var source=(ModelDoc2)app.OpenDoc6((string)Get(project,"SourceDocument"),2,3,"",ref error,ref warning);
  if(source==null)throw new Exception("Could not open source read-only: "+error);
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);
  appearanceScene=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.SolidWorksAppearances+Scene"),new object[]{source});
  var selector=New(code,"FrameSelection",app,source,true);var expected=new Dictionary<string,int>();var finishes=new Dictionary<string,string[]>();
  foreach(var group in Groups(project)){
   if(((IList)Get(group,"Selections")).Count==0)continue;
   var bodies=Bodies(code,selector,group);var id=(string)Get(group,"Id");var name=(string)Get(group,"Name");expected[id]=bodies.Length;
   if(new[]{"Engine Mount","Frame","Nose Panel","L Seat Panel"}.Contains(name))finishes[id]=bodies.Select(b=>Appearance(code,app,b)).OrderBy(v=>v).ToArray();
   Console.WriteLine("Resolved "+name+": "+bodies.Length+" bodies");
  }
  var dirty=source.GetSaveFlag();var context=new Context();System.Threading.SynchronizationContext.SetSynchronizationContext(context);
  var task=(System.Threading.Tasks.Task)Call(New(code,"AssociationAssembly",app,source),"Update",project,receiptPath,refreshGeometry,
   new Action<int,string>((p,s)=>Console.WriteLine(p+"% "+s)),System.Threading.CancellationToken.None);
  while(!task.IsCompleted){context.Drain();System.Windows.Forms.Application.DoEvents();System.Threading.Thread.Sleep(15);}task.GetAwaiter().GetResult();
  var result=task.GetType().GetProperty("Result").GetValue(task,null);var output=(ModelDoc2)Get(result,"Document");var copy=Get(result,"Project");
  var outputPath=output.GetPathName();app.CloseDoc(output.GetTitle());output=(ModelDoc2)app.OpenDoc6(outputPath,2,1,"",ref error,ref warning);
  if(output==null)throw new Exception("Reopen failed: "+error);app.ActivateDoc3(output.GetTitle(),false,0,ref error);
  appearanceScene=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.SolidWorksAppearances+Scene"),new object[]{output});
  selector=New(code,"FrameSelection",app,output,true);
  Check(Groups(project).All(g=>Groups(copy).Any(c=>(string)Get(c,"Id")== (string)Get(g,"Id"))),"every source group carried into companion");
  foreach(var group in Groups(copy)){
   var id=(string)Get(group,"Id");var name=(string)Get(group,"Name");if(!expected.ContainsKey(id))continue;
   var bodies=Bodies(code,selector,group);Check(bodies.Length==expected[id],name+": all "+bodies.Length+" bodies resolve after reopen");
   if(finishes.ContainsKey(id))Check(bodies.Select(b=>Appearance(code,app,b)).OrderBy(v=>v).SequenceEqual(finishes[id]),name+": every body's sampled colour/texture matches source");
   if(name=="Engine Mount"){
    var assignment=code.GetType("BeamNG.Cad.Preparation.AssignmentInspection").GetMethod("Capture").Invoke(null,new[]{group,(object)false});
    Call(selector,"Show",assignment);Check(((SelectionMgr)output.SelectionManager).GetSelectedObjectCount2(-1)==expected[id],"Engine Mount highlights in updated companion");
   }
  }
  foreach(var item in preserved)Check(Hash(item.Key)==item.Value,"preserved "+item.Key);
  Check(source.GetSaveFlag()==dirty,"refresh leaves source dirty state unchanged after resolution");
  output.ClearSelection2(true);output.ShowNamedView2("*Isometric",7);output.ViewZoomtofit2();output.GraphicsRedraw2();System.Windows.Forms.Application.DoEvents();
  var bitmap=Path.Combine(folder,"companion.bmp");if(output.SaveBMP(bitmap,0,0)){using(var image=new System.Drawing.Bitmap(bitmap))image.Save(Path.Combine(folder,"companion.png"),System.Drawing.Imaging.ImageFormat.Png);File.Delete(bitmap);}
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS "+(refreshGeometry?"full geometry refresh":"incremental companion update")+" and reopen\n"+outputPath);
  Console.WriteLine("UPDATED_COMPANION="+outputPath);
 }
}
'@
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
$owned=$null
try {
 $owned=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp/SOLIDWORKS/sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
 if($existing -contains $owned.Id){$owned=$null;throw 'Refusing an existing process'}
 $until=[DateTime]::UtcNow.AddMinutes(2);$app=$null
 do {$app=[SyntheticNativeCad]::Find($owned.Id);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and [DateTime]::UtcNow -lt $until)
 if(-not $app){throw 'Owned SolidWorks did not register'}
 Write-Output ('OWNED_CAD_PROCESS='+$owned.Id)
 [SyntheticNativeCad]::GuardOwnedPrompt($owned.Id)
 [CurrentCompanionUpdate]::Run($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$ReceiptPath,$Destination,[bool]$RefreshGeometry)
}finally{if($owned){try{$app.ExitApp()}catch{};if(-not $owned.WaitForExit(10000)){Stop-Process -Id $owned.Id -Force -ErrorAction SilentlyContinue}}}
