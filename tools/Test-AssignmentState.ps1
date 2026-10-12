param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing','System.Web.Extensions','System.Runtime.Serialization','System.Xml' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Reflection;
using System.Drawing;
using System.Windows.Forms;
using System.Web.Script.Serialization;
public static class AssignmentStateTest {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Put(object o,string n,object value){o.GetType().GetField(n).SetValue(o,value);}
 static object New(Assembly code,string n){return Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation."+n),true);}
 static void Check(bool value,string text){if(!value)throw new Exception(text);Console.WriteLine("PASS "+text);}
 public static void Run(string dll,string output){
  var artifacts=output;output=Path.Combine(output,"case-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(output);
  var code=Assembly.LoadFrom(dll);var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");
  var document=Path.Combine(output,"test.SLDASM");File.WriteAllText(document,"Test placeholder; never opened in CAD");
  var project=projectType.GetMethod("Open").Invoke(null,new object[]{document});
  var catalog=code.GetType("BeamNG.Cad.Preparation.MvpCatalog").GetMethod("Load").Invoke(null,null);
  var state=code.GetType("BeamNG.Cad.Preparation.ComponentAssignments");
  var component=New(code,"ComponentDefinition");Put(component,"Name","Final drive");((IList)Get(project,"Components")).Add(component);
  var selection=New(code,"FrameAssignment");Put(selection,"Configuration","Default");
  var reference=New(code,"SelectionReference");Put(reference,"Reference","opaque-reference");Put(reference,"Kind","body");Put(reference,"Name","Selected body");((IList)Get(selection,"Selections")).Add(reference);
  state.GetMethod("UpdateStatus").Invoke(null,new[]{project});Check(((string)component.GetType().GetProperty("AssignmentSummary").GetValue(component)).Contains("Appearance: unassigned"),"empty row never appears assigned");
  state.GetMethod("Appearance").Invoke(null,new object[]{component,selection,document});
  state.GetMethod("UpdateStatus").Invoke(null,new[]{project});
  Check((string)component.GetType().GetProperty("AssignmentSummary").GetValue(component)=="CAD: unassigned | Appearance: custom (pending)","visual assignment does not imply physical ownership");
  Put(reference,"Reference","mutated-input");Check((string)Get(((IList)Get(component,"AppearanceSelections"))[0],"Reference")=="opaque-reference","assignment retains a copy of durable references");
  projectType.GetMethod("Save").Invoke(project,null);var path=(string)projectType.GetProperty("FilePath").GetValue(project);
  var reloaded=projectType.GetMethod("Load").Invoke(null,new object[]{path});var restored=((IList)Get(reloaded,"Components"))[0];
  Check((string)Get(restored,"AppearanceSourceDocument")==document&&(string)Get(restored,"AppearancePackageState")=="pending"&&((IList)Get(restored,"AppearanceSelections")).Count==1,"pending assignment survives disk reload without an export");
  var original=File.ReadAllBytes(path);var originalProfile=File.ReadAllBytes(path+".profile.json");
  var fresh=projectType.GetMethod("StartFresh").Invoke(project,new object[]{Path.Combine(output,"fresh.json"),catalog,true});
  var groups=((IEnumerable)Get(fresh,"Components")).Cast<object>().ToList();
  Check(groups.Count>20&&groups.All(c=>((IList)Get(c,"Selections")).Count==0&&((IList)Get(c,"AppearanceSelections")).Count==0),"fresh layout groups contain no inherited assignments");
  Check(new[]{"LastBuildReceipt","FrameBuildReceipt","PhysicsBuildReceipt","PhysicsTemplateReceipt","TemplateDefinitionPath"}.All(n=>string.IsNullOrEmpty((string)Get(fresh,n))),"fresh project contains no prior build or hardpoint references");
  Check((string)Get(Get(fresh,"Identity"),"Namespace")!=(string)Get(Get(project,"Identity"),"Namespace"),"fresh project has its own mod identity");
  Check(File.ReadAllBytes(path).SequenceEqual(original)&&File.ReadAllBytes(path+".profile.json").SequenceEqual(originalProfile),"fresh project preserves the original project and mod settings");
  try{projectType.GetMethod("StartFresh").Invoke(project,new object[]{path,catalog,true});throw new Exception("Expected refusal");}catch(TargetInvocationException e){Check(e.InnerException is IOException,"fresh project refuses an existing filename");}
  var empty=projectType.GetMethod("StartFresh").Invoke(project,new object[]{Path.Combine(output,"empty.json"),catalog,false});Check(((IList)Get(empty,"Components")).Count==0,"factory also supports a completely empty group list");
  var other=New(code,"ComponentDefinition");Put(other,"Name","Imported engine");Put(other,"Selections",Get(selection,"Selections"));Put(other,"CadSourceDocument",Path.Combine(output,"synthetic.SLDASM"));((IList)Get(project,"Components")).Add(other);
  state.GetMethod("UpdateStatus").Invoke(null,new[]{project});Check(((string)other.GetType().GetProperty("AssignmentSummary").GetValue(other)).Contains("CAD: other assembly"),"imported CAD cannot masquerade as this assembly's assignment");
  var physical=New(code,"ComponentDefinition");Put(physical,"Name","CAD appearance");Put(physical,"Selections",Get(selection,"Selections"));Put(physical,"CadSourceDocument",document);((IList)Get(project,"Components")).Add(physical);
  state.GetMethod("UpdateStatus").Invoke(null,new[]{project});Check(((string)physical.GetType().GetProperty("AssignmentSummary").GetValue(physical)).Contains("Appearance: uses CAD"),"physical CAD supplies the default appearance without a false missing warning");
  var split=New(code,"CoiloverAppearance");var piece=New(code,"CoiloverMeshAssignment");Put(piece,"Kind","shaft");Put(piece,"Selections",Get(selection,"Selections"));((IList)Get(split,"Pieces")).Add(piece);Put(physical,"AppearanceCoilover",split);Put(physical,"AppearancePackageState","pending");
  state.GetMethod("UpdateStatus").Invoke(null,new[]{project});Check(((string)physical.GetType().GetProperty("AssignmentSummary").GetValue(physical)).Contains("Appearance: coilover 1/3 (pending)"),"incomplete moving-piece assignments are distinguished from CAD fallback");
  using(var form=new Form {Text="Saved assignment status",Width=850,Height=650}){
   var list=(ListBox)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.ComponentAssignmentList"),true);list.Dock=DockStyle.Left;list.Width=285;list.DataSource=((IEnumerable)Get(project,"Components")).Cast<object>().Concat(groups.Take(8)).ToList();
   form.Controls.Add(list);form.Show();Application.DoEvents();
   Check(list.GetItemText(component).Contains("Appearance: custom (pending)"),"accessible row text contains assignment status");
   foreach(var size in new[]{8.25f,10f,12f})using(var font=new Font("Segoe UI",size)){form.Font=font;form.PerformLayout();Application.DoEvents();Check(list.ItemHeight>=2*font.Height+4,"two-line status rows fit at "+size+"pt");form.Font=SystemFonts.MessageBoxFont;}
   using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(Point.Empty,image.Size));image.Save(Path.Combine(artifacts,"assignment-status.png"));}
   form.Close();
  }
 }
}
'@
[AssignmentStateTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
