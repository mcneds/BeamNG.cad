param(
 [Parameter(Mandatory=$true)][string]$Recipe,
 [Parameter(Mandatory=$true)][string]$Destination,
 [string]$OutputDirectory,
 [string]$ReuseCad,
 [string]$CaptureAssembly,
 [switch]$CaptureExistingOnly
)
$ErrorActionPreference='Stop'
if($CaptureExistingOnly -and -not $CaptureAssembly){throw 'CaptureExistingOnly requires CaptureAssembly'}
if(-not $OutputDirectory){$OutputDirectory=Join-Path $PSScriptRoot '..\beamng.cad\bin\synthetic-mvp'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Recipe=(Resolve-Path -LiteralPath $Recipe).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new synthetic CAD directory'}
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
$source=@'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class SyntheticNativeCad {
 delegate bool WindowCallback(IntPtr window,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent,WindowCallback callback,IntPtr parameter);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint process);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window,System.Text.StringBuilder text,int count);
 [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window,uint message,IntPtr w,IntPtr l);
 static System.Threading.Timer promptGuard;
 static string WindowText(IntPtr window){var text=new System.Text.StringBuilder(256);GetWindowText(window,text,256);return text.ToString();}
 public static void GuardOwnedPrompt(int process){
  promptGuard=new System.Threading.Timer(_=>EnumWindows((window,p)=>{
   uint owner;GetWindowThreadProcessId(window,out owner);
   if(owner==(uint)process && WindowText(window)=="Find SOLIDWORKS Toolbox Managed in SOLIDWORKS PDM")
    EnumChildWindows(window,(button,q)=>{uint childOwner;GetWindowThreadProcessId(button,out childOwner);if(childOwner==owner && WindowText(button)=="No")PostMessage(button,0xF5,IntPtr.Zero,IntPtr.Zero);return true;},IntPtr.Zero);
   return true;
  },IntPtr.Zero),null,0,500);
 }
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out IBindCtx context);
 public static ISldWorks Find(int pid){IRunningObjectTable table;IBindCtx context;GetRunningObjectTable(0,out table);CreateBindCtx(0,out context);IEnumMoniker list;table.EnumRunning(out list);var item=new IMoniker[1];
  try{while(list.Next(1,item,IntPtr.Zero)==0){try{string name;item[0].GetDisplayName(context,null,out name);if(name=="SolidWorks_PID_"+pid){object value;table.GetObject(item[0],out value);return (ISldWorks)value;}}finally{Marshal.ReleaseComObject(item[0]);}}return null;}
  finally{Marshal.ReleaseComObject(list);Marshal.ReleaseComObject(context);Marshal.ReleaseComObject(table);}}
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Set(object o,string n,object v){o.GetType().GetField(n).SetValue(o,v);}
 static object Call(object o,string n,params object[] a){return o.GetType().GetMethod(n).Invoke(o,a);}
 static object Create(Assembly code,string name,params object[] a){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+name),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,a,null);}
 static string Hash(string path){using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var hash=System.Security.Cryptography.SHA256.Create())return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-","").ToLowerInvariant();}
 static double[] Vec(object value){return ((IEnumerable)value).Cast<object>().Select(Convert.ToDouble).ToArray();}
 static double[] Sw(double[] v){return new[]{v[0],v[2],-v[1]};}
 static double[] Cross(double[] a,double[] b){return new[]{a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]};}
 static double[] Unit(double[] v){var length=Math.Sqrt(v.Sum(x=>x*x));return v.Select(x=>x/length).ToArray();}
 static void Save(ModelDoc2 doc,string path){int e=0,w=0;if(!doc.Extension.SaveAs(path,0,1,null,ref e,ref w))throw new Exception("CAD save failed "+path+" code="+e);}
 static double[] MakeShape(ISldWorks app,ModelDoc2 part,Dictionary<string,object> shape,bool create){
  var kind=(string)shape["kind"];double[] origin,x,y,z;double depth;
  if(kind=="tube" || kind=="cylinder"){
   var a=Sw(Vec(shape["a"]));var b=Sw(Vec(shape["b"]));origin=a;var delta=a.Zip(b,(aa,bb)=>bb-aa).ToArray();depth=Math.Sqrt(delta.Sum(v=>v*v));z=Unit(delta);
   x=Unit(Cross(Math.Abs(z[1])<.9?new[]{0.0,1.0,0.0}:new[]{1.0,0.0,0.0},z));y=Cross(z,x);
  }else{
   var center=Vec(shape["center"]);var size=Vec(shape["size"]);depth=size[2];origin=Sw(new[]{center[0],center[1],center[2]-depth/2});
   x=Sw(new[]{1.0,0.0,0.0});y=Sw(new[]{0.0,1.0,0.0});z=Sw(new[]{0.0,0.0,1.0});
  }
  var transform=x.Concat(y).Concat(z).Concat(origin).Concat(new[]{1.0,0.0,0.0,0.0}).ToArray();
  if(!create)return transform;
  if(!part.Extension.SelectByID2("Front Plane","PLANE",0,0,0,false,0,null,0))throw new Exception("Sketch plane unavailable");part.SketchManager.InsertSketch(true);
  if(kind=="tube" || kind=="cylinder"){
   var radius=Convert.ToDouble(shape["radius"]);part.SketchManager.CreateCircleByRadius(0,0,0,radius);
   if(kind=="tube")part.SketchManager.CreateCircleByRadius(0,0,0,radius-Convert.ToDouble(shape["wall"]));
  }else{var size=Vec(shape["size"]);part.SketchManager.CreateCornerRectangle(-size[0]/2,-size[1]/2,0,size[0]/2,size[1]/2,0);}
  var sketchName=((Feature)(Sketch)part.GetActiveSketch2()).Name;part.SketchManager.InsertSketch(true);
  if(kind=="sheet"){
   part.ClearSelection2(true);part.Extension.SelectByID2(sketchName,"SKETCH",0,0,0,false,1,null,0);
   if(!part.InsertPlanarRefSurface())throw new Exception("Sheet construction failed");
  }else if(part.FeatureManager.FeatureExtrusion2(true,false,false,0,0,depth,depth,false,false,false,false,0,0,false,false,false,false,false,true,true,0,0,false)==null)throw new Exception("Extrusion failed");
  return transform;
 }
 public static void Run(object application,string dll,string recipePath,string destination,string cacheDirectory){
  var app=(ISldWorks)application;app.UserControl=true;app.Visible=true;app.CommandInProgress=true;
  var json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};var recipe=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(recipePath));
  var cached=new Dictionary<string,Dictionary<string,object>>();var cachedHashes=new Dictionary<string,object>();
  if(!string.IsNullOrEmpty(cacheDirectory)){
   if(!File.Exists(Path.Combine(cacheDirectory,"native-capture.json")))throw new Exception("Cache is not a completed owned native fixture");
   var cache=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(cacheDirectory,"recipe.json")));
   var capture=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(cacheDirectory,"native-capture.json")));
   if(capture.ContainsKey("native_files_sha256"))cachedHashes=(Dictionary<string,object>)capture["native_files_sha256"];
   foreach(Dictionary<string,object> component in (IEnumerable)cache["components"])cached[(string)component["id"]]=component;
  }
  var code=Assembly.LoadFrom(dll);var db=((IEnumerable)app.GetMaterialDatabases()).Cast<string>().Single(p=>Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
  var assembly=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
  var assemblyPath=Path.Combine(destination,"SyntheticVehicle.SLDASM");Save(assembly,assemblyPath);
  var groups=new Dictionary<string,List<Component2>>();int total=0;
  foreach(Dictionary<string,object> component in (IEnumerable)recipe["components"]){
   var id=(string)component["id"];groups[id]=new List<Component2>();int index=0;
   foreach(Dictionary<string,object> shape in (IEnumerable)component["primitives"]){
    Console.WriteLine("Create "+id+" primitive "+index);
    var fileName=id+"_"+index+".SLDPRT";var path=Path.Combine(destination,fileName);bool reuse=false;
    Dictionary<string,object> previous;
    if(cached.TryGetValue(id,out previous) && Equals(previous["material"],component["material"])){
     var shapes=((IEnumerable)previous["primitives"]).Cast<object>().ToArray();reuse=index<shapes.Length && json.Serialize(shapes[index])==json.Serialize(shape) && cachedHashes.ContainsKey(fileName) && File.Exists(Path.Combine(cacheDirectory,fileName)) && Equals(cachedHashes[fileName],Hash(Path.Combine(cacheDirectory,fileName)));
    }
    ModelDoc2 part;int errors=0,warnings=0;
    if(reuse){File.Copy(Path.Combine(cacheDirectory,fileName),path);part=(ModelDoc2)app.OpenDoc6(path,1,1,"",ref errors,ref warnings);Console.WriteLine("Reused native primitive "+fileName);}
    else part=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
    if(part==null)throw new Exception("Native part unavailable "+fileName);
    var transform=MakeShape(app,part,shape,!reuse);if(!reuse){((PartDoc)part).SetMaterialPropertyName2("",db,(string)component["material"]);Save(part,path);}
    index++;app.ActivateDoc3(assembly.GetTitle(),false,0,ref errors);
    var instance=((AssemblyDoc)assembly).AddComponent5(path,0,"",false,"",0,0,0);if(instance==null)throw new Exception("Assembly insertion failed "+id);
    instance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(transform);groups[id].Add(instance);total++;
    app.CloseDoc(part.GetTitle());Marshal.ReleaseComObject(part);Application.DoEvents();
   }
   Save(assembly,assemblyPath);Console.WriteLine("CAD group "+id+": "+groups[id].Count+" bodies");Application.DoEvents();
  }
  Save(assembly,assemblyPath);assembly.ViewZoomtofit2();
  var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var project=projectType.GetMethod("Open").Invoke(null,new object[]{assemblyPath});
  var selection=Create(code,"Preparation.FrameSelection",app,assembly,true);var componentList=(IList)Get(project,"Components");
  foreach(Dictionary<string,object> item in (IEnumerable)recipe["components"]){
   var id=(string)item["id"];assembly.ClearSelection2(true);bool append=false;
   foreach(var instance in groups[id]){if(!instance.Select4(append,null,false))throw new Exception("Cannot select "+id);append=true;}
   var assignment=Call(selection,"Capture");var component=Create(code,"Preparation.ComponentDefinition");
   if(id=="frame" && item.ContainsKey("hull_symmetry"))Set(Get(assignment,"Hull"),"Symmetry",Convert.ToBoolean(item["hull_symmetry"]));
   Set(component,"Id",id);Set(component,"Name","Synthetic "+id);Set(component,"MvpRole",id.StartsWith("panel_")?"panel":item.ContainsKey("role")?(string)item["role"]:id);
   Set(component,"Template",id=="frame"?"calibrated_frame":id.StartsWith("panel_")?"panel":"bulk");
   Set(component,"Hull",Get(assignment,"Hull"));
   Set(component,"Configuration",Get(assignment,"Configuration"));Set(component,"Selections",Get(assignment,"Selections"));Set(component,"BodyIds",Call(selection,"BodyIds",assignment));
   Set(component,"Thickness",Convert.ToDouble(item["thickness"]));Set(component,"SurfaceMassMode",item["surface_mass_mode"]);
   if(item.ContainsKey("visual_parent")){Set(component,"VisualParentId",item["visual_parent"]);Set(component,"Representation","visual_only");Set(component,"MassPolicy","exclude");Console.WriteLine("Explicit zero-mass visual fixture: "+id+"; acknowledge excluded mass before packaging.");}
   var folder=Path.Combine(destination,"cad-inputs",id);Call(selection,"Export",assignment,folder);Set(component,"GeometryDirectory",folder);componentList.Add(component);
   Console.WriteLine("Production CAD export "+id);Application.DoEvents();
  }
  foreach(var pair in (Dictionary<string,object>)recipe["templates"]){var choice=Create(code,"Preparation.MvpTemplateChoice");Set(choice,"Category",pair.Key);Set(choice,"Template",pair.Value);((IList)Get(project,"MvpTemplates")).Add(choice);}
  Call(project,"Save");File.Copy(recipePath,Path.Combine(destination,"recipe.json"));
  app.CommandInProgress=false;assembly.ClearSelection2(true);assembly.ShowNamedView2("*Isometric",7);assembly.ViewZoomtofit2();
  assembly.GraphicsRedraw2();Application.DoEvents();
  var screenshot=Path.Combine(destination,"native-viewport.bmp");
  if(!assembly.SaveBMP(screenshot,0,0))throw new Exception("Native viewport capture failed");
  using(var bitmap=new System.Drawing.Bitmap(screenshot))bitmap.Save(Path.Combine(destination,"native-viewport.png"),System.Drawing.Imaging.ImageFormat.Png);
  File.Delete(screenshot);
  File.WriteAllText(Path.Combine(destination,"native-capture.json"),json.Serialize(new{assembly=assemblyPath,project=assemblyPath+".beamng-project.json",bodies=total,material_database=db,recipe_sha256=recipe["recipe_sha256"],native_files_sha256=Directory.GetFiles(destination,"*.SLDPRT").Where(p=>!Path.GetFileName(p).StartsWith("~$")).Concat(new[]{assemblyPath}).ToDictionary(Path.GetFileName,Hash)}));
 }
 public static void Capture(object application,string assemblyPath,string destination){
  var app=(ISldWorks)application;int errors=0,warnings=0;
  app.UserControl=true;app.Visible=true;app.CommandInProgress=false;
  // Assemblies with the same file name cannot coexist in one SW process.
  // This instance owns only the synthetic documents created above.
  var active=(ModelDoc2)app.ActiveDoc;if(active!=null)app.CloseDoc(active.GetTitle());
  var doc=(ModelDoc2)app.OpenDoc6(assemblyPath,2,3,"",ref errors,ref warnings);
  if(doc==null)throw new Exception("Read-only fixture capture could not open assembly: "+errors);
  app.ActivateDoc3(doc.GetTitle(),false,0,ref errors);doc.ClearSelection2(true);doc.ShowNamedView2("*Isometric",7);doc.ViewZoomtofit2();doc.GraphicsRedraw2();Application.DoEvents();
  var temporary=destination+".bmp";if(!doc.SaveBMP(temporary,0,0))throw new Exception("Fixture viewport capture failed");
  using(var bitmap=new System.Drawing.Bitmap(temporary))bitmap.Save(destination,System.Drawing.Imaging.ImageFormat.Png);
  File.Delete(temporary);app.CloseDoc(doc.GetTitle());
 }
 public static void Finish(object app){if(promptGuard!=null)promptGuard.Dispose();var native=(ISldWorks)app;native.CommandInProgress=false;if(!native.CloseAllDocuments(true))throw new Exception("Owned CAD documents did not close");Application.DoEvents();native.ExitApp();}
}
'@
Add-Type -ReferencedAssemblies $refs -TypeDefinition $source
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
$ownedPid=$null
try {
 $process=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS\sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
 $ownedPid=$process.Id
 if($existing -contains $ownedPid){throw 'Refusing existing native user process'}
 $until=(Get-Date).AddSeconds(120)
 do {$app=[SyntheticNativeCad]::Find($ownedPid);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and (Get-Date) -lt $until)
 if(-not $app){throw 'Owned SolidWorks instance did not register'}
 Write-Output "OWNED_CAD_PROCESS=$ownedPid DESTINATION=$Destination"
 [SyntheticNativeCad]::GuardOwnedPrompt($ownedPid)
 if(-not $CaptureExistingOnly){[SyntheticNativeCad]::Run($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Recipe,$Destination,$ReuseCad)}
 if($CaptureAssembly){[SyntheticNativeCad]::Capture($app,(Resolve-Path -LiteralPath $CaptureAssembly).Path,(Join-Path $Destination 'baseline-native-viewport.png'))}
} finally {
 if($ownedPid -and $existing -notcontains $ownedPid){
  if($app){[SyntheticNativeCad]::Finish($app)}else{Stop-Process -Id $ownedPid -ErrorAction SilentlyContinue}
 }
}
