param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination,[string]$ReviewFixture,[switch]$SyncTest,[string]$SyncFixture)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new owned test directory'}
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[5..6]){[void][Reflection.Assembly]::LoadFrom($ref)}
# Reuse only the owned-process ROT lookup / prompt guard and primitive builder.
$helper=Get-Content -Raw (Join-Path $PSScriptRoot 'New-SyntheticVehicle.ps1')
$start=$helper.IndexOf("using System;")
$end=$helper.IndexOf("'@",$start)
$source=$helper.Substring($start,$end-$start)+@'

public static class WorkingAssemblyTest {
 sealed class CadContext : System.Threading.SynchronizationContext {
  readonly System.Collections.Concurrent.ConcurrentQueue<Action> queue=new System.Collections.Concurrent.ConcurrentQueue<Action>();
  public override void Post(System.Threading.SendOrPostCallback action,object state){queue.Enqueue(()=>action(state));}
  public void Drain(){Action action;while(queue.TryDequeue(out action)){System.Threading.SynchronizationContext.SetSynchronizationContext(this);action();}}
 }
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Set(object o,string n,object v){o.GetType().GetField(n).SetValue(o,v);}
 static object Call(object o,string n,params object[] a){return o.GetType().GetMethod(n).Invoke(o,a);}
 static object Create(Assembly a,string n,params object[] args){return Activator.CreateInstance(a.GetType("BeamNG.Cad."+n),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,args,null);}
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine("PASS "+label);}
 static string Hash(string path){return (string)typeof(SyntheticNativeCad).GetMethod("Hash",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{path});}
 static void Save(ModelDoc2 doc,string path){int e=0,w=0;if(!doc.Extension.SaveAs(path,0,1,null,ref e,ref w))throw new Exception("Native save "+e);}
 static string PathOf(object p){return (string)p.GetType().GetProperty("FilePath").GetValue(p,null);}
 static object Wait(object task){var context=System.Threading.SynchronizationContext.Current;var t=(System.Threading.Tasks.Task)task;try{while(!t.IsCompleted){var cad=context as CadContext;if(cad!=null)cad.Drain();Application.DoEvents();System.Threading.SynchronizationContext.SetSynchronizationContext(context);System.Threading.Thread.Sleep(10);}t.GetAwaiter().GetResult();return t.GetType().GetProperty("Result").GetValue(t,null);}finally{System.Threading.SynchronizationContext.SetSynchronizationContext(context);}}
 static double[] Properties(Body2 body,Component2 instance){var b=(Body2)body.Copy();try{if(instance.Transform2!=null)b.ApplyTransform(instance.Transform2);return (double[])b.GetMassProperties(1);}finally{Marshal.ReleaseComObject(b);}}
 static void Near(double[] a,double[] b,string label){Check(a.Length==b.Length&&a.Zip(b,(x,y)=>Math.Abs(x-y)).Max()<1e-7,label);}
 static List<Tuple<Component2,Body2>> Bodies(object selection,object group){var f=Create(selection.GetType().Assembly,"Preparation.FrameAssignment");Set(f,"Configuration",Get(group,"Configuration"));Set(f,"Selections",Get(group,"Selections"));return (List<Tuple<Component2,Body2>>)Call(selection,"SnapshotBodies",f);}
 public static void Sync(object application,string dll,string folder){
  var app=(ISldWorks)application;app.CommandInProgress=true;var code=Assembly.LoadFrom(dll);int error=0,warning=0;
  System.Threading.SynchronizationContext.SetSynchronizationContext(new CadContext());
  var sourcePath=Directory.GetFiles(folder,"*.SLDASM").Where(p=>!System.IO.Path.GetFileName(p).StartsWith("~$")).Single();var source=(ModelDoc2)app.GetOpenDocumentByName(sourcePath);if(source==null)source=(ModelDoc2)app.OpenDoc6(sourcePath,2,1,"",ref error,ref warning);
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);
  var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var links=code.GetType("BeamNG.Cad.Preparation.CompanionAssemblyLink");
  var sourceProject=projectType.GetMethod("Load").Invoke(null,new object[]{sourcePath+".beamng-project.json"});var sourceGroups=(IList)Get(sourceProject,"Components");
  var rootReceipt=System.IO.Path.Combine(folder,"working","working-assembly.json");links.GetMethod("Register").Invoke(null,new object[]{rootReceipt});
  var receipt=links.GetMethod("Read").Invoke(null,new object[]{rootReceipt});var workingPath=(string)Get(receipt,"Assembly");var workingProjectPath=(string)Get(receipt,"Project");
  var working=(ModelDoc2)app.GetOpenDocumentByName(workingPath);if(working==null)working=(ModelDoc2)app.OpenDoc6(workingPath,2,1,"",ref error,ref warning);
  var workingProject=projectType.GetMethod("Load").Invoke(null,new object[]{workingProjectPath});var workingGroups=(IList)Get(workingProject,"Components");
  Check((string)links.GetMethod("Find").Invoke(null,new[]{sourceProject})==rootReceipt&&(string)links.GetMethod("Find").Invoke(null,new[]{workingProject})==rootReceipt,"source and companion links persist independently of selected project");
  app.ActivateDoc3(working.GetTitle(),false,0,ref error);working.ClearSelection2(true);working.SketchManager.Insert3DSketch(true);var point=working.SketchManager.CreatePoint(.3,.4,.5);working.SketchManager.Insert3DSketch(true);
  working.ClearSelection2(true);var manager=(SelectionMgr)working.SelectionManager;manager.AddSelectionListObject(point,manager.CreateSelectData());var mounts=Create(code,"Preparation.MountAnchors",app,working);
  var kept=Call(mounts,"Capture",workingGroups[0],"Keep frame datum");var replaced=Call(mounts,"Capture",workingGroups[1],"Changed group datum");var removed=Call(mounts,"Capture",workingGroups[2],"Removed panel datum");
  foreach(var a in new[]{kept,replaced,removed})((IList)Get(workingProject,"Anchors")).Add(a);
  var local=Create(code,"Preparation.ComponentDefinition");Set(local,"Name","Companion-only reference group");workingGroups.Add(local);
  Set(Get(workingGroups[0],"Hull"),"Width",17);Set(Get(workingGroups[1],"AppearanceCoilover"),"HousingMount","bottom");Call(workingProject,"Save");
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);var service=Create(code,"Preparation.AssociationAssembly",app,source);bool blocked=false;
  try{Wait(Call(service,"Update",sourceProject,rootReceipt,false,null,System.Threading.CancellationToken.None));}catch(Exception ex){blocked=ex.ToString().Contains("Save the companion");}
  Check(blocked,"unsaved companion reference work blocks an update without discarding it");
  app.ActivateDoc3(working.GetTitle(),false,0,ref error);Save(working,workingPath);
  var selection=Create(code,"Preparation.FrameSelection",app,working,true);var framePair=Bodies(selection,workingGroups[0]).Single();var framePartPath=framePair.Item1.GetPathName();
  working.ClearSelection2(true);((Entity)((object[])framePair.Item2.GetVertices())[0]).Select4(false,null);
  var vertexMount=Call(mounts,"Capture",workingGroups[0],"Keep vertex mount");((IList)Get(workingProject,"Anchors")).Add(vertexMount);Call(workingProject,"Save");
  var part=(ModelDoc2)app.GetOpenDocumentByName(framePartPath);if(part==null)part=(ModelDoc2)app.OpenDoc6(framePartPath,1,1,"",ref error,ref warning);app.ActivateDoc3(part.GetTitle(),false,0,ref error);
  part.SketchManager.Insert3DSketch(true);part.SketchManager.CreatePoint(1,2,3);part.SketchManager.Insert3DSketch(true);Save(part,framePartPath);app.CloseDoc(part.GetTitle());
  app.ActivateDoc3(working.GetTitle(),false,0,ref error);Save(working,workingPath);
  var frameHash=Hash(framePartPath);var workingHash=Hash(workingPath);var workingProjectHash=Hash(workingProjectPath);var sourceHash=Hash(sourcePath);
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);
  Set(sourceGroups[0],"Name","Renamed frame");var dropped=sourceGroups[2];sourceGroups.RemoveAt(2);
  var sourceSelection=Create(code,"Preparation.FrameSelection",app,source,true);var instances=((object[])((AssemblyDoc)source).GetComponents(true)).Cast<Component2>().ToArray();
  source.ClearSelection2(true);instances.Single(c=>System.IO.Path.GetFileName(c.GetPathName())=="source_part_3.SLDPRT").Select4(false,null,false);var capture=Call(sourceSelection,"Capture");
  code.GetType("BeamNG.Cad.Preparation.ComponentAssignments").GetMethod("Physical").Invoke(null,new[]{sourceProject,sourceGroups[1],capture,Call(sourceSelection,"BodyIds",capture),(object)sourcePath});
  source.ClearSelection2(true);instances.Single(c=>System.IO.Path.GetFileName(c.GetPathName())=="source_part_2.SLDPRT").Select4(false,null,false);capture=Call(sourceSelection,"Capture");
  var added=Create(code,"Preparation.ComponentDefinition");Set(added,"Name","New surface panel");Set(added,"MvpRole","panel");Set(added,"Template","panel");Set(added,"SurfaceMassMode","ignore");
  code.GetType("BeamNG.Cad.Preparation.ComponentAssignments").GetMethod("Physical").Invoke(null,new[]{sourceProject,added,capture,Call(sourceSelection,"BodyIds",capture),(object)sourcePath});sourceGroups.Add(added);Call(sourceProject,"Save");
  var pending=(string)links.GetMethod("Status").Invoke(null,new[]{sourceProject,(object)rootReceipt});Check(pending.Contains("1 added")&&pending.Contains("1 removed")&&pending.Contains("2 changed"),"all source list edits are visible as pending");
  // Reproduce the modeless UI failure: source workflow, companion active in CAD.
  var prefs=Create(code,"UI.ExporterSettings",System.IO.Path.Combine(folder,"sync-ui-settings.xml"));Call(prefs,"SelectProject",sourceProject);Call(prefs,"Save");
  var workflowType=code.GetType("BeamNG.Cad.UI.ComponentWorkflow");var values=new List<int>();
  var sourceProjectHash=Hash(PathOf(sourceProject));var originalReceiptHash=Hash(rootReceipt);
  using(var window=(Form)Create(code,"UI.ComponentWorkflow",app,source,prefs)){
   window.Show();Application.DoEvents();app.ActivateDoc3(working.GetTitle(),false,0,ref error);
   var tabs=(TabControl)window.Controls.Find("WorkflowPages",true).Single();tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Components");
   var list=(ListBox)window.Controls.Find("Components",true).Single();list.SelectedItem=list.Items.Cast<object>().Single(c=>(string)Get(c,"Name")=="New surface panel");
   ((Button)window.Controls.Find("AssignCurrentSelection",true).Single()).PerformClick();Application.DoEvents();
   Check(window.Controls.Find("ComponentStatus",true).Single().Text.Contains("Activate the assembly")&&Hash(PathOf(sourceProject))==sourceProjectHash,"selection capture still rejects another active document without changing assignments");
   tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Vehicle setup / MVP");
   ((Button)window.Controls.Find("OpenCompanion",true).Single()).PerformClick();Application.DoEvents();
   var opened=Application.OpenForms.Cast<Form>().Single(f=>f.GetType()==workflowType);
   var message=opened.Controls.Find("ComponentStatus",true).Single().Text;
   Check(message.StartsWith("Opened saved companion revision.")&&message.Contains("New surface panel")&&message.Contains("updates pending"),"Open companion from an inactive source reports the uncopied panel explicitly");
   Check(Hash(rootReceipt)==originalReceiptHash&&Hash(PathOf(sourceProject))==sourceProjectHash,"opening the companion does not copy or discard pending assignments");opened.Close();
  }
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);
  using(var window=(Form)Create(code,"UI.ComponentWorkflow",app,source,prefs)){
   window.Show();Application.DoEvents();app.ActivateDoc3(working.GetTitle(),false,0,ref error);
   var bar=(ProgressBar)workflowType.GetField("progress",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(window);
   var context=System.Threading.SynchronizationContext.Current as CadContext;
   var tabs=(TabControl)window.Controls.Find("WorkflowPages",true).Single();tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Vehicle setup / MVP");
   ((Button)window.Controls.Find("UpdateCompanion",true).Single()).PerformClick();
   var until=DateTime.UtcNow.AddMinutes(5);
   while(!window.IsDisposed&&workflowType.GetField("cancel",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(window)!=null&&DateTime.UtcNow<until){if(context!=null)context.Drain();Application.DoEvents();values.Add(bar.Value);System.Threading.Thread.Sleep(10);}
   values.Add(bar.Value);
   Check(window.IsDisposed,"Update companion completes from inactive source workflow: "+(window.IsDisposed?"completed":window.Controls.Find("ComponentStatus",true).Single().Text));
   foreach(var opened in Application.OpenForms.Cast<Form>().Where(f=>f.GetType()==workflowType).ToArray())opened.Close();
  }
  receipt=links.GetMethod("Read").Invoke(null,new object[]{rootReceipt});
  var output=(ModelDoc2)app.GetOpenDocumentByName((string)Get(receipt,"Assembly"));var revised=projectType.GetMethod("Load").Invoke(null,new object[]{(string)Get(receipt,"Project")});var groups=((IEnumerable)Get(revised,"Components")).Cast<object>().ToArray();
  Check(output.GetPathName()!=workingPath&&Hash(workingPath)==workingHash&&Hash(workingProjectPath)==workingProjectHash,"update creates a revision without altering prior assembly or project");
  Check(Hash(sourcePath)==sourceHash,"source CAD remains unchanged by synchronization");
  Check(((object[])((AssemblyDoc)output).GetComponents(true)).Length==3,"updated native assembly contains exactly its three assigned groups");
  Check(Hash(framePartPath)==frameHash,"unchanged frame part including its added reference sketch is not rewritten");
  Check(groups.Any(c=>(string)Get(c,"Id")== (string)Get(added,"Id"))&&!groups.Any(c=>(string)Get(c,"Id")== (string)Get(dropped,"Id")),"added and removed source groups synchronize");
  Check(groups.Any(c=>(string)Get(c,"Id")== (string)Get(local,"Id")),"companion-only group is retained");
  Check((string)Get(Get(groups.Single(c=>(string)Get(c,"Id")== (string)Get(sourceGroups[1],"Id")),"AppearanceCoilover"),"HousingMount")=="bottom","unchanged companion coilover settings survive geometry reassignment");
  var frame=groups.Single(c=>(string)Get(c,"Id")== (string)Get(sourceGroups[0],"Id"));Check((string)Get(frame,"Name")=="Renamed frame"&&(int)Get(Get(frame,"Hull"),"Width")==17,"source rename applies without overwriting unchanged companion tuning");
  var newSelection=Create(code,"Preparation.FrameSelection",app,output,true);var frameBody=Bodies(newSelection,frame).Single();Check(frameBody.Item1.ComponentReference=="Renamed frame"&&string.Equals(frameBody.Item1.GetPathName(),framePartPath,StringComparison.OrdinalIgnoreCase),"native component reference label updates while reusing its existing part");
  var anchors=((IEnumerable)Get(revised,"Anchors")).Cast<object>().ToArray();
  Check((string)Get(anchors.Single(a=>(string)Get(a,"Id")== (string)Get(kept,"Id")),"Status")=="resolved","unchanged mounting reference survives revision copy");
  Check((string)Get(anchors.Single(a=>(string)Get(a,"Id")== (string)Get(vertexMount,"Id")),"Status")=="resolved","unchanged component vertex mount is rebound to the new assembly context");
  Check((string)Get(anchors.Single(a=>(string)Get(a,"Id")== (string)Get(replaced,"Id")),"Status")=="needs_repair","replaced geometry explicitly invalidates its mounting references");
  Check(!anchors.Any(a=>(string)Get(a,"Id")== (string)Get(removed,"Id")),"removed group mounts are removed only from new revision");
  Check(values.Last()==100&&values.Zip(values.Skip(1),(a,b)=>b>=a).All(x=>x),"update progress is monotonic and completes");
  Check((string)Get(Get(revised,"Identity"),"Id")== (string)Get(Get(workingProject,"Identity"),"Id"),"companion mod identity survives updates");
  Check(new[]{"LastBuildReceipt","FrameBuildReceipt","PhysicsBuildReceipt","PhysicsTemplateReceipt"}.All(n=>string.IsNullOrEmpty((string)Get(revised,n))),"updated revision cannot inherit old build qualification");
  Check(((string)links.GetMethod("Status").Invoke(null,new[]{sourceProject,(object)rootReceipt})).StartsWith("Saved assignments are synchronized"),"pending indicator clears after successful update");
  var revisedPath=output.GetPathName();var revisedProjectPath=PathOf(revised);app.CloseDoc(output.GetTitle());output=(ModelDoc2)app.OpenDoc6(revisedPath,2,1,"",ref error,ref warning);app.ActivateDoc3(output.GetTitle(),false,0,ref error);
  revised=projectType.GetMethod("Load").Invoke(null,new object[]{revisedProjectPath});newSelection=Create(code,"Preparation.FrameSelection",app,output,true);
  Check(((IEnumerable)Get(revised,"Components")).Cast<object>().Where(c=>((IList)Get(c,"Selections")).Count>0).All(c=>Bodies(newSelection,c).Count>0),"all updated CAD groups resolve after native reopen");
  foreach(var c in ((IEnumerable)Get(revised,"Components")).Cast<object>().Where(c=>((IList)Get(c,"Selections")).Count>0)){var f=Create(code,"Preparation.FrameAssignment");Set(f,"Configuration",Get(c,"Configuration"));Set(f,"Selections",Get(c,"Selections"));Check(((IEnumerable)Get(c,"BodyIds")).Cast<string>().SequenceEqual(((IEnumerable)Call(newSelection,"BodyIds",f)).Cast<string>()),"stored body IDs survive reopen for "+Get(c,"Name"));}
  var reopenedMounts=Create(code,"Preparation.MountAnchors",app,output);foreach(var id in new[]{(string)Get(kept,"Id"),(string)Get(vertexMount,"Id")})Call(reopenedMounts,"Update",((IEnumerable)Get(revised,"Anchors")).Cast<object>().Single(a=>(string)Get(a,"Id")==id));
  Check(true,"unchanged assembly datum and component vertex mount resolve after reopen");
  var vertexSaved=((IEnumerable)Get(revised,"Anchors")).Cast<object>().Single(a=>(string)Get(a,"Id")== (string)Get(vertexMount,"Id"));var bodyRefs=(IList)Get(vertexSaved,"BodyReferences");var originalBodyRef=bodyRefs[0];
  var otherGroup=((IEnumerable)Get(revised,"Components")).Cast<object>().Single(c=>(string)Get(c,"Id")== (string)Get(sourceGroups[1],"Id"));bodyRefs[0]=Get(((IList)Get(otherGroup,"Selections"))[0],"Reference");
  blocked=false;try{Call(reopenedMounts,"Update",vertexSaved);}catch{blocked=true;}Check(blocked,"mount ownership check still rejects a reference to another body");bodyRefs[0]=originalBodyRef;Call(reopenedMounts,"Update",vertexSaved);
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);var receiptHash=Hash(rootReceipt);var noop=Wait(Call(service,"Update",sourceProject,rootReceipt,false,null,System.Threading.CancellationToken.None));
  Check(((ModelDoc2)Get(noop,"Document")).GetPathName()==revisedPath&&Hash(rootReceipt)==receiptHash,"no-op update creates no extra revision or rewritten receipt");
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);blocked=false;try{Wait(Call(service,"Update",sourceProject,rootReceipt,false,null,new System.Threading.CancellationToken(true)));}catch{blocked=true;}Check(blocked&&Hash(rootReceipt)==receiptHash,"cancelled update cannot promote an incomplete revision");
  // Force refresh is explicit; it also tests replacing geometry with the same durable selections.
  var moved=instances.Single(c=>System.IO.Path.GetFileName(c.GetPathName())=="source_part_0.SLDPRT");var data=(double[])moved.Transform2.ArrayData;data[9]+=.25;moved.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(data);Save(source,sourcePath);
  var expected=Bodies(sourceSelection,sourceGroups[0]).Select(p=>Properties(p.Item2,p.Item1)).Single();
  var refreshed=Wait(Call(service,"Update",sourceProject,rootReceipt,true,null,System.Threading.CancellationToken.None));var refreshDoc=(ModelDoc2)Get(refreshed,"Document");var refreshProject=Get(refreshed,"Project");
  var refreshFrame=((IEnumerable)Get(refreshProject,"Components")).Cast<object>().Single(c=>(string)Get(c,"Id")== (string)Get(sourceGroups[0],"Id"));
  var refreshedBody=Bodies(Create(code,"Preparation.FrameSelection",app,refreshDoc,true),refreshFrame).Single();Near(Properties(refreshedBody.Item2,refreshedBody.Item1),expected,"explicit geometry refresh copies changed CAD placement with unchanged assignment IDs");
  Check(Hash(framePartPath)==frameHash&&refreshedBody.Item1.GetPathName()!=framePartPath,"forced refresh retains the former part and its sketches for recovery");
  Check((string)Get(((IEnumerable)Get(refreshProject,"Anchors")).Cast<object>().Single(a=>(string)Get(a,"Id")== (string)Get(kept,"Id")),"Status")=="needs_repair","forced refresh flags former mounting references for repair");
  File.WriteAllText(System.IO.Path.Combine(folder,"sync-result.txt"),"PASS companion update, preservation, dirty-state, no-op and cancellation checks");
 }
 public static void Review(object application,string dll,string folder,string fixture){
  var app=(ISldWorks)application;app.CommandInProgress=true;var code=Assembly.LoadFrom(dll);int e=0,w=0;
  var path=Directory.GetFiles(System.IO.Path.Combine(fixture,"working"),"*.SLDASM").Single();
  var document=(ModelDoc2)app.OpenDoc6(path,2,1,"",ref e,ref w);if(document==null)throw new Exception("Open fixture "+e);
  app.ActivateDoc3(document.GetTitle(),false,0,ref e);
  var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var projectPath=path+".beamng-project.json";var project=projectType.GetMethod("Load").Invoke(null,new object[]{projectPath});
  var originalPath=Directory.GetFiles(fixture,"*.SLDASM").Single();var original=(ModelDoc2)app.OpenDoc6(originalPath,2,1,"",ref e,ref w);
  var originalProject=projectType.GetMethod("Load").Invoke(null,new object[]{originalPath+".beamng-project.json"});var originalGroups=((IEnumerable)Get(originalProject,"Components")).Cast<object>().ToArray();
  var expectedColors=new Dictionary<string,string[]>();
  var originalSelection=Create(code,"Preparation.FrameSelection",app,original,true);app.ActivateDoc3(original.GetTitle(),false,0,ref e);
  foreach(var group in originalGroups.Take(3)){
   var pair=Bodies(originalSelection,group).Single();var reader=Create(code,"Preparation.SolidWorksAppearances",app,pair.Item1,pair.Item2);
   expectedColors[(string)Get(group,"Id")]=((object[])pair.Item2.GetFaces()).Cast<Face2>().Select(f=>string.Join(",",((double[])Get(Call(reader,"Read",f),"BaseColor")).Select(x=>Math.Round(x,3).ToString(System.Globalization.CultureInfo.InvariantCulture)))).OrderBy(x=>x).ToArray();
  }
  app.ActivateDoc3(document.GetTitle(),false,0,ref e);
  var groups=((IEnumerable)Get(project,"Components")).Cast<object>().ToArray();var selection=Create(code,"Preparation.FrameSelection",app,document,true);
  foreach(var group in groups.Take(3)){
   var pair=Bodies(selection,group).Single();var reader=Create(code,"Preparation.SolidWorksAppearances",app,pair.Item1,pair.Item2);
   var colors=((object[])pair.Item2.GetFaces()).Cast<Face2>().Select(f=>(double[])Get(Call(reader,"Read",f),"BaseColor")).ToArray();
   var actual=colors.Select(c=>string.Join(",",c.Select(x=>Math.Round(x,3).ToString(System.Globalization.CultureInfo.InvariantCulture)))).OrderBy(x=>x).ToArray();var expected=expectedColors[(string)Get(group,"Id")];
   Check(actual.SequenceEqual(expected),"copied "+Get(group,"Name")+" face colors match source: expected "+string.Join(";",expected)+" / actual "+string.Join(";",actual));
  }
  var prefs=Create(code,"UI.ExporterSettings",System.IO.Path.Combine(folder,"isolated-settings.xml"));prefs.GetType().GetProperty("LastProjectPath").SetValue(prefs,projectPath,null);
  var before=Hash(projectPath);
  using(var window=(Form)Create(code,"UI.ComponentWorkflow",app,document,prefs)){
   window.Show();Application.DoEvents();var tabs=(TabControl)window.Controls.Find("WorkflowPages",true).Single();tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Mounting points");
   var companionUpdate=(Button)window.Controls.Find("UpdateCompanion",true).Single();var companionOpen=(Button)window.Controls.Find("OpenCompanion",true).Single();
   Check(companionUpdate.Enabled&&companionOpen.Enabled&&window.Controls.Find("CompanionStatus",true).Single().Text.Contains("companion"),"native workflow discovers the companion receipt and exposes open/update controls");
   tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Vehicle setup / MVP");Application.DoEvents();
   using(var image=new System.Drawing.Bitmap(window.Width,window.Height)){window.DrawToBitmap(image,new System.Drawing.Rectangle(0,0,image.Width,image.Height));image.Save(System.IO.Path.Combine(folder,"companion-ui.png"));}
   tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Mounting points");
   var owner=(ComboBox)window.Controls.Find("MountOwner",true).Single();var mounts=(ListBox)window.Controls.Find("MountAnchors",true).Single();
   var search=(TextBox)window.Controls.Find("ComponentSearch",true).Single();search.Text="Frame";
   owner.SelectedItem=owner.Items.Cast<object>().Single(c=>(string)Get(c,"Name")=="Panel");Application.DoEvents();
   Check(tabs.SelectedTab.Text=="Mounting points"&&search.Text==""&&mounts.Items.Count==1&&(string)Get(mounts.Items[0],"Name")=="panel mount","mount selector switches owner in place, clears excluding filter and shows only its points");
   owner.SelectedItem=owner.Items.Cast<object>().Single(c=>(string)Get(c,"Name")=="Coilover");Check(mounts.Items.Count==0,"switching owner cannot retain another group's selected mounting point");
   tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Connections");var type=(ComboBox)window.Controls.Find("AttachmentType",true).Single();
   var modes=type.Items.Cast<object>().Select(item=>(string)item.GetType().GetField("Id").GetValue(item)).ToArray();Check(modes.SequenceEqual(new[]{"breakable_fastener","fixed"}),"readable attachment choices retain existing serialized physics values");
   type.SelectedIndex=1;var edited=window.GetType().GetMethod("EditedConnection",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(window,new object[]{null});Check((string)Get(edited,"Template")=="fixed","non-breaking choice still emits fixed connection");
   var label=window.Controls.Find("ConnectionScopeHelp",true).Single();Check(label.Text.Contains("cannot author")&&label.Text.Contains("one beam"),"connection editor explicitly explains suspension joint limitation");
   tabs.SelectedTab=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Mounting points");owner.SelectedIndex=0;Application.DoEvents();
   using(var image=new System.Drawing.Bitmap(window.Width,window.Height)){window.DrawToBitmap(image,new System.Drawing.Rectangle(0,0,image.Width,image.Height));image.Save(System.IO.Path.Combine(folder,"mounting-ui.png"));}
   window.Close();
  }
  Check(Hash(projectPath)==before,"workflow navigation does not modify saved group assignments");
  var mountsService=Create(code,"Preparation.MountAnchors",app,document);
  document.ClearSelection2(true);document.SketchManager.Insert3DSketch(true);var point=document.SketchManager.CreatePoint(.1,.2,.3);document.SketchManager.Insert3DSketch(true);
  document.ClearSelection2(true);var manager=(SelectionMgr)document.SelectionManager;manager.AddSelectionListObject(point,manager.CreateSelectData());
  var mount=Call(mountsService,"Capture",groups[0],"Working reference "+Guid.NewGuid().ToString("N").Substring(0,6));Set(mount,"Offset",new[]{.01,.02,.03});Call(mountsService,"Update",mount);
  Near((double[])Get(mount,"Position"),new[]{.11,-.33,.22},"new assembly 3D datum offsets use assembly coordinates");
  ((IList)Get(project,"Anchors")).Add(mount);Call(project,"Save");Save(document,path);app.CloseDoc(document.GetTitle());document=(ModelDoc2)app.OpenDoc6(path,2,1,"",ref e,ref w);app.ActivateDoc3(document.GetTitle(),false,0,ref e);
  var reloaded=projectType.GetMethod("Load").Invoke(null,new object[]{projectPath});var saved=((IEnumerable)Get(reloaded,"Anchors")).Cast<object>().Single(a=>(string)Get(a,"Id")== (string)Get(mount,"Id"));
  Call(Create(code,"Preparation.MountAnchors",app,document),"Update",saved);Near((double[])Get(saved,"Position"),new[]{.11,-.33,.22},"new working assembly datum resolves after native save / reopen");
  File.WriteAllText(System.IO.Path.Combine(folder,"result.txt"),"PASS appearance, full mounting UI and persistent working datum checks");
 }
 public static void Run(object application,string dll,string folder){
  var app=(ISldWorks)application;app.CommandInProgress=true;var code=Assembly.LoadFrom(dll);
  System.Threading.SynchronizationContext.SetSynchronizationContext(new CadContext());
  int error=0;var source=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
  var sourcePath=System.IO.Path.Combine(folder,"source_"+Guid.NewGuid().ToString("N").Substring(0,8)+".SLDASM");Save(source,sourcePath);
  var db=((IEnumerable)app.GetMaterialDatabases()).Cast<string>().Single(p=>System.IO.Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
  var instances=new List<Component2>();var files=new List<string>{sourcePath};
  for(var i=0;i<4;i++){
   Console.WriteLine("Native fixture part "+(i+1)+" / 4");
   var part=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
   var shape=new Dictionary<string,object>{{"kind",i==2?"sheet":"box"},{"center",new[]{0d,0,0}},{"size",new[]{.2,.1,.05}}};
   typeof(SyntheticNativeCad).GetMethod("MakeShape",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{app,part,shape,true});
   ((PartDoc)part).SetMaterialPropertyName2("",db,"AISI 4130 Steel, normalized at 870C");
   part.MaterialPropertyValues=new[]{.2,.6,.3,.3,.8,.3,.4,0d,0};
   var body=((object[])((PartDoc)part).GetBodies2(-1,false)).Cast<Body2>().Single();
   ((Face2)((object[])body.GetFaces())[0]).MaterialPropertyValues=new[]{.9,.1,.2,.3,.8,.3,.4,0d,0};
   part.SketchManager.Insert3DSketch(true);part.SketchManager.CreatePoint(9,8,7);part.SketchManager.Insert3DSketch(true);
   var path=System.IO.Path.Combine(folder,"source_part_"+i+".SLDPRT");Save(part,path);files.Add(path);
   app.ActivateDoc3(source.GetTitle(),false,0,ref error);
   var instance=((AssemblyDoc)source).AddComponent5(path,0,"",false,"",0,0,0);
   instance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(new[]{0d,0,1,0,1,0,-1,0,0,i*.4,.3,-.2,1,0,0,0});instances.Add(instance);app.CloseDoc(part.GetTitle());
  }
  // Native render overrides deliberately disagree with the legacy RGB arrays.
  // Real imported assemblies retain both, and assembly display finishes must win.
  var texturePath=System.IO.Path.Combine(folder,"test-texture.png");
  using(var texture=new System.Drawing.Bitmap(8,8)){for(var x=0;x<8;x++)for(var y=0;y<8;y++)texture.SetPixel(x,y,(x+y)%2==0?System.Drawing.Color.Black:System.Drawing.Color.White);texture.Save(texturePath);}
  foreach(var index in new[]{0,2}){
   var materialFile=System.IO.Path.Combine(folder,"source-finish-"+index+".p2m");
   var materialText=File.ReadAllText(System.IO.Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.ProgramFiles),@"SOLIDWORKS Corp\SOLIDWORKS\data\graphics\materials\color.p2m"));
   File.WriteAllText(materialFile,System.Text.RegularExpressions.Regex.Replace(materialText,"(?m)^\"col1\"[^\\r\\n]*","\"col1\" "+(index==0?"0.2 0.4 0.2":"1 1 1")));
   var finish=source.Extension.CreateRenderMaterial(materialFile);
   Check(finish.AddEntity(instances[index]),"native appearance attaches to source component "+index);
   finish.LinkToFile=false;finish.ColorForm=(int)(index==2?swRenderMaterialColorForms_e.swRenderMaterialColorFormsImage:swRenderMaterialColorForms_e.swRenderMaterialColorFormsOne_Color);finish.Diffuse=.8;finish.Roughness=.35;
   if(index==2){finish.TextureFilename=texturePath;finish.FixedAspectRatio=false;finish.Width=.03;finish.Height=.04;}
   finish.PrimaryColor=index==0?0x336633:0xffffff;
   int mat1,mat2;Check(source.Extension.AddDisplayStateSpecificRenderMaterial(finish,1,null,out mat1,out mat2),"source display-state appearance saved "+index);
  }
  source.Extension.UpdateRenderMaterialsInSceneGraph(true);
  Save(source,sourcePath);
  var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var project=projectType.GetMethod("Open").Invoke(null,new object[]{sourcePath});
  var selection=Create(code,"Preparation.FrameSelection",app,source,true);var assignments=code.GetType("BeamNG.Cad.Preparation.ComponentAssignments");
  var groups=(IList)Get(project,"Components");
  for(var i=0;i<3;i++){
   source.ClearSelection2(true);instances[i].Select4(false,null,false);var frame=Call(selection,"Capture");
   var c=Create(code,"Preparation.ComponentDefinition");Set(c,"Name",i==0?"Frame":i==1?"Coilover":"Panel");Set(c,"MvpRole",i==0?"frame":i==1?"fl_spring_damper":"panel");Set(c,"Template",i==0?"calibrated_frame":i==2?"panel":"bulk");
   assignments.GetMethod("Physical").Invoke(null,new[]{project,c,frame,Call(selection,"BodyIds",frame),(object)sourcePath});groups.Add(c);
   Set(c,"Thickness",.002);Set(c,"SurfaceMassMode","ignore");
   if(i==0){Set(c,"AppearanceSelections",Get(frame,"Selections"));Set(c,"AppearanceConfiguration",Get(frame,"Configuration"));Set(c,"AppearanceSourceDocument",sourcePath);}
   if(i==1){code.GetType("BeamNG.Cad.Preparation.CoiloverAppearance").GetMethod("Assign").Invoke(null,new[]{c,(object)"housing",frame,Call(selection,"BodyIds",frame),(object)sourcePath});var spring=Create(code,"Preparation.CoiloverSpring");Set(spring,"Mode","dual");Set(c,"CoiloverSpring",spring);}
  }
  groups.Add(Create(code,"Preparation.ComponentDefinition"));
  // Root assembly datums must work without creating anything in a source part.
  source.ClearSelection2(true);source.SketchManager.Insert3DSketch(true);var datum=source.SketchManager.CreatePoint(.7,.8,.9);source.SketchManager.Insert3DSketch(true);
  source.ClearSelection2(true);var manager=(SelectionMgr)source.SelectionManager;manager.AddSelectionListObject(datum,manager.CreateSelectData());
  var mounts=Create(code,"Preparation.MountAnchors",app,source);var anchor=Call(mounts,"Capture",groups[0],"assembly mount");
  Check((string)Get(anchor,"CoordinateSpace")=="assembly"&&(string)Get(anchor,"Status")=="resolved","assembly 3D datum binds explicitly to selected group");
  Near((double[])Get(anchor,"Position"),new[]{.7,-.9,.8},"assembly datum uses CAD-to-BeamNG mapping");((IList)Get(project,"Anchors")).Add(anchor);
  var anchor2=Call(mounts,"Capture",groups[2],"panel mount");((IList)Get(project,"Anchors")).Add(anchor2);
  var link=Create(code,"Preparation.MountConnection");Set(link,"AnchorA",Get(anchor,"Id"));Set(link,"AnchorB",Get(anchor2,"Id"));((IList)Get(project,"Connections")).Add(link);
  Set(project,"FrameBuildReceipt","old-frame");Set(project,"LastBuildReceipt","old-package");Set(project,"PhysicsBuildReceipt","old-physics");Set(project,"PhysicsTemplateReceipt","old-template");
  Call(project,"Save");Save(source,sourcePath);files.Add(PathOf(project));
  // A body saved inside a lightweight component must resolve before selection.
  var highlight=Create(code,"Preparation.FrameAssignment");Set(highlight,"Configuration",source.ConfigurationManager.ActiveConfiguration.Name);
  var highlightRef=Create(code,"Preparation.SelectionReference");object bodyInfo;var highlightBody=((object[])instances[1].GetBodies3(-1,out bodyInfo))[0];
  Set(highlightRef,"Kind","body");Set(highlightRef,"Name","Lightweight saved body");Set(highlightRef,"Reference",Convert.ToBase64String((byte[])source.Extension.GetPersistReference3(highlightBody)));Set(highlightRef,"ComponentReference",Convert.ToBase64String((byte[])source.Extension.GetPersistReference3(instances[1])));((IList)Get(highlight,"Selections")).Add(highlightRef);
  instances[1].SetSuppression2((int)swComponentSuppressionState_e.swComponentLightweight);
  Check(instances[1].GetSuppression2()==(int)swComponentSuppressionState_e.swComponentLightweight,"saved-body fixture is genuinely lightweight");
  Call(selection,"Show",highlight);Check(((SelectionMgr)source.SelectionManager).GetSelectedObjectCount2(-1)==1,"highlight loads a saved lightweight body's owner before resolving the body");
  source.ClearSelection2(true);Save(source,sourcePath);
  var before=files.ToDictionary(x=>x,Hash);var expected=((IEnumerable)groups).Cast<object>().Take(3).Select(g=>Bodies(selection,g).Select(b=>Properties(b.Item2,b.Item1)).ToArray()).ToArray();
  var sourceTextureScale=new Dictionary<int,double[]>();
  foreach(var index in new[]{0,2}){
   var pair=Bodies(selection,groups[index]).Single();var reader=Create(code,"Preparation.SolidWorksAppearances",app,pair.Item1,pair.Item2);
   var material=(RenderMaterial)Call(reader,"ReadNative",((object[])pair.Item2.GetFaces()).Cast<Face2>().First());
   Check(material!=null&&material.PrimaryColor==(index==0?0x336633:0xffffff),"source render fixture has intended colour before copy "+index+"; actual="+(material==null?"missing":material.PrimaryColor.ToString()));
   sourceTextureScale[index]=new[]{material.Width,material.Height};
   if(index==2)Check(File.Exists(material.TextureFilename)&&Hash(material.TextureFilename)==Hash(texturePath)&&material.Width>0&&material.Height>0,"source fixture has a saved texture and positive mapping size");
  }
  var service=Create(code,"Preparation.AssociationAssembly",app,source);var destination=System.IO.Path.Combine(folder,"working");var values=new List<int>();
  var result=Wait(Call(service,"Create",project,destination,new Action<int,string>((p,s)=>{values.Add(p);Console.WriteLine(p+"% "+s);}),System.Threading.CancellationToken.None));
  var output=(ModelDoc2)Get(result,"Document");var copy=Get(result,"Project");var copied=((IEnumerable)Get(copy,"Components")).Cast<object>().ToArray();
  Check(before.All(p=>Hash(p.Key)==p.Value),"source CAD and source project bytes unchanged");
  Check(!source.GetSaveFlag(),"source document not dirtied by snapshot");
  Check(copied.Length==4&&copied.Select(c=>(string)Get(c,"Id")).SequenceEqual(((IEnumerable)groups).Cast<object>().Select(c=>(string)Get(c,"Id"))),"all group IDs preserved including unassigned group");
  Check((string)Get(Get(copy,"Identity"),"Id")!=(string)Get(Get(project,"Identity"),"Id"),"working project gets independent mod identity");
  Check(new[]{"LastBuildReceipt","FrameBuildReceipt","PhysicsBuildReceipt","PhysicsTemplateReceipt"}.All(n=>string.IsNullOrEmpty((string)Get(copy,n))),"old build qualification is not carried across new native identities");
  Check(values.Last()==100&&values.Zip(values.Skip(1),(a,b)=>b>=a).All(v=>v),"progress reaches completion monotonically");
  var outputSelection=Create(code,"Preparation.FrameSelection",app,output,true);
  for(var i=0;i<3;i++){
   var bodies=Bodies(outputSelection,copied[i]);Check(bodies.Count==1,"group "+i+" imports only its tagged body without duplicate appearances");Near(Properties(bodies[0].Item2,bodies[0].Item1),expected[i][0],"group "+i+" preserves placed geometry properties");
   var part=(PartDoc)bodies[0].Item1.GetModelDoc2();var native=((object[])part.GetBodies2(-1,false)).Cast<Body2>().Single();string materialDb;
   Check(native.GetMaterialPropertyName(bodies[0].Item1.ReferencedConfiguration,out materialDb)=="AISI 4130 Steel, normalized at 870C","group "+i+" preserves native physical material");
   var features=new List<string>();for(var f=(Feature)((ModelDoc2)part).FirstFeature();f!=null;f=(Feature)f.GetNextFeature())features.Add(f.GetTypeName2());
   Check(!features.Contains("3DProfileFeature"),"group "+i+" excludes source reference sketches");
  }
  Check((double)Get(copied[2],"Thickness")==.002&&(string)Get(copied[2],"SurfaceMassMode")=="ignore","surface mass settings retained");
  var pieces=(IList)Get(Get(copied[1],"AppearanceCoilover"),"Pieces");Check(pieces.Count==1&&(string)Get(pieces[0],"SourceDocument")==output.GetPathName(),"incomplete coilover assignment preserved and rebound without inventing pieces");
  Check((string)Get(Get(copied[1],"CoiloverSpring"),"Mode")=="dual","coilover settings retained");
  var prep=code.GetType("BeamNG.Cad.Preparation.PreparationFile").GetMethod("Load").Invoke(null,new object[]{output.GetPathName()});Check(Call(prep,"Frame",output.ConfigurationManager.ActiveConfiguration.Name)!=null,"frame definition rebound and saved for native frame workflow");
  Check(((IEnumerable)Get(copy,"Anchors")).Cast<object>().All(a=>(string)Get(a,"Status")=="needs_repair")&&((IList)Get(copy,"Connections")).Count==1,"existing mounts and connection topology retained with explicit repair status");
  Check(((object[])((AssemblyDoc)output).GetComponents(true)).Length==3,"assembly contains only assigned groups");
  var outputPath=output.GetPathName();var projectPath=PathOf(copy);app.CloseDoc(output.GetTitle());int e=0,w=0;
  output=(ModelDoc2)app.OpenDoc6(outputPath,2,1,"",ref e,ref w);app.ActivateDoc3(output.GetTitle(),false,0,ref error);
  copy=projectType.GetMethod("Load").Invoke(null,new object[]{projectPath});copied=((IEnumerable)Get(copy,"Components")).Cast<object>().ToArray();outputSelection=Create(code,"Preparation.FrameSelection",app,output,true);
  Check(copied.Take(3).All(c=>Bodies(outputSelection,c).Count==1),"native associations resolve after document close / reopen");
  foreach(var index in new[]{0,2}){
   var pair=Bodies(outputSelection,copied[index]).Single();var reader=Create(code,"Preparation.SolidWorksAppearances",app,pair.Item1,pair.Item2);var face=((object[])pair.Item2.GetFaces()).Cast<Face2>().First();
   var material=(RenderMaterial)Call(reader,"ReadNative",face);Check(material!=null,"working group "+index+" retains a native render appearance after reopen");
   Check(material.PrimaryColor==(index==0?0x336633:0xffffff),"assembly render override colour survives copy "+index+"; actual="+material.PrimaryColor);
   if(index==2){Check(File.Exists(material.TextureFilename)&&Hash(material.TextureFilename)==Hash(texturePath)&&material.TextureFilename.StartsWith(destination,StringComparison.OrdinalIgnoreCase),"texture asset is copied beside the working CAD with identical bytes");Check(Math.Abs(material.Width-sourceTextureScale[index][0])<1e-9&&Math.Abs(material.Height-sourceTextureScale[index][1])<1e-9,"texture scale survives native save and reopen; source="+string.Join(",",sourceTextureScale[index])+" copied="+material.Width+","+material.Height);}
  }
  var bitmap=System.IO.Path.Combine(folder,"working-assembly.bmp");output.ShowNamedView2("*Isometric",7);output.ViewZoomtofit2();output.GraphicsRedraw2();Application.DoEvents();if(output.SaveBMP(bitmap,0,0)){using(var image=new System.Drawing.Bitmap(bitmap))image.Save(System.IO.Path.Combine(folder,"working-assembly.png"),System.Drawing.Imaging.ImageFormat.Png);File.Delete(bitmap);}
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);bool refused=false;try{Wait(Call(service,"Create",project,destination,null,System.Threading.CancellationToken.None));}catch(Exception){refused=true;}Check(refused,"existing destination cannot be overwritten");
  var cancelled=System.IO.Path.Combine(folder,"cancelled");var token=new System.Threading.CancellationToken(true);refused=false;try{Wait(Call(service,"Create",project,cancelled,null,token));}catch(Exception){refused=true;}Check(refused&&app.IsSame(app.ActiveDoc,source)==(int)swObjectEquality.swObjectSame,"cancellation restores source document and does not alter associations");
  Check(before.All(p=>Hash(p.Key)==p.Value),"source files unchanged after failure and cancellation checks");
  File.WriteAllText(System.IO.Path.Combine(folder,"result.txt"),"PASS native working assembly and mounting datum checks");
 }
}
'@
Add-Type -ReferencedAssemblies $refs -TypeDefinition $source
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
$ownedPid=$null
try {
 $process=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS\sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
 $ownedPid=$process.Id
 if($existing -contains $ownedPid){throw 'Refusing existing user process'}
 $until=(Get-Date).AddSeconds(120)
 do {$app=[SyntheticNativeCad]::Find($ownedPid);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and (Get-Date) -lt $until)
 if(-not $app){throw 'Owned SolidWorks did not register'}
 Write-Output "OWNED_CAD_PROCESS=$ownedPid"
 [SyntheticNativeCad]::GuardOwnedPrompt($ownedPid)
 if($SyncFixture){
  if(-not (Test-Path -LiteralPath (Join-Path $SyncFixture 'result.txt'))){throw 'SyncFixture must be an owned completed native fixture'}
  [WorkingAssemblyTest]::Sync($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),(Resolve-Path -LiteralPath $SyncFixture).Path)
 }
 elseif($ReviewFixture){[WorkingAssemblyTest]::Review($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination,(Resolve-Path -LiteralPath $ReviewFixture).Path)}
 else {[WorkingAssemblyTest]::Run($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination); if($SyncTest){[WorkingAssemblyTest]::Sync($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination)}}
 } catch {
 Write-Output $_.Exception.ToString()
 throw
 } finally {
 if($ownedPid -and $existing -notcontains $ownedPid){
  try{if($app){[SyntheticNativeCad]::Finish($app)}}catch{Write-Warning ('Owned test cleanup: '+$_.Exception.Message)}
  $remaining=Get-Process -Id $ownedPid -ErrorAction SilentlyContinue
  if($remaining -and -not $remaining.WaitForExit(10000)){Stop-Process -Id $ownedPid -ErrorAction SilentlyContinue}
 }
}
