param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a fresh owned fixture directory'}
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing','System.Runtime.Serialization' -TypeDefinition @'
using System;
using System.IO;
using System.Collections;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
public static class DrivelineTest {
 static object New(Assembly code,string name){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+name),true);}
 static object Get(object o,string name){var flags=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance;var p=o.GetType().GetProperty(name,flags);return p!=null?p.GetValue(o,null):o.GetType().GetField(name,flags).GetValue(o);}
 static void Set(object o,string name,object value){var p=o.GetType().GetProperty(name);if(p!=null)p.SetValue(o,value,null);else o.GetType().GetField(name).SetValue(o,value);}
 static object Call(object o,string name,params object[] args){return o.GetType().GetMethod(name,BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance).Invoke(o,args);}
 static void Check(bool ok,string message){if(!ok)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static void RouteForm(Control panel,bool accept,bool ideal,object original=null){
  using(var timer=new Timer()){
   timer.Interval=60;
   timer.Tick+=(s,e)=>{
    var dialog=Application.OpenForms.Cast<Form>().FirstOrDefault(f=>f.Text=="Connect device ports");
    if(dialog==null)return;
    timer.Stop();
    var owner=(ComboBox)dialog.Controls.Find("RouteOwner",true)[0];owner.SelectedIndex=ideal?1:0;
    if(ideal){((ComboBox)dialog.Controls.Find("RoutePlunge",true)[0]).SelectedIndex=1;dialog.Controls.Find("RouteHalfTravel",true)[0].Text="0.025";}
    dialog.DialogResult=accept?DialogResult.OK:DialogResult.Cancel;dialog.Close();
   };
   timer.Start();Call(panel,"RouteDialog",new object[]{original});
  }
 }
 static void RouteWorkflow(Assembly code,Control panel,object project){
  var graph=New(code,"Preparation.Driveline");Set(graph,"Version",2);
  foreach(var id in new[]{"diff","wheel","halfshaft"}){
   var comp=New(code,"Preparation.ComponentDefinition");Set(comp,"Id",id);Set(comp,"Name",id);((IList)Get(project,"Components")).Add(comp);
   if(id=="halfshaft")continue;
   var device=New(code,"Preparation.DriveDevice");Set(device,"Component",id);Set(device,"Name",id);Set(device,"Type",id=="diff"?"differential":"wheel");
   var endpoint=New(code,"Preparation.DriveEndpoint");Set(endpoint,"Component",id);((IList)Get(graph,"Endpoints")).Add(endpoint);
   var port=New(code,"Preparation.DrivePort");Set(port,"Direction",id=="diff"?"output":"input");Set(port,"Endpoint",Get(endpoint,"Id"));((IList)Get(device,"Ports")).Add(port);((IList)Get(graph,"Devices")).Add(device);
  }
  Set(project,"Driveline",graph);Call(panel,"Configure",project,true);
  var routes=(ListBox)panel.Controls.Find("DrivelineRoutes",true)[0];
  Check(routes.Visible && routes.Height>250 && routes.Items.Count==1,"Routes opens first and the narrow pane gives the route list working height");
  RouteForm(panel,false,true);
  Check(!(bool)Get(panel,"HasChanges") && ((IList)Get(Get(panel,"Draft"),"Shafts")).Count==0,"cancelling a bounded shaft leaves the draft unchanged");
  RouteForm(panel,true,true);
  var edited=Get(panel,"Draft");var shaft=((IList)Get(edited,"Shafts"))[0];
  Check((string)Get(shaft,"Representation")=="ideal" && (double)Get(shaft,"HalfTravel")==.025 && ((IList)Get(edited,"Endpoints")).Count==2,"Connect ports reuses both device endpoints for an ideal shaft");
  Check(routes.Items[0].ToString().Contains("halfshaft (ideal)") && routes.Items[0].ToString().Contains("wheel"),"route shows the destination and assigned ideal shaft");
  bool occupied=false;try{Call(panel,"RouteDialog",new object[]{null});}catch(TargetInvocationException e){occupied=e.InnerException.Message.Contains("available output");}
  Check(occupied,"occupied ports cannot acquire another route");
  Set(project,"Driveline",Call(edited,"Copy"));Call(project,"Save");var reloaded=project.GetType().GetMethod("Load").Invoke(null,new[]{Get(project,"FilePath")});
  var saved=((IList)Get(Get(reloaded,"Driveline"),"Shafts"))[0];
  Check((string)Get(saved,"Representation")=="ideal" && (double)Get(saved,"HalfTravel")==.025,"ideal shaft and half travel survive disk reload");
  RouteForm(panel,true,false,routes.SelectedItem);
  var direct=Get(panel,"Draft");
  Check(((IList)Get(direct,"Shafts")).Count==0 && ((IList)Get(direct,"Connections")).Count==1 && ((IList)Get(direct,"Endpoints")).Count==2,"changing an ideal shaft to direct preserves both port datums and removes the shaft");

 }
 public static void Run(string dll,string folder){
  var code=Assembly.LoadFrom(dll);var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");
  var document=Path.Combine(folder,"fixture.SLDASM");File.WriteAllText(document,"Persistence fixture only; never opened in CAD");
  var project=projectType.GetMethod("Open").Invoke(null,new[]{document});var path=(string)Get(project,"FilePath");var original=File.ReadAllBytes(path);
  var graph=New(code,"Preparation.Driveline");var device=New(code,"Preparation.DriveDevice");Set(device,"Name","Rear gearbox housing");Set(device,"Type","cvt");((IList)Get(graph,"Devices")).Add(device);
  var parameters=(IDictionary)Get(device,"Parameters");parameters.Add("minGearRatio",.7);parameters.Add("maxGearRatio",3.2);
  var endpoint=New(code,"Preparation.DriveEndpoint");Set(endpoint,"Name","Custom output");Set(endpoint,"Component","stable-owner");((IList)Get(graph,"Endpoints")).Add(endpoint);
  var shaft=New(code,"Preparation.DriveShaft");Set(shaft,"LegacyPlunge",.03);((IList)Get(graph,"Shafts")).Add(shaft);
  var clone=Call(graph,"Copy");Set(((IList)Get(clone,"Endpoints"))[0],"Name","Edited copy");Check((string)Get(endpoint,"Name")=="Custom output","graph drafts do not mutate saved endpoint objects");
  Set(project,"Driveline",graph);Call(project,"Save");Check((int)Get(project,"Version")==4,"graph adoption writes project version 4");
  Check(File.ReadAllBytes(path+".v3.bak").SequenceEqual(original),"graph migration preserves the exact previous project bytes");
  var restored=projectType.GetMethod("Load").Invoke(null,new[]{path});var saved=Get(restored,"Driveline");
  Check((string)Get(((IList)Get(saved,"Endpoints"))[0],"Id")== (string)Get(endpoint,"Id"),"endpoint identity survives disk reload");
  var settings=(IDictionary)Get(((IList)Get(saved,"Devices"))[0],"Parameters");Check((double)settings["maxGearRatio"]==3.2,"device settings survive dictionary serialization");
  Check((double)Get(((IList)Get(saved,"Shafts"))[0],"LegacyPlunge")==.03,"migration retains the original shaft plunge requirement");
  var issues=((IEnumerable)Call(saved,"ReferenceIssues",restored)).Cast<object>().ToList();Check(issues.Count>0,"partial graphs report missing CAD references instead of inventing endpoints");
  using(var panel=(Control)New(code,"UI.DrivelinePanel"))using(var window=new Form {Width=900,Height=800}){
   Call(panel,"Configure",restored,true);window.Controls.Add(panel);window.Show();Application.DoEvents();
   foreach(var size in new[]{new System.Drawing.Size(900,800),new System.Drawing.Size(560,750)}){window.Size=size;Application.DoEvents();Check(panel.Controls.Find("DrivelineEndpoints",true).Length==1,"native endpoint list is available at "+size.Width+" px");}
   var draft=Call(saved,"Copy");Call(panel,"Adopt",draft);Check((bool)Get(panel,"HasChanges"),"adopting a preset creates an unsaved graph draft");
   Check((string)Get(((IList)Get(Get(restored,"Driveline"),"Endpoints"))[0],"Name")=="Custom output","editing UI drafts preserves saved graph data");
   Call(panel,"Configure",restored,true);Check(!(bool)Get(panel,"HasChanges"),"discard restores the saved graph");RouteWorkflow(code,panel,restored);window.Close();
  }
  var unchanged=projectType.GetMethod("Load").Invoke(null,new[]{path});Check((int)Get(unchanged,"Version")==4,"loading graph work does not downgrade its project version");
 }
}
'@
[DrivelineTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination)
