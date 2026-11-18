param([string]$OutputDirectory=(Join-Path $PSScriptRoot '../beamng.cad/bin/hull-search'),[string]$FrameStl='',[switch]$Gpu,[switch]$Check)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$wpf=Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'WPF'
$refs=@('System.Core','System.Drawing','System.Windows.Forms','System.Web.Extensions',
 (Join-Path $wpf 'WindowsBase.dll'),(Join-Path $wpf 'PresentationCore.dll'),
 (Join-Path $wpf 'PresentationFramework.dll'),(Join-Path $wpf 'WindowsFormsIntegration.dll'))
foreach($ref in $refs[4..7]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;using System.IO;using System.Linq;using System.Reflection;using System.Collections;using System.Collections.Generic;using System.Threading;using System.Threading.Tasks;using System.Diagnostics;using System.Windows.Forms;using System.Windows.Media.Media3D;
public static class HullSearchTests {
 const BindingFlags F=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static;
 static Assembly code;static Type meshType,searchType,optionsType,resultType;static List<Exception> errors=new List<Exception>();static object applied;static int applyCount;public static void Applied(object value){applied=value;applyCount++;}
 static object Get(object o,string n){return o.GetType().GetField(n,F).GetValue(o);}static void Set(object o,string n,object v){o.GetType().GetField(n,F).SetValue(o,v);}
 static object Call(object o,string n,params object[] a){try{return o.GetType().GetMethod(n,F).Invoke(o,a);}catch(TargetInvocationException e){throw e.InnerException;}}
 static object New(Type t,params object[] a){return Activator.CreateInstance(t,F,null,a,null);}
 static void Check(bool ok,string s){if(!ok)throw new Exception(s);Console.WriteLine("PASS: "+s);}
 static void Pump(int ms){var sw=Stopwatch.StartNew();while(sw.ElapsedMilliseconds<ms){Application.DoEvents();Thread.Sleep(2);}}
 static void Until(Func<bool> done,int timeout){var sw=Stopwatch.StartNew();while(!done()){Pump(5);if(sw.ElapsedMilliseconds>timeout)throw new Exception("Search UI timed out");}}
 static readonly Point3D[] cube={new Point3D(-.5,-.5,-.5),new Point3D(.5,-.5,-.5),new Point3D(.5,.5,-.5),new Point3D(-.5,.5,-.5),new Point3D(-.5,-.5,.5),new Point3D(.5,-.5,.5),new Point3D(.5,.5,.5),new Point3D(-.5,.5,.5)};
 static readonly int[] ids={0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,3,7,6,3,6,2,0,4,7,0,7,3,1,2,6,1,6,5};
 static object Mesh(Point3D[] p,int[] t){return New(meshType,p,t);}static string Validate(object m){return (string)Call(m,"ValidateShell",CancellationToken.None);}
 static object Options(){var o=New(optionsType);Set(o,"Orientation","XYZ");Set(o,"Offset",0.0);Set(o,"Weld",0.0);Set(o,"Width",3);Set(o,"Length",4);Set(o,"Height",5);return o;}
 static Point3D[] Soup(Point3D[] p,int[] t){return t.Select(i=>p[i]).ToArray();}
 static Point3D[] Frame(){var p=new List<Point3D>();for(int a=0;a<8;a++)for(int b=a+1;b<8;b++)if((cube[a]-cube[b]).Length==1){var low=new Point3D(Math.Min(cube[a].X,cube[b].X),Math.Min(cube[a].Y,cube[b].Y),Math.Min(cube[a].Z,cube[b].Z));var high=new Point3D(Math.Max(cube[a].X,cube[b].X),Math.Max(cube[a].Y,cube[b].Y),Math.Max(cube[a].Z,cube[b].Z));Func<double,double,double[]> interval=(l,h)=>l==h?(l<0?new[]{-.5,-.45}:new[]{.45,.5}):new[]{l,h};var x=interval(low.X,high.X);var y=interval(low.Y,high.Y);var z=interval(low.Z,high.Z);var v=cube.Select(q=>new Point3D(q.X<0?x[0]:x[1],q.Y<0?y[0]:y[1],q.Z<0?z[0]:z[1])).ToArray();p.AddRange(Soup(v,ids));}return p.ToArray();}
 static object NormalizedMesh(object reference,Point3D[] p,int[] t){var center=(Point3D)Get(reference,"Center");double scale=(double)Get(reference,"Scale");return Mesh(p.Select(q=>(Point3D)((q-center)/scale)).ToArray(),t);}
 static Point3D[] Stl(string path){using(var r=new BinaryReader(File.OpenRead(path))){r.ReadBytes(80);int n=r.ReadInt32();var p=new Point3D[n*3];for(int i=0;i<n;i++){r.ReadBytes(12);for(int k=0;k<3;k++)p[3*i+k]=new Point3D(r.ReadSingle(),r.ReadSingle(),r.ReadSingle());r.ReadUInt16();}return p;}}
 static async Task Deterministic<TOptions,TResult>(object reference,object options,object surface){
  var signatures=new List<string>();
  for(int round=0;round<2;round++){
   var seen=new HashSet<string>();int calls=0;Func<TOptions,CancellationToken,Task<TResult>> evaluate=(o,token)=>{
    var key=Get(o,"Width")+":"+Get(o,"Length")+":"+Get(o,"Height")+":"+Get(o,"Weld");if(!seen.Add(key))throw new Exception("Equivalent proxy candidate repeated");calls++;
    var result=New(resultType);Set(result,"Surface",surface);Set(result,"Lines",Call(surface,"Lines"));Set(result,"Points",Get(surface,"Vertices"));return Task.FromResult((TResult)result);
   };
   Func<TOptions,string> proxyKey=o=>"same-proxy";var task=(Task)Call(reference,"RunAsync",options,1,evaluate,proxyKey,new Action<string>(s=>{}),CancellationToken.None,30,100.0);await task;
   var values=(IEnumerable)task.GetType().GetProperty("Result").GetValue(task,null);signatures.Add(string.Join("|",values.Cast<object>().Select(c=>c.ToString())));Check(calls<=30,"search respects candidate count limit and proxy deduplication");
  }
  Check(signatures[0]==signatures[1],"count-bounded search is deterministic");
  Func<TOptions,CancellationToken,Task<TResult>> slow=async (o,token)=>{await Task.Delay(10000,token);return default(TResult);};
  var timer=Stopwatch.StartNew();var deadline=(Task)Call(reference,"RunAsync",options,1,slow,new Func<TOptions,string>(o=>"proxy"),new Action<string>(s=>{}),CancellationToken.None,30,.05);await deadline;Check(timer.ElapsedMilliseconds<2000,"time budget cancels an in-flight evaluation without losing completed search results");
 }
 public static void Run(string directory,string fixture,bool gpu,bool fullCheck){
  Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);Application.ThreadException+=(s,e)=>errors.Add(e.Exception);Control.CheckForIllegalCrossThreadCalls=true;
  code=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));meshType=code.GetType("BeamNG.Cad.Preparation.PreviewSurface");searchType=code.GetType("BeamNG.Cad.Preparation.HullSearch");optionsType=code.GetType("BeamNG.Cad.Preparation.HullOptions");resultType=code.GetType("BeamNG.Cad.Preparation.PreviewHull+Result");
  Check(Validate(Mesh(cube,ids))==null,"closed oriented cube is eligible");
  Check(Validate(Mesh(cube,ids.Take(ids.Length-3).ToArray()))!=null,"open seam rejected");
  Check(Validate(Mesh(cube,ids.Concat(ids.Take(3)).ToArray())).Contains("Duplicate"),"duplicate faces rejected");
  var flat=cube.Select(p=>new Point3D(p.X,p.Y,0)).ToArray();Check(Validate(Mesh(flat,ids))!=null,"collapsed shell rejected");
  var separate=cube.Concat(cube.Select(p=>p+new Vector3D(2,0,0))).ToArray();Check(Validate(Mesh(separate,ids.Concat(ids.Select(i=>i+8)).ToArray())).Contains("Disconnected"),"disconnected shells rejected");
  var torus=new Point3D[64];var ti=new List<int>();for(int a=0;a<8;a++)for(int b=0;b<8;b++){double u=2*Math.PI*a/8,v=2*Math.PI*b/8;torus[a*8+b]=new Point3D((1+.3*Math.Cos(v))*Math.Cos(u),(1+.3*Math.Cos(v))*Math.Sin(u),.3*Math.Sin(v));int p=a*8+b,q=((a+1)%8)*8+b,r=((a+1)%8)*8+(b+1)%8,s=a*8+(b+1)%8;ti.AddRange(new[]{p,q,r,p,r,s});}
  Check(Validate(Mesh(torus,ti.ToArray())).Contains("Through-holes"),"watertight torus rejected because it has a through-hole");
  var folded=(Point3D[])cube.Clone();folded[6]=new Point3D(0,0,-1);Check(Validate(Mesh(folded,ids))!=null,"self-intersecting folded shell rejected");
  var reference=New(searchType,Frame(),"XYZ",CancellationToken.None);var options=Options();var good=Call(reference,"Score",options,NormalizedMesh(reference,cube,ids),1,CancellationToken.None);
  Console.WriteLine("Windowed frame reference error: "+Get(good,"Error")+"; problem: "+Get(good,"Problem"));Check((bool)Get(good,"Accepted"),"windowed frame favors an outer shell spanning its openings");
  var box=Call(reference,"Score",options,NormalizedMesh(reference,cube.Select(p=>(Point3D)((Vector3D)p*1.7)).ToArray(),ids),1,CancellationToken.None);Check(!(bool)Get(box,"Accepted"),"oversized box cannot win by covering every opening");
  var inward=Call(reference,"Score",options,NormalizedMesh(reference,cube.Select(p=>(Point3D)((Vector3D)p*.5)).ToArray(),ids),1,CancellationToken.None);Check(!(bool)Get(inward,"Accepted"),"inward collapse fails silhouette fidelity");
  using(var cancellation=new CancellationTokenSource()){cancellation.Cancel();bool stopped=false;try{Call(reference,"Score",options,NormalizedMesh(reference,cube,ids),1,cancellation.Token);}catch(OperationCanceledException){stopped=true;}Check(stopped,"scoring observes cancellation");}
  var deterministic=typeof(HullSearchTests).GetMethod("Deterministic",F).MakeGenericMethod(optionsType,resultType);var operation=(Task)deterministic.Invoke(null,new object[]{reference,options,NormalizedMesh(reference,cube,ids)});Until(()=>operation.IsCompleted,20000);operation.GetAwaiter().GetResult();
  var source=string.IsNullOrEmpty(fixture)?Frame():Stl(fixture);
  if(!string.IsNullOrEmpty(fixture)){
   var actualReference=New(searchType,source,"XYZ",CancellationToken.None);var off=Path.Combine(Path.GetDirectoryName(fixture),"mochi_hull.off");
   if(File.Exists(off)){var actual=meshType.GetMethod("ReadOff",F).Invoke(null,new object[]{off,Get(actualReference,"Center"),Get(actualReference,"Scale"),CancellationToken.None});var score=Call(actualReference,"Score",options,actual,1,CancellationToken.None);Console.WriteLine("SAVED FULL HULL: error "+Get(score,"Error")+"; minimum IoU "+Get(score,"MinimumIoU")+"; problem "+Get(score,"Problem"));}
  }
  using(var pane=(Control)New(code.GetType("BeamNG.Cad.UI.FramePreviewPane")))using(var shell=new Form {Width=1050,Height=850}){
   var window=(Form)Get(pane,"Preview");Set(window,"ForceCpuPreview",!gpu);shell.Controls.Add(pane);shell.Show();Call(window,"SetSnapshot",source,options);
   Until(()=>((Label)Get(window,"state")).Text.StartsWith(gpu?"GPU approximation":"Approximate preview"),20000);
   object baseline=Get(window,"options");object oldProjected=gpu?Get(Get(window,"gpu"),"projected"):Get(window,"scene");
   ((Delegate)Get(window,"SearchOpened")).DynamicInvoke();Call(window,"StartSearch");Until(()=>(bool)window.GetType().GetProperty("IsOptimizing",F).GetValue(window,null),5000);Until(()=>!(bool)window.GetType().GetProperty("IsOptimizing",F).GetValue(window,null),45000);
   Check(Object.ReferenceEquals(baseline,Get(window,"options")),"search leaves current options unchanged");
   Check(Object.ReferenceEquals(oldProjected,gpu?Get(Get(window,"gpu"),"projected"):Get(window,"scene")),"candidate evaluation does not flash or replace baseline viewport");
   var list=(ListBox)Get(window,"suggestions");Console.WriteLine("SEARCH: "+((Label)Get(window,"searchMessage")).Text);foreach(var row in list.Items)Console.WriteLine("CANDIDATE: "+row);
   Check(list.Items.Count>0,"search produces reviewable attempts");
   list.SelectedIndex=0;Check(((Label)Get(window,"state")).Text.StartsWith("Candidate"),"candidate selection is explicitly labelled not applied");Check(Object.ReferenceEquals(baseline,Get(window,"options")),"previewing candidate does not apply it");
   Check(((CheckBox)Get(window,"showVolume")).Enabled==gpu,"pruning volume is available only for the GPU approximation candidate");
   if(fullCheck){
    var candidate=list.Items.Cast<object>().First(c=>(bool)Get(c,"Accepted"));var referenceForCheck=Get(window,"search");
    var root=Path.Combine(Path.GetTempPath(),"beamng-hull-check-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
    var settingsType=code.GetType("BeamNG.Cad.UI.ExporterSettings");var settings=New(settingsType,Path.Combine(root,"settings.xml"));var current=New(settingsType,new object[]{null});
    foreach(var name in new[]{"PythonExecutable","BlenderExecutable","CgalPythonExecutable"})settingsType.GetProperty(name).SetValue(settings,settingsType.GetProperty(name).GetValue(current,null),null);
    settingsType.GetProperty("FrameOutput").SetValue(settings,root,null);
    using(var checker=(Form)New(code.GetType("BeamNG.Cad.UI.FramePreviewWindow"),settings)){
     Set(checker,"ForceCpuPreview",!gpu);checker.Show();Call(checker,"SetSnapshot",source,options);Until(()=>((Label)Get(checker,"state")).Text.StartsWith(gpu?"GPU approximation":"Approximate preview"),20000);
     Set(checker,"search",referenceForCheck);var rows=(ListBox)Get(checker,"suggestions");rows.Items.Add(candidate);rows.SelectedIndex=0;var oldOptions=Get(checker,"options");
     Call(checker,"CheckSelected");Until(()=>(bool)checker.GetType().GetProperty("IsOptimizing",F).GetValue(checker,null),5000);Until(()=>!(bool)checker.GetType().GetProperty("IsOptimizing",F).GetValue(checker,null),180000);
     Console.WriteLine("CHECK OUTPUT: "+root);Console.WriteLine("CHECK STATUS: "+((Label)Get(checker,"searchMessage")).Text);foreach(var row in rows.Items)Console.WriteLine("CHECKED CANDIDATE: "+row);
     Check(rows.Items.Cast<object>().Any(c=>(string)Get(c,"Check")=="CGAL checked snapshot"),"full check adds actual Blender/CGAL candidate meshes");Check(Object.ReferenceEquals(oldOptions,Get(checker,"options")),"checking ratios leaves current settings unchanged");
     var checkedRow=rows.Items.Cast<object>().First(c=>(string)Get(c,"Check")=="CGAL checked snapshot");rows.SelectedItem=checkedRow;
     Check(!((CheckBox)Get(checker,"showVolume")).Enabled&&!((CheckBox)Get(checker,"showVolume")).Checked,"checked OFF candidate disables the pruning volume it does not retain");
     checker.Close();Pump(100);
    }
   }
   var eligible=list.Items.Cast<object>().FirstOrDefault(c=>(bool)Get(c,"Accepted"))??list.Items[0];
   if(eligible!=null){
    list.SelectedItem=eligible;var ev=window.GetType().GetEvent("ApplyRequested",F);var argument=System.Linq.Expressions.Expression.Parameter(optionsType,"value");
    var callback=System.Linq.Expressions.Expression.Lambda(ev.EventHandlerType,System.Linq.Expressions.Expression.Call(typeof(HullSearchTests).GetMethod("Applied",F),System.Linq.Expressions.Expression.Convert(argument,typeof(object))),argument).Compile();ev.GetAddMethod(true).Invoke(window,new object[]{callback});
    ((Button)Get(window,"applyHull")).PerformClick();Check(applyCount==1&&applied!=null&&!Object.ReferenceEquals(applied,Get(eligible,"Options")),"Apply emits exactly one cloned settings update");
    foreach(var name in new[]{"Offset","Symmetry","SymmetryBisectFlip","SymmetryMergeDistance","Orientation","ProxyOffsetRatio"})Check(Object.Equals(Get(applied,name),Get(options,name)),"search keeps "+name+" locked");
   }
   var reassessed=list.SelectedItem;var oldSurface=Get(reassessed,"Surface");int oldCount=list.Items.Count;
   Set(reassessed,"Problem",null);Set(reassessed,"Error",.045);Set(reassessed,"MinimumIoU",.92);Set(reassessed,"Check","CGAL checked snapshot");
   var quality=(ComboBox)Get(window,"searchQuality");quality.SelectedIndex=2;
   Check(((Button)Get(window,"applyHull")).Enabled&&((Button)Get(window,"applyHull")).Text=="Apply anyway"&&((Label)Get(window,"applyStatus")).Text.Contains("Outside optimizer target"),"below-target checked result offers Apply anyway with its warning");
   ((Button)Get(window,"applyHull")).PerformClick();Check(applyCount==2&&!Object.ReferenceEquals(applied,Get(reassessed,"Options"))&&!(bool)Get(reassessed,"Accepted"),"manual apply copies below-target settings without marking the mesh accepted");
   quality.SelectedIndex=1;
   Check(((Button)Get(window,"applyHull")).Enabled&&Object.ReferenceEquals(list.SelectedItem,reassessed)&&list.Items.Count==oldCount&&Object.ReferenceEquals(Get(reassessed,"Surface"),oldSurface),"Balanced enables the same checked mesh without rerunning or losing selection");
   Check((string)Get(reassessed,"Check")=="CGAL checked snapshot"&&Object.ReferenceEquals(baseline,Get(window,"options")),"quality reassessment preserves checked status and current hull settings");
   Set(reassessed,"Problem","Open seam or nonmanifold edge.");quality.SelectedIndex=0;
   Check(((Button)Get(window,"applyHull")).Enabled&&((Label)Get(window,"applyStatus")).Text.Contains("Optimizer warning"),"structural optimizer warnings also allow an explicit manual settings choice");
   ((Button)Get(window,"applyHull")).PerformClick();Check(applyCount==3&&!(bool)Get(reassessed,"Accepted")&&(string)Get(reassessed,"Problem")=="Open seam or nonmanifold edge.","manual apply retains structural rejection diagnostics");
   Call(window,"UpdateOptions",options);Check(list.Items.Count==0,"settings changes invalidate shortlist");
   ((Delegate)Get(window,"SearchOpened")).DynamicInvoke();Call(window,"StartSearch");Until(()=>(bool)window.GetType().GetProperty("IsOptimizing",F).GetValue(window,null),5000);Call(window,"MarkStale","Fixture CAD changed");Until(()=>!(bool)window.GetType().GetProperty("IsOptimizing",F).GetValue(window,null),15000);Check(list.Items.Count==0&&Get(window,"source")==null,"CAD invalidation cancels search without resurrecting suggestions");shell.Close();Pump(200);
  }
  Check(errors.Count==0,"search lifecycle has no cross-thread or disposal errors");
 }
}
'@
[HullSearchTests]::Run($OutputDirectory,$FrameStl,$Gpu.IsPresent,$Check.IsPresent)
