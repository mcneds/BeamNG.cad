param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\vehicle-system'),[switch]$SurfaceCases,[string]$PythonExecutable)
$ErrorActionPreference='Stop'
if(-not $PythonExecutable){$PythonExecutable=(Get-Command python.exe -CommandType Application | Select-Object -First 1).Source}
$PythonExecutable=(Resolve-Path -LiteralPath $PythonExecutable).Path
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$root=Join-Path $OutputDirectory ('native-components-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
$refs=@('System.Core','System.Windows.Forms','System.Drawing',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[3..4]){[void][Reflection.Assembly]::LoadFrom($ref)}
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
using System.Runtime.InteropServices.ComTypes;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class ComponentNativeTest {
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out IBindCtx context);
 public static ISldWorks Find(int pid){
  IRunningObjectTable table;IBindCtx context;GetRunningObjectTable(0,out table);CreateBindCtx(0,out context);
  IEnumMoniker list;table.EnumRunning(out list);var item=new IMoniker[1];
  try{while(list.Next(1,item,IntPtr.Zero)==0){try{string name;item[0].GetDisplayName(context,null,out name);if(name=="SolidWorks_PID_"+pid){object value;table.GetObject(item[0],out value);return (ISldWorks)value;}}finally{Marshal.ReleaseComObject(item[0]);}}return null;}
  finally{Marshal.ReleaseComObject(list);Marshal.ReleaseComObject(context);Marshal.ReleaseComObject(table);}
 }
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Set(object o,string n,object v){o.GetType().GetField(n).SetValue(o,v);}
 static object Call(object o,string n,params object[] a){return o.GetType().GetMethod(n).Invoke(o,a);}
 static object Create(Assembly code,string name,params object[] a){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+name),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,a,null);}
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine("PASS "+label);}
 static void Near(double[] actual,double[] expected,string label){Check(actual.Length==expected.Length && actual.Zip(expected,(a,b)=>Math.Abs(a-b)).Max()<1e-8,label+" actual="+string.Join(",",actual));}
 static void Extrude(ModelDoc2 part,double x,bool circle){
  part.ClearSelection2(true);Check(part.Extension.SelectByID2("Front Plane","PLANE",0,0,0,false,0,null,0),"fixture sketch plane");
  part.SketchManager.InsertSketch(true);
  if(circle)part.SketchManager.CreateCircleByRadius(x,.05,0,.04);
  else part.SketchManager.CreateCornerRectangle(x,0,0,x+.1,.1,0);
  part.SketchManager.InsertSketch(true);
  Check(part.FeatureManager.FeatureExtrusion2(true,false,false,0,0,.1,.1,false,false,false,false,0,0,false,false,false,false,false,true,true,0,0,false)!=null,"fixture solid extrusion");
 }
 static double[] Expected(ISldWorks app,Component2 c,double[] local,double[] offset){
  var point=(MathPoint)((MathUtility)app.GetMathUtility()).CreatePoint(local.Zip(offset,(a,b)=>a+b).ToArray());
  point=(MathPoint)point.MultiplyTransform(c.Transform2);var p=(double[])point.ArrayData;return new[]{p[0],-p[2],p[1]};
 }
 static void Sheet(ModelDoc2 part){
  part.ClearSelection2(true);Check(part.Extension.SelectByID2("Front Plane","PLANE",0,0,0,false,0,null,0),"sheet plane");
  part.SketchManager.InsertSketch(true);part.SketchManager.CreateCornerRectangle(.5,0,0,.9,.3,0);
  var sketch=(Sketch)part.GetActiveSketch2();var name=((Feature)sketch).Name;
  part.SketchManager.InsertSketch(true);part.ClearSelection2(true);
  Check(part.Extension.SelectByID2(name,"SKETCH",0,0,0,false,1,null,0),"sheet boundary");
  Check(part.InsertPlanarRefSurface(),"native planar sheet");
 }
 static void Role(Form form,string id){var combo=(ComboBox)Find(form,"MvpRole");combo.SelectedItem=combo.Items.Cast<object>().Single(r=>(string)Get(r,"Id")==id);}
 static void Select(ModelDoc2 model,object value,bool append=false){if(!append)model.ClearSelection2(true);Check(value is Body2?((Body2)value).Select2(append,null):((Entity)value).Select4(append,null),"fixture entity selection");}
 static Body2[] Bodies(Component2 c){object info;return ((object[])c.GetBodies3(0,out info)).Cast<Body2>().ToArray();}
 static void Click(Form form,string text){
  var busy=form.GetType().GetField("cancel",BindingFlags.NonPublic|BindingFlags.Instance);
  var until=DateTime.UtcNow.AddSeconds(60);
  while(busy.GetValue(form)!=null && DateTime.UtcNow<until){Application.DoEvents();Thread.Sleep(10);}
  Check(busy.GetValue(form)==null,"UI idle before "+text);
  var button=Find(form,text) as Button;Check(button!=null,"UI button "+text);
  for(Control parent=button.Parent;parent!=null;parent=parent.Parent)if(parent is TabPage)((TabControl)parent.Parent).SelectedTab=(TabPage)parent;
  Application.DoEvents();Check(button.Enabled,"UI action enabled: "+text);button.PerformClick();
  until=DateTime.UtcNow.AddSeconds(60);
  while(busy.GetValue(form)!=null && DateTime.UtcNow<until){Application.DoEvents();Thread.Sleep(10);}
  Check(busy.GetValue(form)==null,"UI operation returned: "+text);
 }
 static Control Find(Control parent,string text){foreach(Control c in parent.Controls){if(c.Text==text || c.Name==text)return c;var child=Find(c,text);if(child!=null)return child;}return null;}
 static async Task ObserveIdentity(ISldWorks app,ModelDoc2 model){
  await Task.Delay(10);var active=app.ActiveDoc;
  Console.WriteLine("After UI yield: managed equality="+ReferenceEquals(active,model)+", native equality="+app.IsSame(active,model)+", apartment="+Thread.CurrentThread.GetApartmentState());
 }
 public static void Run(object appValue,string dll,string folder,bool surfaces,string python){
  var app=(ISldWorks)appValue;
  using(var writer=new StreamWriter(Path.Combine(folder,"native-tests.log"))){writer.AutoFlush=true;var old=Console.Out;Console.SetOut(writer);
   try{
    SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
    var code=Assembly.LoadFrom(dll);app.UserControl=true;app.Visible=true;Control.CheckForIllegalCrossThreadCalls=true;
    Console.WriteLine("Native fixture thread apartment="+Thread.CurrentThread.GetApartmentState());
    var part=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
    Check(part!=null,"new disposable part");Extrude(part,0,false);Extrude(part,.25,true);if(surfaces)Sheet(part);
    var db=((IEnumerable)app.GetMaterialDatabases()).Cast<string>().Single(p=>Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
    ((PartDoc)part).SetMaterialPropertyName2("",db,"AISI 4130 Steel, annealed at 865C");
    int errors=0,warnings=0;var partPath=Path.Combine(folder,"anchors.SLDPRT");
    Check(part.Extension.SaveAs(partPath,0,1,null,ref errors,ref warnings),"fixture part saved");
    var model=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
    var c=((AssemblyDoc)model).AddComponent5(partPath,0,"",false,"",0,0,0);Check(c!=null,"fixture inserted");
    var transform=new double[]{0,1,0,-1,0,0,0,0,1,.4,.6,.8,1,0,0,0};c.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(transform);
    var assemblyPath=Path.Combine(folder,"anchors.SLDASM");Check(model.Extension.SaveAs(assemblyPath,0,1,null,ref errors,ref warnings),"fixture assembly saved");
    var selection=surfaces?Create(code,"Preparation.FrameSelection",app,model,true):Create(code,"Preparation.FrameSelection",app,model);Check(c.Select4(false,null,false),"whole fixture selected");
    var assignment=Call(selection,"Capture");var owner=Create(code,"Preparation.ComponentDefinition");
    Set(owner,"Selections",Get(assignment,"Selections"));Set(owner,"Configuration",Get(assignment,"Configuration"));Set(owner,"BodyIds",Call(selection,"BodyIds",assignment));
    var service=Create(code,"Preparation.MountAnchors",app,model);var bodies=Bodies(c);Check(bodies.Length==2,"two independently owned solid bodies");
    var block=bodies.First(b=>((object[])b.GetVertices()).Length==8);var vertices=((object[])block.GetVertices()).Cast<Vertex>().ToArray();
    Select(model,vertices[0]);var anchor=Call(service,"Capture",owner,"Vertex");var local=(double[])vertices[0].GetPoint();
    Near((double[])Get(anchor,"Position"),Expected(app,c,local,new double[3]),"assembly rotation and axis mapping once");
    var offset=new[]{.01,-.02,.03};Set(anchor,"Offset",offset);Call(service,"Update",anchor);
    Near((double[])Get(anchor,"Position"),Expected(app,c,local,offset),"component-local offsets follow rotation");
    transform[9]=.8;transform[10]=.3;c.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(transform);Call(service,"Update",anchor);
    Near((double[])Get(anchor,"Position"),Expected(app,c,local,offset),"persistent mount follows moved CAD component");
    Select(model,vertices[0]);Select(model,vertices[1],true);var midpoint=Call(service,"Capture",owner,"Midpoint");
    var p1=(double[])vertices[0].GetPoint();var p2=(double[])vertices[1].GetPoint();Near((double[])Get(midpoint,"Position"),Expected(app,c,p1.Zip(p2,(a,b)=>(a+b)/2).ToArray(),new double[3]),"two-point midpoint");
    var cylinder=bodies.First(b=>b.Name!=block.Name);var edge=((object[])cylinder.GetEdges()).Cast<Edge>().First(e=>((Curve)e.GetCurve()).IsCircle());
    Select(model,edge);var circle=Call(service,"Capture",owner,"Hole center");var center=((double[])((Curve)edge.GetCurve()).CircleParams).Take(3).ToArray();
    Near((double[])Get(circle,"Position"),Expected(app,c,center,new double[3]),"circular edge center");
    Select(model,block);var blockAssignment=Call(selection,"Capture");var blockOwner=Create(code,"Preparation.ComponentDefinition");Set(blockOwner,"Selections",Get(blockAssignment,"Selections"));Set(blockOwner,"BodyIds",Call(selection,"BodyIds",blockAssignment));
    Select(model,edge);bool rejected=false;try{Call(service,"Capture",blockOwner,"Wrong body");}catch(TargetInvocationException e){rejected=e.InnerException.Message.Contains("outside");}Check(rejected,"mount on different body in same part rejected");
    ((IList)Get(anchor,"References"))[0]=Convert.ToBase64String(new byte[]{1,2,3});rejected=false;try{Call(service,"Update",anchor);}catch(TargetInvocationException){rejected=true;}Check(rejected && (string)Get(anchor,"Status")=="needs_repair","missing persistent reference requires repair");
    var settings=Create(code,"UI.ExporterSettings",Path.Combine(folder,"settings.xml"));
    settings.GetType().GetProperty("FrameOutput").SetValue(settings,Path.Combine(folder,"builds"),null);
    settings.GetType().GetProperty("CalibrationPythonExecutable").SetValue(settings,python,null);Call(settings,"Save");
    Check(c.Select4(false,null,false),"fixture reselected for component UI");
    Body2 sheet=null;
    if(surfaces){
     object bodyInfo;sheet=((object[])c.GetBodies3(1,out bodyInfo)).Cast<Body2>().Single();
     Check(((IList)Call(selection,"BodyIds",assignment)).Count==3,"whole component includes sheet and solids");
     Select(model,((object[])sheet.GetEdges())[0]);var all=Call(selection,"CaptureOwningComponents");
     Check(((IList)Call(selection,"BodyIds",all)).Count==3,"explicit owning component from edge");
     Select(model,((object[])sheet.GetFaces())[0]);var faceAssignment=Call(selection,"Capture");
     Check(((IList)Call(selection,"BodyIds",faceAssignment)).Count==1,"surface face captures entire sheet body");
     var solidSelection=Create(code,"Preparation.FrameSelection",app,model);rejected=false;
     try{Call(solidSelection,"Capture");}catch(TargetInvocationException){rejected=true;}Check(rejected,"frame keeps its solid-body requirement");
     Select(model,block);
    }
    using(var form=(Form)Create(code,"UI.ComponentWorkflow",app,model,settings)){
     form.Show();Application.DoEvents();var identity=ObserveIdentity(app,model);while(!identity.IsCompleted){Application.DoEvents();Thread.Sleep(10);}identity.GetAwaiter().GetResult();
     ((ComboBox)form.GetType().GetField("template",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form)).SelectedItem="bulk";
     Click(form,"Set to selected");
     var list=(ListBox)form.Controls.Find("Components",true).Single();Check(list.Items.Count==1,"component UI saves ownership");
     var component=list.Items[0];var active=app.ActiveDoc as ModelDoc2;
     Check(Directory.Exists((string)Get(component,"GeometryDirectory")),"component UI exports native geometry (active="+(active==null?"none":active.GetPathName())+"): "+form.Controls.Find("ComponentLog",true).Single().Text);
     Check(Find(form,"ComponentStatus").Text.IndexOf("outside",StringComparison.OrdinalIgnoreCase)<0,"component UI completed without ownership error");
     var firstGeometry=(string)Get(component,"GeometryDirectory");
     ((ComboBox)form.GetType().GetField("method",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form)).SelectedItem="convex";
     ((ComboBox)form.GetType().GetField("template",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form)).SelectedItem="bulk";
     Click(form,"Generate / preview");
     Check(((IDictionary)form.GetType().GetField("previews",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form)).Count==1,"native component preview created: "+form.Controls.Find("ComponentLog",true).Single().Text);
     var secondGeometry=(string)Get(component,"GeometryDirectory");
     Check(firstGeometry!=secondGeometry && Directory.GetFiles(firstGeometry).All(p=>File.ReadAllBytes(p).SequenceEqual(File.ReadAllBytes(Path.Combine(secondGeometry,Path.GetFileName(p))))),"fresh CAD exports have identical input contents");
     Check(!form.Controls.OfType<ProgressBar>().Single().Visible,"progress stops after completed preview");
     if(surfaces){
      Role(form,"engine");Click(form,"Save parameters");Check((string)Get(component,"MvpRole")=="engine","existing assignment tagged");
      Role(form,"panel");Click(form,"New tagged group");
      ((NumericUpDown)Find(form,"SurfaceThickness")).Value=2;
      Select(model,((object[])sheet.GetFaces())[0]);Click(form,"Set to selected");
      Check(list.Items.Count==2,"surface assignment created");var skin=list.SelectedItem;
      Check((double)Get(skin,"Thickness")==.002 && (string)Get(skin,"MvpRole")=="panel","new group preserves thickness and role");
      Click(form,"Generate / preview");
      Check(((IDictionary)form.GetType().GetField("previews",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form)).Count==2,"weighted sheet preview: "+Find(form,"ComponentLog").Text);
      Check(Find(form,"ComponentStatus").Text.Contains("Mass fitted"),"surface material mass fitted");
      ((ComboBox)Find(form,"SurfaceMassMode")).SelectedIndex=1;
      var parents=(ComboBox)Find(form,"VisualParent");parents.SelectedIndex=1;
      Click(form,"Generate / preview");Check(Find(form,"ComponentStatus").Text.Contains("zero added mass"),"weightless sheet preview");
      Click(form,"Refresh tagged CAD");
      Check(File.Exists(assemblyPath+".beamng-project.json.inventory.json"),"reusable CAD inventory written");
      Check(Find(form,"MvpChecklist").Text.Contains("TAGGED | Engine") && Find(form,"MvpChecklist").Text.Contains("MISSING | CVT"),"MVP coverage separates tagged from missing groups");
      list.SelectedItem=component;Role(form,"rl_trailing_arm");Click(form,"Save parameters");
      var rear=(ComboBox)Find(form,"MvpTemplate_rear_suspension");rear.SelectedIndex=1;Click(form,"Apply vehicle setup");
      Check(Find(form,"MvpChecklist").Text.Contains("MISSING | RL upper wishbone") && Find(form,"MvpChecklist").Text.Contains("OUTSIDE CURRENT SETUP"),"rear template changes requirements and retains existing tags");
      rear.SelectedIndex=0;Click(form,"Apply vehicle setup");Check(Find(form,"MvpChecklist").Text.Contains("TAGGED | RL trailing arm"),"switching back restores original grouped selection");
      Role(form,"engine");Click(form,"Save parameters");Click(form,"Refresh tagged CAD");
      var projectText=File.ReadAllText(assemblyPath+".beamng-project.json");Check(projectText.Contains("MvpRole") && projectText.Contains("panel"),"role tags persisted with native references");
     }
     form.Close();Application.DoEvents();Check(form.IsDisposed,"component UI closes safely");
    }
    app.ActivateDoc3(partPath,false,0,ref errors);rejected=false;
    try{Call(selection,"ValidateDocument");}catch(TargetInvocationException){rejected=true;}
    Check(rejected,"different active document is still rejected");
    File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS");
   }catch(Exception e){Console.WriteLine(e);File.WriteAllText(Path.Combine(folder,"result.txt"),e.ToString());}
   finally{Console.SetOut(old);}
  }
 }
 public static void Finish(object app){((ISldWorks)app).ExitApp();}
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
    do {$app=[ComponentNativeTest]::Find($ownedPid);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and (Get-Date) -lt $until)
    if(-not $app){throw 'Owned SolidWorks instance did not register'}
    Write-Output "TEST_PROCESS=$ownedPid EVIDENCE=$root"
    [ComponentNativeTest]::Run($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$root,[bool]$SurfaceCases,$PythonExecutable)
    Get-Content -LiteralPath (Join-Path $root 'native-tests.log')
    if((Get-Content -LiteralPath (Join-Path $root 'result.txt') -Raw) -ne 'PASS'){throw 'Native component tests failed'}
} finally {
    if($ownedPid){
        if(Test-Path -LiteralPath (Join-Path $root 'result.txt')){[ComponentNativeTest]::Finish($app)}
        else{Stop-Process -Id $ownedPid -ErrorAction SilentlyContinue}
    }
}
