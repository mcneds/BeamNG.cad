param(
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [Parameter(Mandatory=$true)][string]$Destination,
 [Parameter(Mandatory=$true)][ValidateSet('Write','Read')][string]$Phase
)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing','System.Runtime.Serialization' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
public static class FrameAssignmentWorkflowTest {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Put(object o,string n,object v){var f=o.GetType().GetField(n);if(f!=null)f.SetValue(o,v);else o.GetType().GetProperty(n).SetValue(o,v);}
 static object New(Assembly a,string n){return Activator.CreateInstance(a.GetType("BeamNG.Cad."+n),true);}
 static object Call(object o,string n,params object[] args){return o.GetType().GetMethod(n).Invoke(o,args);}
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine("PASS "+label);}
 static Control Find(Control c,string n){return c.Controls.Find(n,true).Single();}
 public static void Run(string dll,string folder,string phase){
  var code=Assembly.LoadFrom(dll);var doc=Path.Combine(folder,"fixture.SLDASM");
  var prep=code.GetType("BeamNG.Cad.Preparation.PreparationFile");var projects=code.GetType("BeamNG.Cad.Preparation.VehicleProject");
  var assignments=code.GetType("BeamNG.Cad.Preparation.ComponentAssignments");
  if(phase=="Write"){
   if(File.Exists(doc))throw new Exception("Use a fresh owned fixture directory");File.WriteAllText(doc,"Persistence test only; never opened in CAD");
   var frame=New(code,"Preparation.FrameAssignment");Put(frame,"Id","stable-frame-id");Put(frame,"Configuration","Default");
   var reference=New(code,"Preparation.SelectionReference");Put(reference,"Kind","body");Put(reference,"Reference","durable-body-reference");Put(reference,"ComponentReference","durable-component-reference");Put(reference,"Name","Frame tubes");((IList)Get(frame,"Selections")).Add(reference);
   Put(Get(frame,"Hull"),"Width",9);Put(Get(frame,"Hull"),"ProxyDivisor",8d);Put(Get(frame,"Hull"),"Symmetry",true);
   var definitions=prep.GetMethod("Load").Invoke(null,new object[]{doc});Call(definitions,"Save",frame);
   var other=New(code,"Preparation.FrameAssignment");Put(other,"Configuration","Alternative");Call(definitions,"Save",other);
   var project=projects.GetMethod("Open").Invoke(null,new object[]{doc});
   var group=New(code,"Preparation.ComponentDefinition");Put(group,"Id","saved-project-frame");Put(group,"Name","My frame");Put(group,"Template","calibrated_frame");Put(group,"MvpRole","frame");Put(group,"Hull",Get(frame,"Hull"));
   assignments.GetMethod("Physical").Invoke(null,new object[]{project,group,frame,new List<string>{"frame-body-id"},doc});((IList)Get(project,"Components")).Add(group);
   var role=New(code,"Preparation.MvpRole");Put(role,"Id","frame");Put(role,"Label","Frame");Put(role,"Representation","calibrated_frame");
   var created=assignments.GetMethod("CreateGroup").Invoke(null,new[]{project,role});
   Check((string)Get(created,"MvpRole")==""&&(string)Get(created,"Template")=="auto","new group after frame selection does not inherit the protected frame role");
   Put(role,"Id","panel");Put(role,"Label","Body panel");Put(role,"Representation","panel");Put(role,"Repeatable",true);
   var left=assignments.GetMethod("CreateNamedGroup").Invoke(null,new[]{project,role,(object)"  Left body panel  "});var right=assignments.GetMethod("CreateNamedGroup").Invoke(null,new[]{project,role,(object)"Right body panel"});
   Check((string)Get(left,"Name")=="Left body panel"&&(string)Get(right,"Name")=="Right body panel","new groups preserve entered names and trim surrounding whitespace");
   Check((string)Get(group,"Name")=="My frame","naming a new group never renames the selected existing frame");
   Check((string)Get(left,"Name")!=""&&(string)Get(right,"Name")!=(string)Get(left,"Name"),"repeated panels have distinct names");
   Check((string)Get(left,"Template")=="panel"&&(string)Get(right,"MvpRole")=="panel","repeated panel groups retain their role and representation");
   Call(project,"Save");
   Check(((IList)Get(created,"Selections")).Count==0&&((IList)Get(left,"Selections")).Count==0,"new empty groups save without requiring a CAD selection");
   File.WriteAllText(Path.Combine(folder,"writer-pid.txt"),System.Diagnostics.Process.GetCurrentProcess().Id.ToString());return;
  }
  Check(File.ReadAllText(Path.Combine(folder,"writer-pid.txt"))!=System.Diagnostics.Process.GetCurrentProcess().Id.ToString(),"definition restored in a different process");
  var preparation=prep.GetMethod("Load").Invoke(null,new object[]{doc});var saved=Call(preparation,"Frame","Default");
  Check((string)Get(saved,"Id")=="stable-frame-id"&&((IList)Get(saved,"Selections")).Count==1,"frame identity and selection survive process restart");
  var savedRef=((IList)Get(saved,"Selections"))[0];
  Check((string)Get(savedRef,"Reference")=="durable-body-reference"&&(string)Get(savedRef,"ComponentReference")=="durable-component-reference","body and owning-component persistent references restored exactly");
  Check((int)Get(Get(saved,"Hull"),"Width")==9&&(double)Get(Get(saved,"Hull"),"ProxyDivisor")==8d&&(bool)Get(Get(saved,"Hull"),"Symmetry"),"frame hull settings restored exactly");
  Check(Call(preparation,"Frame","Alternative")!=null&&Call(preparation,"Frame","Missing")==null,"frame definitions remain scoped to their saved configuration");
  var projectPath=doc+".beamng-project.json";var bytes=File.ReadAllBytes(projectPath);var prepBytes=File.ReadAllBytes(doc+".truemesh-prep.json");
  var loaded=projects.GetMethod("Load").Invoke(null,new object[]{projectPath});var groups=((IEnumerable)Get(loaded,"Components")).Cast<object>().ToArray();var frameGroup=groups.Single(c=>(string)Get(c,"MvpRole")=="frame");
  Check(groups.Length==4&&groups.Count(c=>(string)Get(c,"MvpRole")=="panel")==2,"new component and both empty panel groups survive restart");
  Check(groups.Any(c=>(string)Get(c,"Name")=="Left body panel")&&groups.Any(c=>(string)Get(c,"Name")=="Right body panel"),"entered group names survive immediate save and process restart");
  Check((string)Get(frameGroup,"Id")=="saved-project-frame"&&((IList)Get(frameGroup,"BodyIds")).Count==1&&((IList)Get(frameGroup,"Selections")).Count==1,"linked project frame reloads without redefining or packaging");
  var groupState=assignments.GetMethod("State").Invoke(null,new[]{loaded,frameGroup,(object)false});Check((string)groupState=="saved","reloaded frame is reported as assigned");
  using(var form=new Form {Width=960,Height=660,Text="Frame assignment and component search"})
  using(var panel=(Control)New(code,"UI.FrameAssignmentPanel"))
  using(var list=(ListBox)New(code,"UI.ComponentAssignmentList")){
   panel.Location=new Point(355,15);list.Dock=DockStyle.Left;list.Width=330;form.Controls.Add(panel);form.Controls.Add(list);form.Show();
   Action<string,string> filter=(q,id)=>Call(list,"ShowComponents",Get(loaded,"Components"),q,id);
   filter("PANEL body",null);Check(list.Items.Count==2,"search matches name words regardless of order or case");
   var panels=groups.Where(c=>(string)Get(c,"MvpRole")=="panel").ToArray();Put(panels[0],"Name","Nose cone");Put(panels[1],"Name","Side cover");
   filter("body",null);Check(list.Items.Count==2,"body finds the Body panel role even when neither custom name contains body");
   filter("BODY nose",null);Check(list.Items.Count==1&&list.SelectedItem==panels[0],"search combines displayed role and custom name without case sensitivity");
   var housing=groups.Single(c=>(string)Get(c,"MvpRole")=="");Put(housing,"Name","Gearcase");Put(housing,"MvpRole","rear_final_drive");
   filter("differential",null);Check(list.Items.Count==1&&list.SelectedItem==housing,"displayed catalog labels are searched for other component roles too");
   filter("calibrated frame",null);Check(list.Items.Count==1&&(string)Get(list.SelectedItem,"Id")=="saved-project-frame","search accepts frame representation and readable role words");
   filter("missinggroup",null);Check(list.Items.Count==0&&list.SelectedItem==null,"no matches cannot leave an invisible selected component");
   filter("","saved-project-frame");Check(list.Items.Count==4&&(string)Get(list.SelectedItem,"Id")=="saved-project-frame","clearing search restores all groups and selected identity");
   Call(panel,"SetState",true,"Default",saved,"saved",new string[0],null);Application.DoEvents();
   Check(Find(panel,"UseSavedFrame").Enabled&&Find(panel,"SavedFrameState").Text.Contains("restarting SolidWorks"),"saved frame offers direct reuse and explains persistence");
   using(var bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(0,0,bitmap.Width,bitmap.Height));bitmap.Save(Path.Combine(folder,"saved-frame.png"));}
   Call(panel,"SetState",true,"Missing",null,"missing",new[]{"Default"},null);
   Check(!Find(panel,"UseSavedFrame").Enabled&&Find(panel,"DefineFrame").Enabled&&Find(panel,"SavedFrameState").Text.Contains("Default"),"missing configuration offers definition and identifies the existing saved configuration");
   Call(panel,"SetState",true,"Default",null,"saved",new string[0],"Test read error");
   Check(!Find(panel,"UseSavedFrame").Enabled&&Find(panel,"SavedFrameState").Text.Contains("Test read error"),"unreadable definition is reported without claiming it is missing");
   Call(panel,"SetState",false,"Default",saved,"saved",new string[0],null);Check(!panel.Visible,"frame-specific instructions are hidden for ordinary components");form.Close();
  }
  Check(File.ReadAllBytes(projectPath).SequenceEqual(bytes)&&File.ReadAllBytes(doc+".truemesh-prep.json").SequenceEqual(prepBytes),"searching and viewing frame status do not modify saved assignments");
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS: separate-process frame/group persistence and assignment/search UI");
 }
}
'@
[FrameAssignmentWorkflowTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination),$Phase)
