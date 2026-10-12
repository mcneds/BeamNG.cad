param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing','System.Web.Extensions' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Diagnostics;
using System.Windows.Forms;
using System.Drawing;
using System.Web.Script.Serialization;
public static class SkeletonUiTest {
 static object Make(Assembly code,string name){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+name),true);}
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static Control Find(Control root,string name){return root.Controls.Find(name,true).Single();}
 static void Capture(Form form,string path){using(var b=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(b,new Rectangle(0,0,b.Width,b.Height));b.Save(path);}}
 public static void Run(string dll,string folder){
  var code=Assembly.LoadFrom(dll);var catalog=code.GetType("BeamNG.Cad.Preparation.MvpCatalog").GetMethod("Load").Invoke(null,null);
  var project=Make(code,"Preparation.VehicleProject");var json=new JavaScriptSerializer();
  var original=json.Serialize(project);var watch=Stopwatch.StartNew();
  using(var form=new Form {Text="Reference skeleton - tested synthetic vehicle",Width=1120,Height=800})
  using(var control=(Control)Make(code,"UI.ReferenceSkeleton")){
   form.Controls.Add(control);form.Show();control.GetType().GetMethod("Configure").Invoke(control,new[]{catalog,project});Application.DoEvents();
   var tree=(TreeView)Find(control,"ReferenceRequests");Check(tree.Nodes.ContainsKey("rl_trailing_arm"),"primary requests include trailing arm");
   Check(!tree.Nodes.ContainsKey("rl_upper_wishbone"),"inactive rear wishbone requests excluded");
   Check(tree.Nodes.ContainsKey("shaft_carrier")&&tree.Nodes["shaft_carrier"].Nodes.ContainsKey("shaft_joint"),"carrier support requests are exposed");
   var roles=((IEnumerable)catalog.GetType().GetProperty("Roles").GetValue(catalog)).Cast<object>();
   var shaftRole=roles.Single(r=>(string)r.GetType().GetField("Id").GetValue(r)=="front_propshaft");
   Check((bool)shaftRole.GetType().GetProperty("Repeatable").GetValue(shaftRole),"each front propshaft section can own a separate CAD group");
   tree.SelectedNode=tree.Nodes["rl_trailing_arm"].Nodes["pivot_axis_a"];tree.SelectedNode.Parent.Expand();Application.DoEvents();
   Check(Find(control,"ReferenceDetail").Text.Contains("hardpoints.RL.hinge_inner"),"trailing pivot identifies declaration");
   Capture(form,Path.Combine(folder,"reference-trailing-arm.png"));
   tree.SelectedNode=tree.Nodes["fl_wheel"].Nodes["wheel_axis"];Application.DoEvents();
   Check(Find(control,"ReferenceDetail").Text.Contains("0.8500"),"wheel axis second point shown");
   var angle=(ComboBox)Find(control,"ReferenceViewAngle");foreach(var i in new[]{1,2,3,4,0}){angle.SelectedIndex=i;Application.DoEvents();}
   var viewport=Find(control,"ReferenceViewport");var projectPoint=viewport.GetType().GetMethod("Project",BindingFlags.Instance|BindingFlags.NonPublic);
   Func<double[],PointF> point=p=>(PointF)projectPoint.Invoke(viewport,new object[]{p});
   angle.SelectedIndex=2;Check(point(new[]{1d,0,0}).X>point(new[]{-1d,0,0}).X,"front view puts vehicle left on screen right");
   angle.SelectedIndex=4;Check(point(new[]{1d,0,0}).X<point(new[]{-1d,0,0}).X,"rear view puts vehicle left on screen left");
   angle.SelectedIndex=1;Check(point(new[]{0d,-1,0}).Y<point(new[]{0d,1,0}).Y && point(new[]{1d,0,0}).X<point(new[]{-1d,0,0}).X,"top view looks down with forward up and vehicle left on screen left");
   angle.SelectedIndex=0;
   ((CheckBox)Find(control,"ReferenceFocus")).Checked=true;Application.DoEvents();Capture(form,Path.Combine(folder,"reference-wheel-axis.png"));
   tree.SelectedNode=tree.Nodes["engine"].Nodes["output_axis"];Application.DoEvents();
   Check(Find(control,"ReferenceDetail").Text.Contains("Not explicitly located"),"missing engine bearing axis is not guessed");
   Check(json.Serialize(project)==original,"reference browsing cannot mutate project");
   var choices=(IList)project.GetType().GetField("MvpTemplates").GetValue(project);choices.Clear();
   foreach(var pair in new[]{new[]{"front_suspension","double_wishbone"},new[]{"rear_suspension","double_wishbone"},new[]{"drivetrain","cvt_rear_drive"}}){
    var choice=Make(code,"Preparation.MvpTemplateChoice");choice.GetType().GetField("Category").SetValue(choice,pair[0]);choice.GetType().GetField("Template").SetValue(choice,pair[1]);choices.Add(choice);}
   control.GetType().GetMethod("Configure").Invoke(control,new[]{catalog,project});Application.DoEvents();
   Check(tree.Nodes.ContainsKey("rl_upper_wishbone")&&!tree.Nodes.ContainsKey("rl_trailing_arm"),"alternate layout switches requested rear parts");
   Check(Find(control,"ReferenceHeading").Text.Contains("variant-vehicle-w"),"alternate uses matching tested geometry");
   tree.SelectedNode=tree.Nodes["rl_upper_wishbone"].Nodes["outboard_joint"];tree.SelectedNode.Parent.Expand();
   ((CheckBox)Find(control,"ReferenceFocus")).Checked=false;Application.DoEvents();Capture(form,Path.Combine(folder,"reference-alternate.png"));
   foreach(var choice in choices){
    var category=(string)choice.GetType().GetField("Category").GetValue(choice);
    if(category=="rear_suspension")choice.GetType().GetField("Template").SetValue(choice,"trailing_radius_toe");
    if(category=="drivetrain")choice.GetType().GetField("Template").SetValue(choice,"cvt_rear_front_output");
   }
   control.GetType().GetMethod("Configure").Invoke(control,new[]{catalog,project});Application.DoEvents();
   Check(new[]{"rl_upper_radius_rod","rl_lower_radius_rod","rl_toe_link","rr_upper_radius_rod","rr_lower_radius_rod","rr_toe_link"}.All(id=>tree.Nodes.ContainsKey(id)),"ball-joint option requests two radius rods and one toe link on both sides");
   Check(tree.Nodes["rl_trailing_arm"].Nodes.ContainsKey("carrier_joint")&&!tree.Nodes["rl_trailing_arm"].Nodes.ContainsKey("hub_center"),"arm marker switches to carrier ball for this layout");
   Check(Find(control,"ReferenceHeading").Text.StartsWith("SYNTHETIC REFERENCE"),"ball-joint option uses matching native geometry");
   tree.SelectedNode=tree.Nodes["rl_upright"].Nodes["carrier_joint"];tree.SelectedNode.Parent.Expand();Application.DoEvents();
   Check(Find(control,"ReferenceDetail").Text.Contains("hardpoints.RL.carrier_ball"),"carrier marker comes from declared ball centre");
   Capture(form,Path.Combine(folder,"reference-radius-toe.png"));
   tree.SelectedNode=tree.Nodes["rl_lower_radius_rod"].Nodes["chassis_joint"];tree.SelectedNode.Parent.Expand();tree.SelectedNode.EnsureVisible();
   ((CheckBox)Find(control,"ReferenceFocus")).Checked=true;Application.DoEvents();
   Check(Find(control,"ReferenceDetail").Text.Contains("hardpoints.RL.radius_lower_inner"),"lower radius rod has its own chassis ball marker");
   Capture(form,Path.Combine(folder,"reference-lower-radius-rod.png"));
   var first=choices[0];first.GetType().GetField("Template").SetValue(first,"strut");
   control.GetType().GetMethod("Configure").Invoke(control,new[]{catalog,project});Application.DoEvents();
   Check(Find(control,"ReferenceHeading").Text.StartsWith("No tested reference"),"unsupported layout does not show misleading geometry");
   form.Close();
  }
  Console.WriteLine("Elapsed UI exercise ms: "+watch.ElapsedMilliseconds);File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS");
 }
}
'@
[SkeletonUiTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
