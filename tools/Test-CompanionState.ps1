param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new test directory'}
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing','System.Runtime.Serialization' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Windows.Forms;
using System.Drawing;
public static class CompanionStateTest {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Set(object o,string n,object v){o.GetType().GetField(n).SetValue(o,v);}
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine("PASS "+label);}
 static object New(Assembly code,string n){return Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation."+n),true);}
 public static void Run(string dll,string folder){
  var code=Assembly.LoadFrom(dll);var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var link=code.GetType("BeamNG.Cad.Preparation.CompanionAssemblyLink");
  Func<string,object> make=name=>{var path=Path.Combine(folder,name+".SLDASM");File.WriteAllText(path,"Test placeholder; never opened in CAD");return projectType.GetMethod("Open").Invoke(null,new object[]{path});};
  Func<object,string> pathOf=p=>(string)projectType.GetProperty("FilePath").GetValue(p,null);
  Action<object> save=p=>projectType.GetMethod("Save").Invoke(p,null);
  Func<string,object> load=p=>projectType.GetMethod("Load").Invoke(null,new object[]{p});
  var source=make("source");var companion=make("companion");var group=New(code,"ComponentDefinition");var groups=(IList)Get(source,"Components");groups.Add(group);save(source);save(companion);
  var receipt=New(code,"AssociationAssembly+Receipt");Set(receipt,"Status","completed");Set(receipt,"SourceProject",pathOf(source));Set(receipt,"SourceDocument",Get(source,"SourceDocument"));Set(receipt,"Project",pathOf(companion));Set(receipt,"Assembly",Get(companion,"SourceDocument"));
  var receiptPath=Path.Combine(folder,"working-assembly.json");
  Action baseline=()=>{var saved=load(pathOf(source));Set(receipt,"SourceComponents",Get(saved,"Components"));Set(receipt,"SourceTemplates",Get(saved,"MvpTemplates"));code.GetType("BeamNG.Cad.Preparation.JsonFile").GetMethod("Write").MakeGenericMethod(receipt.GetType()).Invoke(null,new[]{(object)receiptPath,receipt});};
  baseline();link.GetMethod("Register").Invoke(null,new[]{(object)receiptPath});
  Func<object,string> status=p=>(string)link.GetMethod("Status").Invoke(null,new[]{p,(object)receiptPath});
  Action pending=()=>{save(source);Check(status(source).Contains("updates pending"),"saved assignment change is pending");baseline();Check(status(source).StartsWith("Saved assignments are synchronized"),"updated baseline clears pending state");};
  Check((string)link.GetMethod("Find").Invoke(null,new[]{load(pathOf(source))})==receiptPath&&(string)link.GetMethod("Find").Invoke(null,new[]{load(pathOf(companion))})==receiptPath,"links survive independent project reload");
  Check(status(source).StartsWith("Saved assignments are synchronized"),"unchanged source starts synchronized");
  Set(group,"Name","Renamed");pending();
  Set(group,"Thickness",.003);pending();
  var reference=New(code,"SelectionReference");Set(reference,"Kind","body");Set(reference,"Reference","durable body reference");((IList)Get(group,"Selections")).Add(reference);pending();
  Set(group,"Configuration","Variant");pending();
  Set(group,"SurfaceMassMode","ignore");pending();
  var added=New(code,"ComponentDefinition");Set(added,"Name","RL number Panel");groups.Add(added);save(source);Check(status(companion).Contains("1 added")&&status(companion).Contains("RL number Panel")&&status(companion).Contains("Use Update companion assembly"),"companion names uncopied groups and the action needed, including changes saved by another workflow");baseline();
  groups.RemoveAt(0);groups.Add(group);save(source);Check(status(source).Contains("order changed"),"order-only edits are pending");baseline();
  groups.Remove(added);save(source);Check(status(source).Contains("1 removed"),"removed source groups are pending");baseline();
  var choices=(IList)Get(source,"MvpTemplates");var choice=New(code,"MvpTemplateChoice");Set(choice,"Category","rear_suspension");Set(choice,"Template","trailing_radius_toe");choices.Add(choice);save(source);Check(status(source).Contains("vehicle layout changed"),"template configuration changes are pending");baseline();
  Set(group,"GeometryDirectory","generated-cache");Set(group,"AppearanceDirectory","generated-appearance");Set(group,"AppearancePackageState","failed");Set(group,"AppearancePackageError","worker diagnostic");save(source);Check(status(source).StartsWith("Saved assignments are synchronized"),"export cache and packaging statuses do not trigger geometry changes");
  var older=make("older");save(older);Check(status(older).Contains("earlier companion revision"),"older revisions direct the user to the latest companion");
  bool refused=false;try{link.GetMethod("Attach").Invoke(null,new[]{older,(object)receiptPath});}catch(TargetInvocationException e){refused=e.InnerException is InvalidOperationException;}Check(refused,"unrelated project cannot claim a companion link");
  Set(receipt,"SourceComponents",null);code.GetType("BeamNG.Cad.Preparation.JsonFile").GetMethod("Write").MakeGenericMethod(receipt.GetType()).Invoke(null,new[]{(object)receiptPath,receipt});Check(status(source).Contains("First update"),"legacy receipt offers tracking upgrade");baseline();
  var original=File.ReadAllBytes(receiptPath);var next=make("next");save(next);Set(receipt,"Project",pathOf(next));Set(receipt,"Assembly",Get(next,"SourceDocument"));
  Directory.CreateDirectory(pathOf(next)+".companion.json");refused=false;try{link.GetMethod("Promote",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new[]{(object)receiptPath,receipt});}catch(TargetInvocationException){refused=true;}
  Check(refused&&original.SequenceEqual(File.ReadAllBytes(receiptPath)),"failed sidecar write cannot promote new assembly revision");
  var panelType=code.GetType("BeamNG.Cad.UI.CompanionAssemblyPanel");
  using(var form=new Form {Width=650,Height=320})using(var panel=(Control)Activator.CreateInstance(panelType,true)){
   form.Controls.Add(panel);form.Show();Application.DoEvents();
   var opens=0;var updates=0;panelType.GetEvent("OpenRequested").AddEventHandler(panel,new Action(()=>opens++));panelType.GetEvent("UpdateRequested").AddEventHandler(panel,new Action(()=>updates++));
   var open=(Button)panel.Controls.Find("OpenCompanion",true).Single();var update=(Button)panel.Controls.Find("UpdateCompanion",true).Single();var geometry=(CheckBox)panel.Controls.Find("RefreshCompanionGeometry",true).Single();
   panelType.GetMethod("SetState").Invoke(panel,new object[]{false,"No companion linked"});Check(!open.Enabled&&update.Enabled,"unlinked project can choose existing companion but cannot open stale path");
   Check(!(bool)panelType.GetProperty("RefreshGeometry").GetValue(panel,null),"geometry replacement is opt-in");
   panelType.GetMethod("SetState").Invoke(panel,new object[]{true,"Companion updates pending: 1 added, 1 removed, 2 changed."});open.PerformClick();update.PerformClick();Check(opens==1&&updates==1,"open and update actions dispatch separately");
   geometry.Checked=true;Check((bool)panelType.GetProperty("RefreshGeometry").GetValue(panel,null),"explicit geometry refresh choice reaches caller");
   Application.DoEvents();Check(panel.Width<form.ClientSize.Width&&panel.Height<form.ClientSize.Height,"companion controls fit compact workflow width");
   using(var bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(0,0,bitmap.Width,bitmap.Height));bitmap.Save(Path.Combine(folder,"companion-controls.png"));}
  }
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS companion state, promotion and UI checks");
 }
}
'@
[CompanionStateTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination)
