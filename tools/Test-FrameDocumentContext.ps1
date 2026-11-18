param([string]$OutputDirectory=(Join-Path $PSScriptRoot '../beamng.cad/bin/proxy-preview-context'))
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$wpf=Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'WPF'
$refs=@('System.Core','System.Drawing','System.Windows.Forms',
 (Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),
 (Join-Path $wpf 'WindowsBase.dll'),(Join-Path $wpf 'PresentationCore.dll'),
 (Join-Path $wpf 'PresentationFramework.dll'),(Join-Path $wpf 'WindowsFormsIntegration.dll'))
foreach($ref in $refs[3..7]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Remoting.Proxies;
using System.Runtime.Remoting.Messaging;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
public static class FrameDocumentContextTest {
 const BindingFlags Flags=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance;
 sealed class Proxy:RealProxy {
  readonly Func<IMethodCallMessage,object> invoke;
  readonly Type type;
  public Proxy(Type type,Func<IMethodCallMessage,object> invoke):base(type){this.invoke=invoke;this.type=type;}
  public override IMessage Invoke(IMessage message){var call=(IMethodCallMessage)message;try{return new ReturnMessage(call.MethodName=="GetType"&&((MethodInfo)call.MethodBase).ReturnType==typeof(Type)?type:invoke(call),null,0,call.LogicalCallContext,call);}catch(Exception error){return new ReturnMessage(error,call);}}
 }
 static object Stub(Type type,Func<IMethodCallMessage,object> invoke){return new Proxy(type,invoke).GetTransparentProxy();}
 static object Get(object obj,string name){return obj.GetType().GetField(name,Flags).GetValue(obj);}
 static void Set(object obj,string name,object value){obj.GetType().GetField(name,Flags).SetValue(obj,value);}
 static object Call(object obj,string name,params object[] args){try{return obj.GetType().GetMethod(name,Flags).Invoke(obj,args);}catch(TargetInvocationException error){throw error.InnerException;}}
 static void Check(bool ok,string text){if(!ok)throw new Exception(text);Console.WriteLine("PASS: "+text);}
 static object New(Assembly code,string type,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+type),Flags,null,args,null);}
 static object Prop(object obj,string name){return obj.GetType().GetProperty(name,Flags).GetValue(obj,null);}
 static Control Find(Control root,string name){return root.Controls.Find(name,true).Single();}
 static void NextSteps(Assembly code,ISldWorks app,ModelDoc2 model,string document){
  var folder=Path.Combine(Path.GetTempPath(),"beamng-next-step-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);
  try {
   File.WriteAllText(document,"Saved assembly stand-in for the offline routing test");
   var catalog=code.GetType("BeamNG.Cad.Preparation.MvpCatalog").GetMethod("Load").Invoke(null,null);
   var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");
   var project=projectType.GetMethod("CreateFresh").Invoke(null,new[]{(object)document,Path.Combine(folder,"project.json"),catalog,"authored"});
   var groups=(IList)Get(project,"Components");
   var frameGroup=groups.Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="frame");
   var settings=New(code,"UI.ExporterSettings",Path.Combine(folder,"settings.xml"));
   using(var host=new Form {Width=340,Height=850,StartPosition=FormStartPosition.Manual,Location=new System.Drawing.Point(-20000,-20000)})
   using(var workspace=(Control)New(code,"UI.ProjectWorkspace",app,settings)){
    host.Controls.Add(workspace);Call(workspace,"SelectProject",project,model);host.Show();
    var navigation=(FlowLayoutPanel)Get(workspace,"navigation");
    var drivelineButton=navigation.Controls.OfType<Button>().Single(b=>b.Text=="Driveline");
    drivelineButton.PerformClick();Application.DoEvents();
    var routes=Find(workspace,"DrivelineRoutes");
    Check((string)Prop(workspace,"CurrentStage")=="Driveline"&&routes.Visible&&
          !Find(workspace,"MvpTemplate_drivetrain").Visible,"first Driveline click displays Routes instead of the vehicle layout");
    Call(workspace,"Navigate","Joints");
    drivelineButton.PerformClick();Application.DoEvents();
    Check(routes.Visible,"returning to Driveline displays Routes again");
    Check((bool)Call(workspace,"Navigate","Frame"),"fresh vehicle opens the docked frame editor");
    var frame=Get(workspace,"frame");var preview=Get(frame,"previewWindow");Set(preview,"ForceCpuPreview",true);
    Set(preview,"source",new System.Windows.Media.Media3D.Point3D[0]);Set(frame,"previewStamp",(int?)0);
    Call(workspace,"UpdateNextStep");Application.DoEvents();
    var title=Find(workspace,"WorkflowNextTitle");var next=(Button)Find(workspace,"WorkflowNextAction");
    Check(title.Text.Contains("Proxy preview ready")&&title.Text.Contains("Assign required component bodies")&&Find(workspace,"WorkflowNextDetail").Text.Contains("Use saved frame"),"proxy completion points to linking the frame and assigning bodies");
    var panel=Find(workspace,"WorkflowNextStep");Check(panel.Visible&&next.Right<panel.ClientSize.Width&&next.Height>=32,"next action fits a narrow workspace");
    next.PerformClick();
    var components=(ListBox)Find(workspace,"Components");
    Check((string)Prop(workspace,"CurrentStage")=="Components"&&(string)Get(components.SelectedItem,"Id")== (string)Get(frameGroup,"Id"),"next action selects the exact missing group");
    var editor=Get(workspace,"components");
    var editorProject=Prop(editor,"CurrentProject");
    var springGroups=((IList)Get(editorProject,"Components")).Cast<object>()
     .Where(c=>((string)Get(c,"MvpRole")??"").EndsWith("_spring_damper")).ToArray();
    var lastSpring=springGroups.Last();
    var springAction=(Button)Find(workspace,"OpenSpringSetup");
    var springProgress=Find(workspace,"SpringCadProgress");
    var componentDetails=(TabControl)Find(workspace,"ComponentDetails");
    Check(!springProgress.Visible&&!springAction.Visible,"spring handoff does not add clutter to other CAD groups");
    foreach(var group in springGroups){
     Set(group,"CadSourceDocument",document);Set(group,"Configuration","Default");
     ((IList)Get(group,"Selections")).Add(New(code,"Preparation.SelectionReference"));
    }
    Set(lastSpring,"Configuration","Other");
    Call(editor,"RefreshLists");components.SelectedItem=lastSpring;Application.DoEvents();
    Check(springProgress.Visible&&springProgress.Text.Contains("3 of 4")&&springProgress.Text.Contains((string)Get(lastSpring,"Name"))&&!springAction.Visible,
     "Spring Setup waits for all four full assemblies in the current configuration");
    Set(lastSpring,"Configuration","Default");
    Call(editor,"Save");Call(editor,"RefreshLists");Application.DoEvents();
    var springButtonBounds=componentDetails.SelectedTab.RectangleToClient(springAction.RectangleToScreen(springAction.ClientRectangle));
    Check(springProgress.Text.Contains("4 of 4")&&springAction.Visible&&springButtonBounds.Left>=0&&
     springButtonBounds.Right<componentDetails.SelectedTab.ClientSize.Width&&springButtonBounds.Bottom<=componentDetails.SelectedTab.ClientSize.Height,
     "final saved spring assembly reveals an action that fits the narrow dock");
    var inspection=Find(workspace,"AssignmentInspection");
    Check(inspection.Visible&&inspection.Height>=inspection.PreferredSize.Height&&componentDetails.SelectedTab.Contains(inspection),
     "narrow CAD assignment retains the saved geometry inspection controls");
    springAction.PerformClick();Application.DoEvents();
    var setupAssembly=Find(workspace,"SpringSetupAssembly");
    Check(componentDetails.SelectedTab.Text=="Spring Setup"&&ReferenceEquals(components.SelectedItem,lastSpring)&&setupAssembly.Text.Contains((string)Get(lastSpring,"Name")),
     "Open Spring Setup keeps the selected assembly");
    var springPieces=Find(workspace,"CoiloverPieces");
    var pieceBounds=componentDetails.SelectedTab.RectangleToClient(springPieces.RectangleToScreen(springPieces.ClientRectangle));
    Check(components.ClientSize.Height>=components.ItemHeight&&pieceBounds.Right<=componentDetails.SelectedTab.ClientSize.Width,
     "the narrow dock keeps the component list usable and spring piece slots fit horizontally");
    components.SelectedItem=springGroups[0];Application.DoEvents();
    Check(componentDetails.SelectedTab.Text=="Spring Setup"&&setupAssembly.Text.Contains((string)Get(springGroups[0],"Name")),
     "switching spring groups keeps Spring Setup open");
    Check((bool)Call(workspace,"Navigate","Frame")&&ReferenceEquals(Get(workspace,"frame"),frame)&&((string)Prop(frame,"PreviewStatus")).StartsWith("Proxy"),"returning to Frame retains a current proxy");
    foreach(var group in groups){Set(group,"Configuration","Default");Set(group,"CadSourceDocument",document);((IList)Get(group,"Selections")).Add(New(code,"Preparation.SelectionReference"));}
    groups.Add(New(code,"Preparation.ComponentDefinition")); // Unassigned optional group.
    Call(project,"Save");Call(Prop(workspace,"Session"),"Refresh");
    Check(title.Text.Contains("Review actual joints and hardpoints"),"after required CAD is assigned, optional groups do not delay hardpoint guidance");
    Set(frame,"prepared",folder);Call(frame,"Busy",false);Call(workspace,"UpdateNextStep");
    Check(title.Text.Contains("Prepared hull ready")&&((Button)Get(frame,"accept")).Enabled,"prepared hull remains available for compiler preflight with hardpoints pending");
    next.PerformClick();Check((string)Prop(workspace,"CurrentStage")=="Joints","hardpoint action opens Joints");
    Check((bool)Call(workspace,"Navigate","Frame")&&Get(frame,"prepared")!=null,"hardpoint editor round trip retains the prepared hull");
    Set(frame,"generation",folder);Call(workspace,"UpdateNextStep");
    Check(title.Text.Contains("Fixtures need review")&&next.Text=="Review fixtures","generated frame surfaces fixture review above the preview");
    var authored=Get(project,"JointWorkspace");Set(authored,"Mode","legacy");Set(project,"PhysicsTemplateReceipt","fixture receipt");
    Call(project,"Save");Call(Prop(workspace,"Session"),"Refresh");Call(workspace,"Navigate","Overview");next.PerformClick();
    Check((string)Prop(workspace,"CurrentStage")=="Components"&&((TabControl)Find(workspace,"ComponentDetails")).SelectedTab.Text=="Appearance","imported physics opens the Appearance editor directly");
    Set(authored,"Mode","authored");Set(project,"PhysicsTemplateReceipt",null);
   }
   var readiness=code.GetType("BeamNG.Cad.UI.VehicleReadiness").GetMethod("Evaluate");
   var jointWorkspace=Get(project,"JointWorkspace");var anchors=(IList)Get(project,"Anchors");
   foreach(var request in (IEnumerable)Call(catalog,"JointRequests",project)){
    var id=(string)Get(request,"Id");var role=(string)Get(request,"Role");
    var owner=groups.Cast<object>().FirstOrDefault(c=>id.StartsWith((string)Get(c,"Id")+".",StringComparison.Ordinal))??groups.Cast<object>().Single(c=>(string)Get(c,"MvpRole")==role);
    var ownerId=(string)Get(owner,"Id");
    var anchor=New(code,"Preparation.MountAnchor");Set(anchor,"ComponentId",ownerId);Set(anchor,"Status","resolved");anchors.Add(anchor);
    var binding=New(code,"Preparation.HardpointBinding");Set(binding,"Request",id);Set(binding,"ComponentId",ownerId);Set(binding,"AnchorId",Get(anchor,"Id"));
    ((IList)Get(jointWorkspace,"Bindings")).Add(binding);
   }
   Check((string)Get(readiness.Invoke(null,new[]{project,catalog,"Default"}),"Stage")=="Frame","saved authored hardpoints lead back to Frame preflight");
   Set(anchors[0],"Status","needs_repair");
   Check((int)Get(readiness.Invoke(null,new[]{project,catalog,"Default"}),"MissingHardpoints")==1,"an unresolved CAD anchor remains a hardpoint blocker");
   Set(jointWorkspace,"Mode","legacy");
   Check((string)Get(readiness.Invoke(null,new[]{project,catalog,"Default"}),"Stage")=="Project","reviewed template route offers project tools when JSON is missing");
   var definition=Path.Combine(folder,"definition.json");File.WriteAllText(definition,"{}");Set(project,"TemplateDefinitionPath",definition);
   Check((bool)Get(readiness.Invoke(null,new[]{project,catalog,"Default"}),"CanGenerateFrame"),"existing reviewed template reaches preflight, which still validates its contents");
   Set(project,"PhysicsTemplateReceipt","fixture receipt");Check((string)Get(readiness.Invoke(null,new[]{project,catalog,"Default"}),"ActionText")=="Assign appearances","imported physics keeps its appearance route");
   Set(project,"PhysicsTemplateReceipt",null);Set(project,"TemplateDefinitionPath",null);groups.Clear();groups.Add(frameGroup);
   Check((bool)Get(readiness.Invoke(null,new[]{project,catalog,"Default"}),"CanGenerateFrame"),"calibrated frame-only route needs no vehicle groups");
  } finally {if(File.Exists(document))File.Delete(document);}
 }
 static object Empty(IMethodCallMessage call){var type=((MethodInfo)call.MethodBase).ReturnType;return type==typeof(void)?null:type.IsValueType?Activator.CreateInstance(type):null;}
 public static void Run(string directory){
  var code=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));
  string path=Path.Combine(Path.GetTempPath(),"beamng-context-"+Guid.NewGuid().ToString("N")+".sldasm");
  bool closed=false;int oldCalls=0;string configuration="Default";ModelDoc2 active=null;
  Func<IMethodCallMessage,object> doc=call=>{
   if(call.MethodName=="GetType")return 2;
   if(call.MethodName=="GetPathName")return path;
   if(call.MethodName=="get_ConfigurationManager")return Stub(((MethodInfo)call.MethodBase).ReturnType,manager=>{
    if(manager.MethodName=="get_ActiveConfiguration")return Stub(((MethodInfo)manager.MethodBase).ReturnType,c=>c.MethodName=="get_Name"?configuration:Empty(c));return Empty(manager);});
   return Empty(call);
  };
  var original=(ModelDoc2)Stub(typeof(ModelDoc2),call=>{oldCalls++;if(closed)throw new COMException("fixture disconnected",unchecked((int)0x80010108));return doc(call);});
  var replacement=(ModelDoc2)Stub(typeof(ModelDoc2),doc);active=original;
  var app=(ISldWorks)Stub(typeof(ISldWorks),call=>{
   if(call.MethodName=="get_ActiveDoc")return active;
   if(call.MethodName=="IsSame"){
    if(closed&&Object.ReferenceEquals(call.Args[1],original))throw new COMException("fixture disconnected",unchecked((int)0x80010108));
    return Object.ReferenceEquals(call.Args[0],call.Args[1])?1:0;
   }return Empty(call);
  });
  using(var editor=(Form)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.FrameWorkflow"),Flags,null,new object[]{app,original},null)){
   var selection=Get(editor,"selection");Call(selection,"ValidateDocument");
   var frameType=code.GetType("BeamNG.Cad.Preparation.FrameAssignment");var assignment=Activator.CreateInstance(frameType,true);Set(assignment,"Configuration","Default");Set(editor,"frame",assignment);Set(editor,"prepared","old result");
   var value=Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation.HullOptions"),true);Set(value,"Width",5);
   var preview=Get(editor,"previewWindow");((Delegate)Get(preview,"ApplyRequested")).DynamicInvoke(value);
   Check((int)Get(Get(assignment,"Hull"),"Width")==5&&Get(editor,"prepared")==null,"Apply updates the real frame options and invalidates prepared output");
   Set(preview,"ForceCpuPreview",true);editor.MinimumSize=System.Drawing.Size.Empty;editor.Width=360;editor.Height=820;editor.Show();
   ((Delegate)Get(preview,"SearchOpened")).DynamicInvoke();Call(preview,"StartSearch");
   var until=DateTime.UtcNow.AddSeconds(2);while(DateTime.UtcNow<until&&!((Label)Get(preview,"state")).Text.Contains("Start preview")){Application.DoEvents();Thread.Sleep(2);}
   var tabs=(TabControl)editor.GetType().GetProperty("tabs",Flags).GetValue(editor,null);
   Check(tabs.SelectedTab.Text=="Hull suggestions"&&((Label)Get(preview,"state")).Text.Contains("Start preview"),"search before capture gives an action available in the current view");
   var panel=(Control)preview.GetType().GetProperty("SearchControls",Flags).GetValue(preview,null);
   Check(panel.Controls.Find("StartHullPreview",true).Length==1&&((Button)Get(preview,"capturePreview")).Text=="Start preview","preview can be started from either toolbar without opening settings");
   ((Button)panel.Controls.Find("ShowHullSettings",true)[0]).PerformClick();
   Check(tabs.SelectedTab.Text=="Hull settings"&&(int)Get(Get(assignment,"Hull"),"Width")==5,"Show current settings reveals the hidden hull tab without changing values");editor.Hide();
   closed=true;active=replacement;int before=oldCalls;
   bool friendly=false;try{Call(selection,"ValidateDocument");}catch(InvalidOperationException e){friendly=e.InnerException is COMException;}
   Check(friendly&&oldCalls==before,"disconnected identity is reported without calling the dead document");
   Set(editor,"prepared","old prepared result");Set(editor,"previewStamp",(int?)10);
   using(var running=new CancellationTokenSource()){
    Set(editor,"cancellation",running);Call(editor,"RefreshDocumentContext");
    Check(Object.ReferenceEquals(Get(editor,"model"),original),"running capture never rebinds to another document");Set(editor,"cancellation",null);
   }
   configuration="Other";bool rejected=false;try{Call(editor,"RefreshDocumentContext");}catch(InvalidOperationException){rejected=true;}
   Check(rejected&&Object.ReferenceEquals(Get(editor,"model"),original),"another configuration cannot replace the frame context");configuration="Default";
   Call(editor,"RefreshDocumentContext");
   Check(Object.ReferenceEquals(Get(editor,"model"),replacement)&&!Object.ReferenceEquals(Get(editor,"selection"),selection),"idle refresh rebinds reopened source assembly");
   Check(Get(editor,"prepared")==null&&Get(editor,"previewStamp")==null,"reopened document discards prepared results and snapshot stamp");
   Call(Get(editor,"selection"),"ValidateDocument");Check(oldCalls==before,"recovery never dereferences the disconnected document");
   active=null;Call(editor,"CheckPreviewContext");Check(Object.ReferenceEquals(Get(editor,"model"),replacement),"closing the source does not bind a different document");
   active=replacement;Call(editor,"RefreshDocumentContext");Call(Get(editor,"selection"),"ValidateDocument");
   Check(true,"reactivating the source permits fresh preview capture");
   File.Delete(path+".truemesh-prep.json");
  }
  NextSteps(code,app,replacement,path);
 }
}
'@
[FrameDocumentContextTest]::Run($OutputDirectory)
