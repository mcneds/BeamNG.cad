param(
 [string]$OutputDirectory=(Join-Path $PSScriptRoot '../beamng.cad/bin/proxy-preview-verified'),
 [string]$FrameStl='',
 [switch]$Software,
 [switch]$Gpu
)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Run in Windows PowerShell -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$wpf=Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'WPF'
$refs=@('System.Core','System.Drawing','System.Windows.Forms',
 (Join-Path $wpf 'WindowsBase.dll'),(Join-Path $wpf 'PresentationCore.dll'),
 (Join-Path $wpf 'PresentationFramework.dll'),(Join-Path $wpf 'WindowsFormsIntegration.dll'))
foreach($ref in $refs[3..6]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Reflection;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Media;
using System.Windows.Media.Media3D;
public static class FramePreviewTests {
 [System.Runtime.InteropServices.DllImport("opengl32.dll")] static extern IntPtr wglGetCurrentContext();
 static Assembly code;static Type geometry,optionsType;const BindingFlags Flags=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static;
 static System.Collections.Generic.List<string> unhandled=new System.Collections.Generic.List<string>();
 static object Field(object value,string name){return value.GetType().GetField(name,Flags).GetValue(value);}
 static void Set(object value,string name,object data){value.GetType().GetField(name,Flags).SetValue(value,data);}
 static object Call(object value,string name,params object[] args){try{return value.GetType().GetMethod(name,Flags).Invoke(value,args);}catch(TargetInvocationException e){throw e.InnerException;}}
 static object Options(int grid){var value=Activator.CreateInstance(optionsType,true);foreach(var name in new[]{"Width","Height","Length"})Set(value,name,grid);Set(value,"Offset",0.0);Set(value,"Weld",0.0);return value;}
 static object Proxy(Point3D[] points,object options,CancellationToken token){try{return geometry.GetMethod("Proxy",Flags).Invoke(null,new object[]{points,options,token});}catch(TargetInvocationException e){throw e.InnerException;}}
 static object Exact(string path,object context){try{return geometry.GetMethod("Exact",Flags).Invoke(null,new object[]{path,context,CancellationToken.None});}catch(TargetInvocationException e){throw e.InnerException;}}
 static void Check(bool ok,string message){if(!ok)throw new Exception(message);Console.WriteLine("PASS: "+message);}
 static void Pump(int ms){var clock=Stopwatch.StartNew();while(clock.ElapsedMilliseconds<ms){Application.DoEvents();Thread.Sleep(2);}}
 static void Until(Func<bool> done){var clock=Stopwatch.StartNew();while(!done()){Pump(5);if(clock.ElapsedMilliseconds>15000)throw new Exception("Preview UI timed out");}}
 static Point3D[] Points(){return new[]{new Point3D(0,0,0),new Point3D(.2,0,0),new Point3D(0,.2,0),new Point3D(3,0,0),new Point3D(3.2,0,0),new Point3D(3,.2,0)};}
 static Point3D[] Stl(string path){using(var reader=new BinaryReader(File.OpenRead(path))){reader.ReadBytes(80);uint count=reader.ReadUInt32();if(count>200000||reader.BaseStream.Length!=84+50L*count)throw new Exception("Fixture exceeds preview budget or is not binary STL");var points=new Point3D[count*3];for(int i=0;i<count;i++){reader.ReadBytes(12);for(int j=0;j<3;j++)points[3*i+j]=new Point3D(reader.ReadSingle(),reader.ReadSingle(),reader.ReadSingle());reader.ReadUInt16();}return points;}}
 public static void Run(string directory,string stl,bool software,bool gpu){
  Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
  Application.ThreadException+=(s,e)=>{unhandled.Add(e.Exception.ToString());Console.WriteLine("UI EXCEPTION: "+e.Exception);};
  if(software)System.Windows.Media.RenderOptions.ProcessRenderMode=System.Windows.Interop.RenderMode.SoftwareOnly;
  code=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));geometry=code.GetType("BeamNG.Cad.Preparation.PreviewGeometry");optionsType=code.GetType("BeamNG.Cad.Preparation.HullOptions");
  Postprocess();Docked(gpu);
  if(gpu){RunGpu(stl);Check(unhandled.Count==0,"GPU window lifecycle has no UI exceptions");return;}
  var points=Points();var options=Options(9);var result=Proxy(points,options,CancellationToken.None);
  var source=(MeshGeometry3D)Field(result,"Source");var overlay=(MeshGeometry3D)Field(result,"Overlay");
  Check(source.IsFrozen&&overlay.IsFrozen&&source.Positions.Count==points.Length,"immutable meshes cross worker/UI boundary without dropping CAD triangles");
  Check(overlay.Positions.Count>0&&overlay.TriangleIndices.Count<6*2*8*8*8*3,"projected edge mesh remains bounded");
  var center=(Point3D)Field(result,"Center");double scale=(double)Field(result,"Scale");
  Check(Math.Abs(source.Positions[2].Z*scale+center.Z-.2)<1e-9&&Math.Abs(source.Positions[2].Y*scale+center.Y)<1e-9,"SolidWorks Y maps to BeamNG Z");
  var oldBounds=overlay.Bounds;Set(options,"Offset",.1);var expanded=Proxy(points,options,CancellationToken.None);
  var expandedMesh=(MeshGeometry3D)Field(expanded,"Overlay");
  Check(expandedMesh.Bounds.SizeZ*(double)Field(expanded,"Scale")>oldBounds.SizeZ*scale,"surface offset changes the projected result in physical units");
  var capped=Proxy(points,Options(100),CancellationToken.None);
  Check(((string)Field(capped,"Summary")).Contains("grid 100 ")&&((MeshGeometry3D)Field(capped,"Overlay")).Positions.Count<=100*100*100*36,"full requested grid is evaluated within the declared input limit");
  bool cancelled=false;using(var cancel=new CancellationTokenSource()){cancel.Cancel();try{Proxy(points,options,cancel.Token);}catch(OperationCanceledException){cancelled=true;}}Check(cancelled,"cancelled geometry request exits");
  bool invalid=false;try{Proxy(new[]{new Point3D(double.NaN,0,0),points[1],points[2]},options,CancellationToken.None);}catch(InvalidDataException){invalid=true;}Check(invalid,"non-finite source rejected");
  string path=Path.Combine(Path.GetTempPath(),"beamng-preview-"+Guid.NewGuid().ToString("N")+".off");
  try{
   File.WriteAllText(path,"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n");var exact=Exact(path,null);
   Check(((string)Field(exact,"Summary")).Contains("3 unique")&&((MeshGeometry3D)Field(exact,"Overlay")).IsFrozen,"actual OFF edges are batched into a frozen display mesh");
   File.WriteAllText(path,"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 8\n");invalid=false;try{Exact(path,null);}catch(InvalidDataException){invalid=true;}Check(invalid,"invalid OFF indices rejected");
   File.WriteAllText(path,"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n");
   var errors=new System.Collections.Generic.List<string>();Application.ThreadException+=(s,e)=>errors.Add(e.Exception.ToString());
   using(var form=(Form)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.FramePreviewWindow"),true)){
    Set(form,"ForceCpuPreview",true);
    form.Show();Call(form,"SetSnapshot",points,Options(9));
    Until(()=>((Label)Field(form,"state")).Text.StartsWith("Approximate preview"));
    Call(form,"UpdateOptions",Options(5));Call(form,"UpdateOptions",Options(11));
    Until(()=>((Label)Field(form,"state")).Text.Contains("grid 11 "));
    Check(((string)Field(Field(form,"scene"),"Summary")).Contains("grid 11 "),"rapid edits install only newest preview");
    var task=(Task)Call(form,"ShowExactAsync",path,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();
    Check(((Label)Field(form,"state")).Text.StartsWith("Prepared hull"),"prepared hull replaces approximation");
    Call(form,"MarkStale","Fixture changed.");Pump(350);Check(Field(form,"scene")==null&&Field(form,"source")==null,"CAD invalidation removes stale geometry and prevents late resurrection");
    form.Size=new System.Drawing.Size(420,360);Pump(30);Check(((Control)Field(form,"host")).Height>0,"viewport remains reachable at minimum window size");
    Call(form,"SetSnapshot",points,Options(9));Call(form,"UpdateProxy");form.Close();Pump(500);
   }
   Check(errors.Count==0,"close during background preview has no UI-thread errors");
  }finally{File.Delete(path);}
  if(!string.IsNullOrEmpty(stl)){
   var fixture=Stl(stl);var clock=Stopwatch.StartNew();var measured=Proxy(fixture,Options(25),CancellationToken.None);
   Console.WriteLine("MEASURED: saved CAD STL, "+fixture.Length/3+" triangles, 25-point grid, "+clock.ElapsedMilliseconds+" ms CPU projected-hull estimate; excludes capture/upload/display. "+Field(measured,"Summary"));
  }
  Console.WriteLine("Rendering capability tier: "+(RenderCapability.Tier>>16)+"; forced software: "+software+". This is not a SolidWorks live-host or GPU timing qualification.");
 }
 static Point3D[] Cube(){
  var vertices=new[]{new Point3D(-.5,-.5,-.5),new Point3D(.5,-.5,-.5),new Point3D(.5,.5,-.5),new Point3D(-.5,.5,-.5),new Point3D(-.5,-.5,.5),new Point3D(.5,-.5,.5),new Point3D(.5,.5,.5),new Point3D(-.5,.5,.5)};
  var ids=new[]{0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,3,7,6,3,6,2,0,4,7,0,7,3,1,2,6,1,6,5};var points=new Point3D[ids.Length];for(int i=0;i<ids.Length;i++)points[i]=vertices[ids[i]];return points;
 }
 static void Postprocess(){
  var source=Cube();var packed=new float[source.Length*4];for(int i=0;i<source.Length;i++){packed[4*i]=(float)source[i].X;packed[4*i+1]=(float)source[i].Y;packed[4*i+2]=(float)source[i].Z;}
  var type=code.GetType("BeamNG.Cad.Preparation.PreviewHull");var hull=Activator.CreateInstance(type,Flags,null,new object[]{packed,CancellationToken.None},null);
  var volume=new uint[8*8*8];for(int i=0;i<volume.Length;i++)volume[i]=1;
  var options=Options(3);Set(options,"Orientation","XYZ");
  var result=Call(hull,"Evaluate",volume,8,-.5,.125,1.0,options,CancellationToken.None);
  Check(((Point3D[])Field(result,"Points")).Length==26&&(int)Field(result,"Faces")==48,"analytic cube yields the expected pruned/projected 3-point lattice topology");
  var shrunk=Call(hull,"Evaluate",volume,8,-1.0,.25,1.0,options,CancellationToken.None);
  var shrunkPoints=(Point3D[])Field(shrunk,"Points");
  Check(System.Linq.Enumerable.All(shrunkPoints,p=>Math.Abs(p.X)<=.500001&&Math.Abs(p.Y)<=.500001&&Math.Abs(p.Z)<=.500001)&&shrunkPoints.Length==26,"nearest-triangle projection shrinks an oversized lattice onto the actual CAD cube");
  var denser=Call(hull,"Evaluate",volume,8,-.5,.125,1.0,Options(5),CancellationToken.None);
  Check(((Point3D[])Field(denser,"Points")).Length==98,"grid density changes projected hull topology");
  Set(options,"Offset",.1);var offset=Call(hull,"Evaluate",volume,8,-.5,.125,1.0,options,CancellationToken.None);
  Check(!System.Linq.Enumerable.SequenceEqual((float[])Field(result,"Lines"),(float[])Field(offset,"Lines")),"surface offset affects projected geometry independently of the pruning volume");
  Set(options,"Weld",2.0);var welded=Call(hull,"Evaluate",volume,8,-.5,.125,1.0,options,CancellationToken.None);
  Check(((float[])Field(welded,"Lines")).Length==0,"weld collapses nearby vertices and removes degenerate faces");
  var symmetric=Options(3);Set(symmetric,"Symmetry",true);Set(symmetric,"SymmetryMergeDistance",.6);
  var seam=Call(hull,"Evaluate",volume,8,-.5,.125,1.0,symmetric,CancellationToken.None);
  Check(((Point3D[])Field(seam,"Points")).Length>0&&System.Linq.Enumerable.All((Point3D[])Field(seam,"Points"),p=>Math.Abs(p.X)<1e-9),"seam merge distance affects the mirrored projected mesh");
  using(var cancel=new CancellationTokenSource()){cancel.Cancel();bool stopped=false;try{Call(hull,"Evaluate",volume,8,-.5,.125,1.0,Options(5),cancel.Token);}catch(OperationCanceledException){stopped=true;}Check(stopped,"post-wrap work observes cancellation");}
 }
 static void Docked(bool gpu){
  using(var shell=new Form {Width=350,Height=800})
  using(var pane=(Control)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.FramePreviewPane"),true)){
   var preview=(Form)Field(pane,"Preview");Set(preview,"ForceCpuPreview",!gpu);
   var editors=(TabControl)Field(pane,"Editors");var settings=new TabPage("Hull settings");
   var options=(UserControl)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.HullOptionsPanel"),true);
   settings.Controls.Add(options);editors.TabPages.Add(settings);editors.TabPages.Add(new TabPage("Build"));
   Func<object> value=()=>options.GetType().GetProperty("Value",Flags).GetValue(options,null);
   options.GetType().GetEvent("ValueChanged").AddEventHandler(options,new EventHandler((s,e)=>Call(preview,"UpdateOptions",value())));
   shell.Controls.Add(pane);shell.Show();Pump(60);
   Check(!preview.TopLevel&&preview.Parent!=null&&preview.Visible,"preview is embedded in the settings workspace");
   var handle=preview.Handle;var graphics=(Control)Field(preview,gpu?"gpu":"host");var graphicsHandle=graphics.Handle;
   Call(preview,"SetSnapshot",Points(),value());
   Func<bool> ready=()=>gpu?(bool)Field(preview,"gpuReady")&&(bool)graphics.GetType().GetProperty("HasResult",Flags).GetValue(graphics,null):Field(preview,"scene")!=null&&Field(Field(preview,"scene"),"Overlay")!=null;
   Until(ready);
   var number=(NumericUpDown)options.Controls.Find("HullProxyDivisor",true)[0];
   number.Focus();number.Value=14;Until(ready);number.Value=9;Until(ready);
   Check(preview.Visible&&!preview.IsDisposed&&preview.Handle==handle&&graphics.Handle==graphicsHandle&&number.Focused,"editing actual hull controls preserves the preview and input focus");
   var split=(SplitContainer)Field(pane,"split");
   Check(split.Orientation==Orientation.Horizontal&&graphics.Height>=120&&editors.Height>=180&&!options.HorizontalScroll.Visible,"narrow dock keeps a usable viewport and scrolling settings without horizontal overflow");
   var divider=split.SplitterDistance;split.SplitterDistance=divider+20;Pump(20);
   Check(split.SplitterDistance==divider+20,"preview/settings divider can be resized");
   shell.Width=1000;Pump(50);
   Check(split.Orientation==Orientation.Vertical&&preview.Width>=280&&editors.Width>=280,"wide dock puts preview beside settings");
   editors.SelectedIndex=1;Pump(20);Check(preview.Visible,"preview stays visible on other frame tabs");
   pane.Hide();shell.Controls.Remove(pane);Pump(20);shell.Controls.Add(pane);pane.Show();shell.Width=350;Pump(60);
   Check(preview.Visible&&preview.Handle==handle&&graphics.Handle==graphicsHandle&&ready(),"navigation and narrow/wide resizing preserve the renderer and captured result");
   Call(preview,"UpdateOptions",value());shell.Close();Pump(400);
   Check(preview.IsDisposed&&graphics.IsDisposed,"closing the frame owner disposes its renderer");
  }
  Check(unhandled.Count==0,"docked preview lifecycle has no UI exceptions");
 }
 static uint BoundaryVertices(uint[] volume){uint count=0;const int n=64;for(int z=0;z<n;z++)for(int y=0;y<n;y++)for(int x=0;x<n;x++){int i=x+n*(y+n*z);if(volume[i]==0)continue;foreach(int step in new[]{-1,1,-n,n,-n*n,n*n}){bool edge=step==-1?x==0:step==1?x==n-1:step==-n?y==0:step==n?y==n-1:step==-n*n?z==0:z==n-1;if(edge||volume[i+step]==0)count+=6;}}return count;}
 static void RunGpu(string stl){
  var source=string.IsNullOrEmpty(stl)?Points():Stl(stl);var options=Options(9);Set(options,"Weld",0.0);if(!string.IsNullOrEmpty(stl))Set(options,"Orientation","XYZ");
  using(var form=new Form {Width=850,Height=650})using(var view=(Control)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.GpuFramePreview"),true)){
   var originalContext=wglGetCurrentContext();
   form.Controls.Add(view);form.Show();Call(view,"Initialize");Console.WriteLine("GPU renderer: "+view.GetType().GetProperty("Renderer",Flags).GetValue(view,null));
   var first=Stopwatch.StartNew();var task=(Task<string>)Call(view,"UpdateAsync",source,options,CancellationToken.None);Until(()=>task.IsCompleted);Console.WriteLine(task.GetAwaiter().GetResult());
   Console.WriteLine("MEASURED: first GPU voxelization + update "+first.ElapsedMilliseconds+" ms, "+source.Length/3+" source triangles.");
   uint count=(uint)Call(view,"ReadVertexCountForTest");Check(count>0&&count%6==0&&count<=64*64*64*36,"GPU compute produces a bounded pruning volume");
   view.Refresh();Check((int)Call(view,"ReadColoredPixelsForTest")>20,"projected grid draws visible orange edges");
   Set(view,"ShowSource",false);Set(view,"ShowProxy",false);Set(view,"ShowVolume",false);view.Refresh();Check((int)Call(view,"ReadColoredPixelsForTest")==0,"volume off removes its pixels when CAD and edges are hidden");
   Set(view,"ShowVolume",true);view.Refresh();Check((int)Call(view,"ReadColoredPixelsForTest")>100,"pruning-volume toggle produces visible shaded volume pixels");
   var different=Options(9);Set(different,"ProxyDivisor",3.0);if(!string.IsNullOrEmpty(stl))Set(different,"Orientation","XYZ");
   var candidateTask=(Task)Call(view,"EvaluateCandidateAsync",source,different,CancellationToken.None);Until(()=>candidateTask.IsCompleted);candidateTask.GetAwaiter().GetResult();var candidate=candidateTask.GetType().GetProperty("Result").GetValue(candidateTask,null);
   Check((uint)Call(view,"ReadVertexCountForTest")==count,"offscreen candidate evaluation preserves the visible pruning buffer");
   Call(view,"PresentCandidate",candidate);Check((uint)Call(view,"ReadVertexCountForTest")==BoundaryVertices((uint[])Field(candidate,"PruningVolume")),"candidate presentation rebuilds faces from that candidate's retained volume");
   view.Refresh();Check((int)Call(view,"ReadColoredPixelsForTest")>100,"candidate pruning volume renders after selection");
   var checkedMesh=Activator.CreateInstance(candidate.GetType(),true);Set(checkedMesh,"Lines",Field(candidate,"Lines"));Call(view,"PresentCandidate",checkedMesh);
   Check(!(bool)view.GetType().GetProperty("HasPruningVolume",Flags).GetValue(view,null),"checked mesh without retained proxy cannot display an old pruning volume");
   Set(view,"ShowSource",true);Set(view,"ShowProxy",true);Set(view,"ShowVolume",false);
   Set(options,"ProxyDivisor",14.0);var clock=Stopwatch.StartNew();task=(Task<string>)Call(view,"UpdateAsync",source,options,CancellationToken.None);Until(()=>task.IsCompleted);Console.WriteLine(task.GetAwaiter().GetResult());
   Console.WriteLine("MEASURED: cached GPU parameter edit including fence "+clock.Elapsed.TotalMilliseconds.ToString("0.0",System.Globalization.CultureInfo.InvariantCulture)+" ms.");
   uint changed=(uint)Call(view,"ReadVertexCountForTest");Console.WriteLine("GPU boundary vertices before/after alpha edit: "+count+" / "+changed);
   var timings=new System.Collections.Generic.List<double>();
   for(int i=0;i<20;i++){
    Set(options,"ProxyDivisor",i%2==0?7.0:14.0);task=(Task<string>)Call(view,"UpdateAsync",source,options,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();
    timings.Add((double)view.GetType().GetProperty("LastUpdateMilliseconds",Flags).GetValue(view,null));
   }
   timings.Sort();Console.WriteLine("MEASURED: 20 cached alpha edits, hybrid update median "+timings[10].ToString("0.0",System.Globalization.CultureInfo.InvariantCulture)+" ms; p95 "+timings[18].ToString("0.0",System.Globalization.CultureInfo.InvariantCulture)+" ms. Includes readback, pruning, projection and weld; excludes debounce, capture and presentation.");
   if(!string.IsNullOrEmpty(stl)){
    var typical=Options(3);Set(typical,"Height",5);Set(typical,"Length",7);Set(typical,"Offset",.01);Set(typical,"Weld",.15);Set(typical,"Orientation","XYZ");
    var measured=new System.Collections.Generic.List<double>();
    for(int i=0;i<5;i++){task=(Task<string>)Call(view,"UpdateAsync",source,typical,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();measured.Add((double)view.GetType().GetProperty("LastUpdateMilliseconds",Flags).GetValue(view,null));}
    measured.Sort();Console.WriteLine("MEASURED: original 3 x 7 x 5 (X/Y/Z) settings, .01 m offset/.15 m weld, hybrid update median "+measured[2].ToString("0.0",System.Globalization.CultureInfo.InvariantCulture)+" ms. "+task.GetAwaiter().GetResult());
    var grid=(float[])Field(Field(view,"projected"),"Lines");Check(grid.Length>0,"saved CAD produces a drawable projected hull with its original settings");
   }
   Set(options,"Offset",.1);task=(Task<string>)Call(view,"UpdateAsync",source,options,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();Check((uint)Call(view,"ReadVertexCountForTest")>0,"offset edit leaves a renderable GPU envelope");
   Call(view,"InvalidateResult");Check(!(bool)view.GetType().GetProperty("HasResult",Flags).GetValue(view,null),"superseded GPU result is hidden immediately");
   using(var cancel=new CancellationTokenSource()){cancel.Cancel();task=(Task<string>)Call(view,"UpdateAsync",source,options,cancel.Token);Until(()=>task.IsCompleted);Check(task.IsCanceled,"GPU update cancellation is surfaced");}
   view.Invalidate();Pump(100);Call(view,"ClearSnapshot");Check(!(bool)view.GetType().GetProperty("HasResult",Flags).GetValue(view,null),"GPU snapshot cleared on CAD invalidation");
   var cpu=Stopwatch.StartNew();Proxy(source,Options(25),CancellationToken.None);Console.WriteLine("MEASURED: CPU projected-hull fallback "+cpu.ElapsedMilliseconds+" ms; different approximation, not a CGAL comparison.");
   var asymmetric=new[]{new Point3D(-2,0,0),new Point3D(-1,0,0),new Point3D(-1,1,0),new Point3D(1,4,0),new Point3D(2,4,0),new Point3D(1,5,0)};
   var symmetry=Options(9);Set(symmetry,"Orientation","XYZ");Set(symmetry,"Symmetry",true);Set(symmetry,"ProxyDivisor",10000.0);
   task=(Task<string>)Call(view,"UpdateAsync",asymmetric,symmetry,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();
   Check((double)Call(view,"ReadMeanFaceYForTest")>0,"default symmetry keeps +X source half, matching Blender bisect convention");
   Set(symmetry,"SymmetryBisectFlip",true);task=(Task<string>)Call(view,"UpdateAsync",asymmetric,symmetry,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();
   Check((double)Call(view,"ReadMeanFaceYForTest")<0,"flipped symmetry keeps the opposite source half");
   Set(symmetry,"Symmetry",false);task=(Task<string>)Call(view,"UpdateAsync",asymmetric,symmetry,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();
   var baseline=(float[])Field(Field(view,"projected"),"Lines");
   Set(symmetry,"Symmetry",true);task=(Task<string>)Call(view,"UpdateAsync",asymmetric,symmetry,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();
   Set(symmetry,"Symmetry",false);task=(Task<string>)Call(view,"UpdateAsync",asymmetric,symmetry,CancellationToken.None);Until(()=>task.IsCompleted);task.GetAwaiter().GetResult();
   Check(System.Linq.Enumerable.SequenceEqual(baseline,(float[])Field(Field(view,"projected"),"Lines")),"symmetry off restores the identical unsymmetrized projected result");
   Check(wglGetCurrentContext()==originalContext,"preview restores the caller's OpenGL context");
   form.Close();
  }
  using(var window=(Form)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.FramePreviewWindow"),true)){
   window.Show();Call(window,"SetSnapshot",source,options);
   Until(()=>((Label)Field(window,"state")).Text.StartsWith("GPU approximation"));
   Check((bool)Field(window,"gpuReady"),"integrated preview window selects GPU compute");
   var volumeToggle=(CheckBox)Field(window,"showVolume");Check(volumeToggle.Enabled,"live GPU view enables its retained pruning volume");volumeToggle.Checked=true;

   Set(options,"ProxyDivisor",10.0);Call(window,"UpdateOptions",options);Set(options,"ProxyDivisor",12.0);Call(window,"UpdateOptions",options);
   Until(()=>((Label)Field(window,"state")).Text.StartsWith("GPU approximation"));
   var baseline=(float[])Field(Field(Field(window,"gpu"),"projected"),"Lines");
   var invalid=Options(4);Set(invalid,"Symmetry",true);Call(window,"UpdateOptions",invalid);
   Until(()=>((Label)Field(window,"state")).Text.StartsWith("Invalid preview settings"));
   Check((bool)Field(window,"gpuReady")&&Field(window,"source")!=null,"even-width symmetry validation keeps GPU backend and source snapshot");
   Call(window,"UpdateOptions",options);Until(()=>((Label)Field(window,"state")).Text.StartsWith("GPU approximation"));
   Check(System.Linq.Enumerable.SequenceEqual(baseline,(float[])Field(Field(Field(window,"gpu"),"projected"),"Lines")),"correcting invalid symmetry restores the same GPU hull without refresh");
   Check(volumeToggle.Checked&&volumeToggle.Enabled,"pruning-volume choice survives live parameter updates");
   var preparedFile=Path.Combine(Path.GetTempPath(),"beamng-volume-"+Guid.NewGuid().ToString("N")+".off");
   try{File.WriteAllText(preparedFile,"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n");var exactTask=(Task)Call(window,"ShowExactAsync",preparedFile,CancellationToken.None);Until(()=>exactTask.IsCompleted);exactTask.GetAwaiter().GetResult();Check(!volumeToggle.Enabled&&!volumeToggle.Checked,"prepared OFF view disables its unavailable pruning volume");}finally{File.Delete(preparedFile);}
   Call(window,"MarkStale","Fixture changed.");Pump(300);Check(Field(window,"source")==null&&!(bool)Field(window,"gpu").GetType().GetProperty("HasResult",Flags).GetValue(Field(window,"gpu"),null),"integrated GPU invalidation removes stale preview");
   Call(window,"SetSnapshot",source,options);Call(window,"UpdateProxy");
   Until(()=>(int)Field(Field(window,"gpu"),"sourceCount")>0);
   window.Close();Pump(300);
   Check(window.IsDisposed,"closing during GPU snapshot work disposes the window");
  }
 }
}
'@
try { [FramePreviewTests]::Run($OutputDirectory,$FrameStl,$Software.IsPresent,$Gpu.IsPresent) }
catch { Write-Output $_.Exception.ToString(); throw }
