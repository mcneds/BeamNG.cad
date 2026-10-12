param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\bulk-material'),[switch]$TestPicker,[switch]$PickerOnly,[string]$FixtureDirectory,[string]$Gate,[switch]$CompileOnly)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$root=if($FixtureDirectory){(Resolve-Path -LiteralPath $FixtureDirectory).Path}else{Join-Path $OutputDirectory ('bulk-material-test-'+[Guid]::NewGuid().ToString('N'))}
[void][IO.Directory]::CreateDirectory($root)
$refs=@('System.Core','System.Windows.Forms','System.Drawing',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$refs+=[System.Windows.Automation.AutomationElement].Assembly.Location
$refs+=[System.Windows.Automation.ControlType].Assembly.Location
foreach($file in @('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll')){[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory $file))}
$source=@'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class BulkMaterialsSmoke {
 static ISldWorks currentApp;
 static bool isolated;
 delegate bool WindowCallback(IntPtr window,IntPtr data);
 [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback,IntPtr data);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window,StringBuilder text,int length);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
 [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window,int message,IntPtr wparam,IntPtr lparam);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window,int command);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern IntPtr GetProp(IntPtr window,string name);
 static void Check(bool ok,string message){if(!ok)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static void Box(ModelDoc2 part,double x){
  part.ClearSelection2(true);Check(part.Extension.SelectByID2("Front Plane","PLANE",0,0,0,false,0,null,0),"sketch plane");
  part.SketchManager.InsertSketch(true);part.SketchManager.CreateCornerRectangle(x,0,0,x+.1,.1,0);part.SketchManager.InsertSketch(true);
  Check(part.FeatureManager.FeatureExtrusion2(true,false,false,0,0,.1,.1,false,false,false,false,0,0,false,false,false,false,false,true,true,0,0,false)!=null,"fixture body");
 }
 static void Save(ModelDoc2 doc,string path){int e=0,w=0;Check(doc.Extension.SaveAs(path,0,1,null,ref e,ref w),"fixture saved");}
 static void Activate(ISldWorks app,ModelDoc2 doc){int e=0;Check(app.ActivateDoc3(doc.GetTitle(),false,0,ref e)!=null,"activate fixture");}
 static string Material(Body2 body,string config){string db;return body.GetMaterialPropertyName(config,out db);}
 static object Invoke(object instance,string method,params object[] args){return instance.GetType().GetMethod(method).Invoke(instance,args);}
 static object Apply(object service,object choice,Action<int,int,string> progress,CancellationToken token){
  var app=currentApp;var doc=(ModelDoc2)app.ActiveDoc;
  var frame=new IntPtr(((Frame)app.Frame()).GetHWndx64());
  // Fixture construction can hide a newly launched frame while closing its
  // source part. A material button is normally invoked from a visible GUI.
  if(isolated)ShowWindow(frame,5);
  var visible=IsWindowVisible(frame);var redraw=GetProp(frame,"SysSetRedraw");var command=app.CommandInProgress;
  var oldTree=doc.FeatureManager.EnableFeatureTree;var oldTreeWindow=doc.FeatureManager.EnableFeatureTreeWindow;var oldGraphics=((ModelView)doc.ActiveView).EnableGraphicsUpdate;
  Action<int,int,string> checkedProgress=(done,total,label)=>{
   Check(GetProp(frame,"SysSetRedraw")!=IntPtr.Zero,"automated assignment holds frame redraw (initial visible="+visible+", redraw="+redraw+")");
   var active=(ModelDoc2)app.ActiveDoc;
   var tree=active.FeatureManager.EnableFeatureTree;var treeWindow=active.FeatureManager.EnableFeatureTreeWindow;var graphics=((ModelView)active.ActiveView).EnableGraphicsUpdate;
   Check(!tree && !treeWindow && !graphics,"part updates paused (tree="+tree+", window="+treeWindow+", graphics="+graphics+")");
   Check(Application.OpenForms.Cast<Form>().Any(f=>f.Text=="beamng.cad material update" && IsWindowVisible(f.Handle)),"workspace cover hides native document transitions");
   if(progress!=null)progress(done,total,label);
  };
  var task=(Task)Invoke(service,"ApplyAsync",choice,checkedProgress,token);
  while(!task.IsCompleted){Application.DoEvents();Thread.Sleep(5);}
  task.GetAwaiter().GetResult();
  var appliedResult=task.GetType().GetProperty("Result").GetValue(task,null);
  Console.WriteLine("UI_RESTORE_RESULT="+appliedResult.GetType().GetProperty("Summary").GetValue(appliedResult,null));
  foreach(var detail in (IEnumerable)Field(appliedResult,"Diagnostics"))Console.WriteLine(detail);
  Check(IsWindowVisible(frame)==visible && GetProp(frame,"SysSetRedraw")==redraw && app.CommandInProgress==command,"frame visibility, redraw and command state restored (visible="+visible+"/"+IsWindowVisible(frame)+", redraw="+redraw+"/"+GetProp(frame,"SysSetRedraw")+", command="+command+"/"+app.CommandInProgress+")");
  Check(app.ActiveDoc==doc && doc.FeatureManager.EnableFeatureTree==oldTree && doc.FeatureManager.EnableFeatureTreeWindow==oldTreeWindow && ((ModelView)doc.ActiveView).EnableGraphicsUpdate==oldGraphics,
   "assembly display restored (active="+(app.ActiveDoc==doc)+", tree="+oldTree+"/"+doc.FeatureManager.EnableFeatureTree+", window="+oldTreeWindow+"/"+doc.FeatureManager.EnableFeatureTreeWindow+", graphics="+oldGraphics+"/"+((ModelView)doc.ActiveView).EnableGraphicsUpdate+")");
  Check(!Application.OpenForms.Cast<Form>().Any(f=>f.Text=="beamng.cad material update"),"workspace cover removed after assignment or failure");
  return appliedResult;
 }
 static object Field(object o,string name){return o.GetType().GetField(name).GetValue(o);}
 static string Ref(ModelDoc2 doc,object item){return Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(item));}
 static object Resolve(ModelDoc2 doc,string reference){int error;var item=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out error);Check(item!=null && error==0,"persistent fixture reference resolves");return item;}
 static void Normalization(object selection,ModelDoc2 assembly,Component2 component,Component2 duplicate,Component2 unrelated){
  object info;var bodies=((object[])component.GetBodies3(0,out info)).Cast<Body2>().ToArray();
  assembly.ClearSelection2(true);
  var faces=((object[])bodies[0].GetFaces()).Cast<Face2>().Take(2).ToArray();
  Check(((Entity)faces[0]).Select4(false,null) && ((Entity)faces[1]).Select4(true,null) && bodies[0].Select2(true,null),"overlapping faces and body selected");
  var captured=Invoke(selection,"Capture");
  Check(((IList)Field(captured,"Selections")).Count==1 && ((IList)Invoke(selection,"MaterialBodies",captured)).Count==1,"faces select exactly their owning body and overlaps deduplicate");
  var faceReference=Ref(assembly,faces[0]);
  Feature folder=null;
  for(var feature=component.FirstFeature() as Feature;feature!=null;feature=feature.GetNextFeature() as Feature)
   if(feature.GetTypeName2()=="SolidBodyFolder"){folder=feature;break;}
  Check(folder!=null && folder.Select2(false,0),"component body folder selected");
  Check(((Entity)faces[0]).Select4(true,null),"overlapping face added to folder");
  captured=Invoke(selection,"Capture");
  Check(((IList)Field(captured,"Selections")).Count==3 && ((IList)Invoke(selection,"MaterialBodies",captured)).Count==3,"body folder retains its three bodies without duplicate face");
  // Component references survive loading state changes; the face reference must
  // also survive so a lightweight pick cannot silently expand to the whole part.
  component.Select4(false,null,false);var componentFrame=Invoke(selection,"Capture");
  var reference=Ref(assembly,component);var otherReference=Ref(assembly,unrelated);
  assembly.ClearSelection2(true);
  var loadingResult=component.SetSuppression2(1);component=(Component2)Resolve(assembly,reference);
  Check(component.GetSuppression2()==1 || component.GetSuppression2()==4,"fixture is genuinely lightweight (native result "+loadingResult+", state "+component.GetSuppression2()+")");
  bool rejected=false;try{Invoke(selection,"ReadMaterials",componentFrame);}catch(TargetInvocationException e){rejected=e.InnerException.Message.Contains("lightweight (not suppressed)");}
  Check(rejected && (component.GetSuppression2()==1 || component.GetSuppression2()==4),"material refresh leaves lightweight component untouched and labels it accurately");
  unrelated=(Component2)Resolve(assembly,otherReference);unrelated.SetSuppression2(1);unrelated=(Component2)Resolve(assembly,otherReference);var otherState=unrelated.GetSuppression2();
  Check(otherState==1 || otherState==4,"unrelated control component is lightweight");
  Check(((Entity)Resolve(assembly,faceReference)).Select4(false,null),"lightweight face selected");
  captured=Invoke(selection,"Capture");
  Check(((SelectionMgr)assembly.SelectionManager).GetSelectedObjectCount2(-1)==1,"loading preserves the original face selection");
  Check(((IList)Field(captured,"Selections")).Count==1 && ((IList)Invoke(selection,"MaterialBodies",captured)).Count==1,"lightweight face resolves to only its original body");
  component=(Component2)Resolve(assembly,reference);unrelated=(Component2)Resolve(assembly,otherReference);
  Check(component.GetSuppression2()==2 || component.GetSuppression2()==3,"selected lightweight component resolved");
  Check(unrelated.GetSuppression2()==otherState,"unrelated component loading state preserved");
  assembly.ClearSelection2(true);component.SetSuppression2(0);
  rejected=false;try{Invoke(selection,"MaterialBodies",componentFrame);}catch(TargetInvocationException e){rejected=e.InnerException.Message.Contains("genuinely suppressed");}
  Check(rejected && component.GetSuppression2()==0,"explicitly suppressed target rejected without unsuppressing");
  component.SetSuppression2(3);assembly.ClearSelection2(true);
 }
 static AutomationElement Find(AutomationElement root,string name,ControlType type){
  var deadline=DateTime.UtcNow.AddSeconds(12);
  do{
   var item=root.FindAll(TreeScope.Descendants,Condition.TrueCondition).Cast<AutomationElement>().FirstOrDefault(e=>e.Current.Name==name && e.Current.ControlType==type);
   if(item!=null)return item;Thread.Sleep(200);
  }while(DateTime.UtcNow<deadline);
  throw new Exception("Native picker control missing: "+name);
 }
 static void Expand(AutomationElement item){var pattern=(ExpandCollapsePattern)item.GetCurrentPattern(ExpandCollapsePattern.Pattern);if(pattern.Current.ExpandCollapseState==ExpandCollapseState.Collapsed)pattern.Expand();}
 static void Workflow(Assembly code,ISldWorks app,ModelDoc2 assembly,object selection){
  var stale=Invoke(selection,"Capture");
  var first=((IList)Field(stale,"Selections"))[0];first.GetType().GetField("Reference").SetValue(first,"invalid saved reference");
  var type=code.GetType("BeamNG.Cad.UI.FrameWorkflow");
  using(var form=(Form)Activator.CreateInstance(type,app,assembly)){
   var handle=form.Handle;var flags=BindingFlags.Instance|BindingFlags.NonPublic;
   type.GetField("frame",flags).SetValue(form,stale);
   type.GetField("generation",flags).SetValue(form,"stale-generation-sentinel");
   var pid=app.GetProcessID();var closed=0;Exception automationError=null;
   using(var closer=new System.Threading.Timer(state=>EnumWindows((window,data)=>{
    uint owner;GetWindowThreadProcessId(window,out owner);var title=new StringBuilder(512);GetWindowText(window,title,512);
    if(owner==pid && title.ToString()=="Material" && IsWindowVisible(window) && Interlocked.CompareExchange(ref closed,1,0)==0){
     try{
      Check(IsWindowVisible(window),"native picker remains visible");
      var dialog=AutomationElement.FromHandle(window);
      Expand(Find(dialog,"SOLIDWORKS Materials",ControlType.TreeItem));Expand(Find(dialog,"Steel",ControlType.TreeItem));
      ((SelectionItemPattern)Find(dialog,"Alloy Steel",ControlType.TreeItem).GetCurrentPattern(SelectionItemPattern.Pattern)).Select();
      ((InvokePattern)Find(dialog,"Apply",ControlType.Button).GetCurrentPattern(InvokePattern.Pattern)).Invoke();
     }catch(Exception e){automationError=e;}
     finally{try{ClosePicker(window,false);}catch(Exception e){automationError=automationError??e;PostMessage(window,0x10,IntPtr.Zero,IntPtr.Zero);}}
    }return true;
   },IntPtr.Zero),null,2000,1000)){
    type.GetMethod("SetMaterials",flags).Invoke(form,new object[]{false});
    var deadline=DateTime.UtcNow.AddSeconds(60);
    while(type.GetField("cancellation",flags).GetValue(form)!=null && DateTime.UtcNow<deadline){Application.DoEvents();Thread.Sleep(10);}
    if(automationError!=null)throw automationError;
    Check(closed==1,"valid current selection opens native picker despite invalid saved frame");
    Check(type.GetField("cancellation",flags).GetValue(form)==null,"material workflow finishes and clears busy state");
    Check((string)type.GetField("taskResult",flags).GetValue(form)=="Finished","unrelated saved-frame refresh failure does not report material assignment as failed");
    Check(type.GetField("generation",flags).GetValue(form)==null,"unverifiable saved frame invalidates existing generation after material writes");
   }
  }
 }
 static void ClosePicker(IntPtr window,bool titlebar){
  if(titlebar)PostMessage(window,0x112,new IntPtr(0xF060),IntPtr.Zero); // SC_CLOSE, same as title-bar X
  else ((InvokePattern)Find(AutomationElement.FromHandle(window),"Close",ControlType.Button).GetCurrentPattern(InvokePattern.Pattern)).Invoke();
 }
 static void Picker(object service,ISldWorks app,ModelDoc2 assembly,bool apply,bool titlebar=false){
  using(var dispatcher=new Control()){
   var handle=dispatcher.Handle;var pid=app.GetProcessID();var closed=0;
   Exception automationError=null;
   using(var closer=new System.Threading.Timer(state=>EnumWindows((window,data)=>{
    uint owner;GetWindowThreadProcessId(window,out owner);var title=new StringBuilder(512);GetWindowText(window,title,512);
    if(owner==pid && title.ToString()=="Material" && IsWindowVisible(window) && Interlocked.CompareExchange(ref closed,1,0)==0){
     try{
      var dialog=AutomationElement.FromHandle(window);
      if(apply){
       Expand(Find(dialog,"SOLIDWORKS Materials",ControlType.TreeItem));Expand(Find(dialog,"Steel",ControlType.TreeItem));
       foreach(var name in new[]{"Plain Carbon Steel","Alloy Steel"}){
        ((SelectionItemPattern)Find(dialog,name,ControlType.TreeItem).GetCurrentPattern(SelectionItemPattern.Pattern)).Select();
        Thread.Sleep(250);
        ((InvokePattern)Find(dialog,"Apply",ControlType.Button).GetCurrentPattern(InvokePattern.Pattern)).Invoke();
        Thread.Sleep(250);
       }
       // Merely highlighting a third material must not replace the last Apply.
       ((SelectionItemPattern)Find(dialog,"Galvanized Steel",ControlType.TreeItem).GetCurrentPattern(SelectionItemPattern.Pattern)).Select();
      }
     }catch(Exception e){automationError=e;}
     finally{try{ClosePicker(window,titlebar);}catch(Exception e){automationError=automationError??e;PostMessage(window,0x10,IntPtr.Zero,IntPtr.Zero);}}
    }return true;
   },IntPtr.Zero),null,2000,1000)){
    var task=(Task)Invoke(service,"PickAsync",dispatcher);var deadline=DateTime.UtcNow.AddSeconds(45);
    while(!task.IsCompleted && DateTime.UtcNow<deadline){Application.DoEvents();Thread.Sleep(10);}
    Check(task.IsCompleted,"native picker closes through command event");task.GetAwaiter().GetResult();
    if(automationError!=null)throw automationError;
    var choice=task.GetType().GetProperty("Result").GetValue(task,null);
    if(apply){
     Check(choice!=null && (string)Field(choice,"Name")=="Alloy Steel","last native Apply wins over an unapplied highlight");
     var result=Apply(service,choice,null,CancellationToken.None);
     Check(Field(result,"Error")==null && ((IList)Field(result,"Remaining")).Count==0,"native picker choice applies to all captured targets");
    }else Check(choice==null,"closing without Apply cancels selection");
    Check(app.ActiveDoc==assembly,"picker restores assembly");
   }
  }
 }
 public static void Run(string dll,string folder,int[] existing,bool testPicker,bool pickerOnly,ISldWorks host=null,bool assignmentOnly=false){
  var app=host??(ISldWorks)Marshal.GetActiveObject("SldWorks.Application");currentApp=app;isolated=host!=null;
  var original=app.ActiveDoc as ModelDoc2;
  if(original!=null && original.GetPathName().StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))original=null;
  var opened=new System.Collections.Generic.List<ModelDoc2>();
  try {
   SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
   var path=Path.Combine(folder,"bodies.SLDPRT");var assemblyPath=Path.Combine(folder,"fixture.SLDASM");int openError=0,openWarning=0;
   var reuse=File.Exists(path) && File.Exists(assemblyPath);
   var part=reuse?(ModelDoc2)app.OpenDoc6(path,1,1,"",ref openError,ref openWarning):(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
   opened.Add(part);
   if(!reuse){Box(part,0);Box(part,.3);Box(part,.6);}
   var config=part.ConfigurationManager.ActiveConfiguration.Name;
   var db=((IEnumerable)app.GetMaterialDatabases()).Cast<string>().First(p=>Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
   ((PartDoc)part).SetMaterialPropertyName2(config,db,"Plain Carbon Steel");
   if(!reuse)Save(part,path);
   var assembly=reuse?(ModelDoc2)app.OpenDoc6(assemblyPath,2,1,"",ref openError,ref openWarning):(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
   opened.Add(assembly);
   var components=reuse?((object[])((AssemblyDoc)assembly).GetComponents(true)).Cast<Component2>().ToArray():null;
   var component=reuse?components[0]:((AssemblyDoc)assembly).AddComponent5(path,0,"",false,"",0,0,0);
   var duplicate=reuse?components[1]:((AssemblyDoc)assembly).AddComponent5(path,0,"",false,"",1,0,0);
   if(!reuse)Save(assembly,assemblyPath);
   var code=Assembly.LoadFrom(dll);
   var selectionType=code.GetType("BeamNG.Cad.Preparation.FrameSelection");
   var serviceType=code.GetType("BeamNG.Cad.Preparation.BulkMaterialAssignment");
   var choiceType=code.GetType("BeamNG.Cad.Preparation.NativeMaterialChoice");
   var selection=Activator.CreateInstance(selectionType,app,assembly);
   if(!pickerOnly){
    var componentReference=Ref(assembly,component);var duplicateReference=Ref(assembly,duplicate);
    var control=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);opened.Add(control);
    Box(control,0);var controlPath=Path.Combine(folder,"unrelated.SLDPRT");Save(control,controlPath);Activate(app,assembly);
    var unrelated=((AssemblyDoc)assembly).AddComponent5(controlPath,0,"",false,"",3,0,0);
    app.CloseDoc(control.GetTitle());
    // SolidWorks will not make a component lightweight while its part window is open.
    app.CloseDoc(part.GetTitle());Activate(app,assembly);
    if(!assignmentOnly)Normalization(selection,assembly,component,duplicate,unrelated);
    component=(Component2)Resolve(assembly,componentReference);duplicate=(Component2)Resolve(assembly,duplicateReference);
    part=(ModelDoc2)component.GetModelDoc2();
   }
   object info;var bodies=((object[])component.GetBodies3(0,out info)).Cast<Body2>().ToArray();
   assembly.ClearSelection2(true);Check(bodies[0].Select2(false,null) && bodies[1].Select2(true,null),"select two bodies");
   var saved=Invoke(selection,"Capture");
   var originalNames=bodies.Take(2).Select(b=>b.Name).ToArray();
   var originalPartVisibility=part.Visible;
   var service=Activator.CreateInstance(serviceType,app,assembly,Invoke(selection,"MaterialBodies",new object[]{null}));
   Check(part.Visible==originalPartVisibility && app.ActiveDoc==assembly,"preflight preserves source window visibility and active assembly");
   Check((int)serviceType.GetProperty("Count").GetValue(service,null)==2,"current selection contains only chosen bodies");
   if(pickerOnly){try{Picker(service,app,assembly,false);Picker(service,app,assembly,false,true);Picker(service,app,assembly,true);}finally{((IDisposable)service).Dispose();}Workflow(code,app,assembly,selection);return;}
   var choice=Activator.CreateInstance(choiceType,true);choiceType.GetField("Name").SetValue(choice,"1060 Alloy");choiceType.GetField("Database").SetValue(choice,db);
   var thread=Thread.CurrentThread.ManagedThreadId;
   var result=Apply(service,choice,(done,total,label)=>Check(thread==Thread.CurrentThread.ManagedThreadId,"assignment stays on STA thread"),CancellationToken.None);
   Console.WriteLine("ASSIGNMENT_RESULT="+result.GetType().GetProperty("Summary").GetValue(result,null));
   Check(Field(result,"Error")==null && ((IList)Field(result,"Applied")).Count==2,"bulk assignment succeeds with full database path");
   Check((int)Field(result,"RebuildCount")<=1,"at most one conditional rebuild per source configuration");
   Check(app.ActiveDoc==assembly && ((SelectionMgr)assembly.SelectionManager).GetSelectedObjectCount2(-1)==2,"assembly and selection restored");
   Check(part.Visible==originalPartVisibility,"assignment restores source window visibility (expected="+originalPartVisibility+", actual="+part.Visible+")");
   var source=((object[])((PartDoc)part).GetBodies2(0,false)).Cast<Body2>().ToArray();
   Check(source.Where(b=>originalNames.Contains(b.Name)).All(b=>Material(b,config)=="1060 Alloy"),"both targets read back chosen material");
   Check(source.Where(b=>!originalNames.Contains(b.Name)).All(b=>string.IsNullOrEmpty(Material(b,config))),"unselected body still inherits part material");
   string actualDb;Check(((PartDoc)part).GetMaterialPropertyName2(config,out actualDb)=="Plain Carbon Steel","part-level material unchanged");
   ((IDisposable)service).Dispose();
   assembly.ClearSelection2(true);
   service=Activator.CreateInstance(serviceType,app,assembly,Invoke(selection,"MaterialBodies",saved));
   Check((int)serviceType.GetProperty("Count").GetValue(service,null)==2,"saved selection works without current highlight");
   result=Apply(service,choice,null,CancellationToken.None);
   Check(Field(result,"Error")==null,"same-material assignment succeeds");((IDisposable)service).Dispose();
   component.Select4(false,null,false);duplicate.Select4(true,null,false);
   service=Activator.CreateInstance(serviceType,app,assembly,Invoke(selection,"MaterialBodies",new object[]{null}));
   Check((int)serviceType.GetProperty("Count").GetValue(service,null)==3,"shared part instances deduplicated");
   var cancel=new CancellationTokenSource();choiceType.GetField("Name").SetValue(choice,"Plain Carbon Steel");
   result=Apply(service,choice,(done,total,label)=>cancel.Cancel(),cancel.Token);
   Check((bool)Field(result,"Cancelled") && ((IList)Field(result,"Applied")).Count==1 && ((IList)Field(result,"Remaining")).Count==2,"cancellation reports partial assignment accurately");
   Check((int)Field(result,"RebuildCount")==0,"cancellation never triggers a cleanup rebuild");
   ((IDisposable)service).Dispose();cancel.Dispose();
   service=Activator.CreateInstance(serviceType,app,assembly,Invoke(selection,"MaterialBodies",saved));
   result=Apply(service,choice,(done,total,label)=>{throw new Exception("Injected progress failure");},CancellationToken.None);
   Check(((string)Field(result,"Error")).Contains("Injected progress failure") && ((IList)Field(result,"Applied")).Count==1 && ((IList)Field(result,"Remaining")).Count==1,"failure restores UI and retains verified partial results");
   Check(part.Visible==originalPartVisibility,"failure restores source window visibility");((IDisposable)service).Dispose();
   Activate(app,part);part.SetReadOnlyState(true);Activate(app,assembly);
   bool rejected=false;try{service=Activator.CreateInstance(serviceType,app,assembly,Invoke(selection,"MaterialBodies",saved));}catch(TargetInvocationException e){rejected=e.InnerException.Message.Contains("read-only");}
   Check(rejected,"read-only target rejected before assignment");
   Activate(app,part);part.SetReadOnlyState(false);Activate(app,assembly);
   // A source part in two configurations plus a different part nested below a
   // subassembly exercises the hierarchy that motivated the bulk action.
   Activate(app,part);
   Check(part.ConfigurationManager.AddConfiguration2("MaterialAlternate","","",0,"","",false)!=null,"alternate configuration created");
   part.ShowConfiguration2(config);
   var other=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);opened.Add(other);
   Box(other,0);var otherPath=Path.Combine(folder,"other.SLDPRT");Save(other,otherPath);
   var nested=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);opened.Add(nested);
   Check(((AssemblyDoc)nested).AddComponent5(otherPath,0,"",false,"",0,0,0)!=null,"nested part inserted");
   var nestedPath=Path.Combine(folder,"nested.SLDASM");Save(nested,nestedPath);
   Activate(app,assembly);
   var sub=((AssemblyDoc)assembly).AddComponent5(nestedPath,0,"",false,"",2,0,0);
   duplicate.ReferencedConfiguration="MaterialAlternate";assembly.EditRebuild3();
   assembly.ClearSelection2(true);component.Select4(false,null,false);duplicate.Select4(true,null,false);sub.Select4(true,null,false);
   service=Activator.CreateInstance(serviceType,app,assembly,Invoke(selection,"MaterialBodies",new object[]{null}));
   Check((int)serviceType.GetProperty("Count").GetValue(service,null)==7,"nested parts and distinct configurations expanded");
   choiceType.GetField("Name").SetValue(choice,"1060 Alloy");
   result=Apply(service,choice,null,CancellationToken.None);
   Check(Field(result,"Error")==null && ((IList)Field(result,"Applied")).Count==7,"all seven targets across hierarchies assigned: "+Field(result,"Error"));
   Check((int)Field(result,"RebuildCount")<=3,"rebuild count bounded by distinct source configurations");
   Check(part.ConfigurationManager.ActiveConfiguration.Name==config && app.ActiveDoc==assembly,"original source configuration restored");
   ((IDisposable)service).Dispose();
   Activate(app,part);part.ShowConfiguration2("MaterialAlternate");
   Check(((object[])((PartDoc)part).GetBodies2(0,false)).Cast<Body2>().All(b=>Material(b,"MaterialAlternate")=="1060 Alloy"),"alternate configuration readback");
   part.ShowConfiguration2(config);Activate(app,assembly);
   Check(((object[])((PartDoc)other).GetBodies2(0,false)).Cast<Body2>().All(b=>Material(b,other.ConfigurationManager.ActiveConfiguration.Name)=="1060 Alloy"),"separate nested part readback");
   var snapshot=Invoke(selection,"ReadMaterials",saved);
   Check(((IEnumerable)Field(snapshot,"Bodies")).Cast<object>().All(b=>Field(b,"Error")==null && (string)Field(b,"Name")=="1060 Alloy"),"export material reader sees assigned native values");
   if(testPicker){
    service=Activator.CreateInstance(serviceType,app,assembly,Invoke(selection,"MaterialBodies",saved));
    try{Picker(service,app,assembly,false);Picker(service,app,assembly,false,true);Picker(service,app,assembly,true);}finally{((IDisposable)service).Dispose();}
    Invoke(selection,"Show",saved);Workflow(code,app,assembly,selection);
   }
   Console.WriteLine("BULK_MATERIAL_EVIDENCE="+folder);
  } catch(Exception e){Console.WriteLine(e.ToString());throw;}
  finally {foreach(var doc in opened.AsEnumerable().Reverse())try{app.CloseDoc(doc.GetTitle());}catch(COMException){}if(original!=null)Activate(app,original);}
 }
}
'@
if($CompileOnly){Add-Type -ReferencedAssemblies $refs -TypeDefinition $source -OutputAssembly (Join-Path $OutputDirectory 'BulkMaterialsSmoke.dll');return}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $source
if($Gate){Write-Output "BULK_TEST_PID=$PID";while(-not (Test-Path -LiteralPath $Gate)){Start-Sleep -Milliseconds 250}}
[BulkMaterialsSmoke]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$root,[int[]]$existing,$TestPicker.IsPresent,$PickerOnly.IsPresent)
