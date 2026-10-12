param(
    [string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\material-rebuild-final'),
    [Parameter(Mandatory=$true)][string]$FrameSource,
    [switch]$FrameOnly
)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$FrameSource=(Resolve-Path -LiteralPath $FrameSource).Path
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
$root=Join-Path $OutputDirectory ('native-material-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
function Get-SourceHash {
    $stream=[IO.File]::Open($FrameSource,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    $sha=[Security.Cryptography.SHA256]::Create()
    try {[BitConverter]::ToString($sha.ComputeHash($stream))} finally {$sha.Dispose();$stream.Dispose()}
}
$beforeHash=Get-SourceHash
if(Test-Path (Join-Path $OutputDirectory 'BulkMaterialsSmoke.dll')){Remove-Item -LiteralPath (Join-Path $OutputDirectory 'BulkMaterialsSmoke.dll')}
& powershell -NoProfile -STA -File (Join-Path $PSScriptRoot 'Test-BulkMaterials.ps1') -OutputDirectory $OutputDirectory -CompileOnly
if($LASTEXITCODE -ne 0){throw 'Could not compile native material tests.'}
$hostDll=Join-Path $OutputDirectory 'MaterialNativeHost.dll'
$job=Join-Path $OutputDirectory 'material-native-job.txt'
[IO.File]::WriteAllLines($job,@($root,$FrameSource,$FrameOnly.IsPresent.ToString()))
$refs=@('System.Core','System.Windows.Forms','System.Drawing',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swpublished.dll'),(Join-Path $OutputDirectory 'BulkMaterialsSmoke.dll'))
$source=@'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
// External STA client of an explicitly owned native SolidWorks instance.
public sealed class MaterialNativeHost {
 [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window,int command);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static object Field(object o,string name){return o.GetType().GetField(name).GetValue(o);}
 static object Call(object o,string name,params object[] args){return o.GetType().GetMethod(name).Invoke(o,args);}
 static void Frame(ISldWorks app,string dll,string folder,string source){
  var copied=Path.Combine(folder,"material-frame-copy.SLDPRT");
  using(var input=File.Open(source,FileMode.Open,FileAccess.Read,FileShare.ReadWrite))
  using(var output=File.Create(copied))input.CopyTo(output);
  int e=0,w=0;
  var part=(ModelDoc2)app.OpenDoc6(copied,1,1,"Default<As Machined>",ref e,ref w);
  Check(part!=null,"disposable frame copy opened");
  ModelDoc2 assembly=null;
  try {
   assembly=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
   var component=((AssemblyDoc)assembly).AddComponent5(copied,0,"",false,"",0,0,0);
   Check(component!=null,"disposable frame inserted");
   Check(assembly.Extension.SaveAs(Path.Combine(folder,"material-frame-copy.SLDASM"),0,1,null,ref e,ref w),"disposable frame assembly saved");
   Check(component.Select4(false,null,false),"disposable frame selected");
   var code=Assembly.LoadFrom(dll);
   var selection=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.FrameSelection"),app,assembly);
   var service=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.BulkMaterialAssignment"),app,assembly,Call(selection,"MaterialBodies",new object[]{null}));
   using((IDisposable)service){
    Check((int)service.GetType().GetProperty("Count").GetValue(service,null)==60,"real frame contains 60 unique material targets");
    var choice=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.NativeMaterialChoice"),true);
    choice.GetType().GetField("Name").SetValue(choice,"AISI 4130 Steel, annealed at 865C");
    var database=((IEnumerable)app.GetMaterialDatabases()).Cast<string>().Single(p=>Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
    choice.GetType().GetField("Database").SetValue(choice,database);
    var sta=Thread.CurrentThread.ManagedThreadId;
    Action<int,int,string> progress=(done,total,label)=>{Check(sta==Thread.CurrentThread.ManagedThreadId,"frame assignment on native STA");Console.WriteLine("FRAME "+done+"/"+total+" "+label);};
    service.GetType().GetProperty("Status").SetValue(service,new Action<string>(s=>Console.WriteLine(s)),null);
    var task=(Task)Call(service,"ApplyAsync",choice,progress,CancellationToken.None);
    while(!task.IsCompleted){Application.DoEvents();Thread.Sleep(5);}
    task.GetAwaiter().GetResult();
    var result=task.GetType().GetProperty("Result").GetValue(task,null);
    foreach(var detail in (IEnumerable)Field(result,"Diagnostics"))Console.WriteLine(detail);
    Check(Field(result,"Error")==null,"real frame assignment succeeded: "+Field(result,"Error"));
    Check(((IList)Field(result,"Applied")).Count==60 && ((IList)Field(result,"Remaining")).Count==0,"all 60 frame bodies verified");
    Check((int)Field(result,"RebuildCount")<=1,"real frame rebuild count at most one");
    var snapshot=Call(selection,"ReadMaterials",Call(selection,"Capture"));
    Check(((IEnumerable)Field(snapshot,"Bodies")).Cast<object>().All(b=>Field(b,"Error")==null && (string)Field(b,"Name")=="AISI 4130 Steel, annealed at 865C"),"exporter independently reads all real frame material assignments");
   }
  } finally {
   // Closing the assembly can unload its last referenced part as well.
   // Use known fixture names rather than dereferencing an unloaded COM object.
   if(assembly!=null)app.CloseDoc(assembly.GetTitle());
   app.CloseDoc(Path.GetFileName(copied));
  }
 }
 public void Run(ISldWorks app){
  var directory=Path.GetDirectoryName(GetType().Assembly.Location);
  var job=File.ReadAllLines(Path.Combine(directory,"material-native-job.txt"));
  using(var writer=new StreamWriter(Path.Combine(job[0],"native-tests.log"))){
   writer.AutoFlush=true;var old=Console.Out;Console.SetOut(writer);
   try {
    app.UserControl=true;app.Visible=true;
    var frame=new IntPtr(((Frame)app.Frame()).GetHWndx64());ShowWindow(frame,5);
    Check(IsWindowVisible(frame),"isolated native frame is visible before UI tests");
    SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
    Console.WriteLine("Native SolidWorks PID="+app.GetProcessID()+", STA="+Thread.CurrentThread.GetApartmentState());
    var dll=Path.Combine(directory,"beamng.cad.dll");
    if(job.Length<3 || !bool.Parse(job[2]))BulkMaterialsSmoke.Run(dll,job[0],new int[0],true,false,app,true);
    Frame(app,dll,job[0],job[1]);
    File.WriteAllText(Path.Combine(job[0],"result.txt"),"PASS");
   } catch(Exception ex){Console.WriteLine(ex);File.WriteAllText(Path.Combine(job[0],"result.txt"),ex.ToString());}
   finally {Console.SetOut(old);}
  }
 }
}
'@
if(Test-Path -LiteralPath $hostDll){Remove-Item -LiteralPath $hostDll}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $source -OutputAssembly $hostDll
$ownedPid=$null
try {
    # Launch explicitly and bind the exact PID moniker. CoCreateInstance can
    # return an existing instance and block on the user's busy UI thread.
    foreach($name in @('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll')){[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory $name))}
    Add-Type -ReferencedAssemblies $refs[3] -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using SolidWorks.Interop.sldworks;
public static class IsolatedMaterialApp {
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out IBindCtx context);
 public static ISldWorks Find(int pid){
  IRunningObjectTable table;IBindCtx context;GetRunningObjectTable(0,out table);CreateBindCtx(0,out context);
  IEnumMoniker list;table.EnumRunning(out list);var item=new IMoniker[1];
  try {while(list.Next(1,item,IntPtr.Zero)==0){
   try {string name;item[0].GetDisplayName(context,null,out name);if(name=="SolidWorks_PID_"+pid){object value;table.GetObject(item[0],out value);return (ISldWorks)value;}}
   finally {Marshal.ReleaseComObject(item[0]);}
  }return null;} finally {Marshal.ReleaseComObject(list);Marshal.ReleaseComObject(context);Marshal.ReleaseComObject(table);}
 }
 public static void Finish(object value,string dll){((ISldWorks)value).ExitApp();}
}
'@
    $exe=Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS\sldworks.exe'
    $process=Start-Process -FilePath $exe -ArgumentList '/r' -WindowStyle Hidden -PassThru
    $ownedPid=$process.Id
    if($existing -contains $ownedPid){throw 'Refusing to use an existing user instance.'}
    $startup=(Get-Date).AddSeconds(120)
    do {$app=[IsolatedMaterialApp]::Find($ownedPid);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and (Get-Date) -lt $startup)
    if(-not $app){throw 'Isolated SolidWorks instance did not register in the ROT.'}
    Write-Output "TEST_PROCESS=$ownedPid EVIDENCE=$root"
    $hostType=[Reflection.Assembly]::LoadFrom($hostDll).GetType('MaterialNativeHost')
    [void]$hostType.GetMethod('Run').Invoke([Activator]::CreateInstance($hostType),@($app))
    Get-Content (Join-Path $root 'native-tests.log')
    if((Get-Content (Join-Path $root 'result.txt') -Raw) -ne 'PASS'){throw 'Native material tests failed.'}
} finally {
    if($ownedPid){
        # Exit normally only once the host has returned. A stuck native test may
        # be stopped, but ownership is restricted to our newly created PID.
        if(Test-Path (Join-Path $root 'result.txt')){[IsolatedMaterialApp]::Finish($app,$hostDll)}
        else {Stop-Process -Id $ownedPid -ErrorAction SilentlyContinue}
    }
    if((Get-SourceHash) -ne $beforeHash){throw 'Original frame file changed during test.'}
}
