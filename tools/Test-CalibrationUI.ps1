param([string]$OutputDirectory='beamng.cad/bin/cad-calibration',[Parameter(Mandatory=$true)][string]$ReviewFile)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
Add-Type -ReferencedAssemblies @('System.Core','System.Drawing','System.Windows.Forms','System.Web.Extensions') -TypeDefinition @'
using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
public static class CalibrationUiSmoke {
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 public static void Run(string directory,string source){
  var assembly=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));
  var path=Path.Combine(directory,"fixture-review-ui.json");File.Copy(source,path,true);
  var type=assembly.GetType("BeamNG.Cad.UI.FixtureReview");
  using(var form=(Form)Activator.CreateInstance(type,path)){
   form.StartPosition=FormStartPosition.Manual;form.Location=new Point(-30000,-30000);form.Show();Application.DoEvents();
   var mode=(ComboBox)form.Controls.Find("FixtureMode",true)[0];mode.SelectedIndex=1;
   var review=type.GetField("review",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(form);
   var nodes=(Array)review.GetType().GetField("nodes").GetValue(review);var node=nodes.GetValue(0);var id=(string)node.GetType().GetField("id").GetValue(node);
   type.GetMethod("Pick",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,new object[]{id});
   type.GetMethod("Pick",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,new object[]{id});
   Check(!((bool)review.GetType().GetField("approved").GetValue(review)),"fixture edits require explicit approval");
   using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(0,0,form.Width,form.Height));image.Save(Path.Combine(directory,"fixture-review.png"));}
   ((Button)form.Controls.Find("ApproveFixtures",true)[0]).PerformClick();Application.DoEvents();
   Check(form.DialogResult==DialogResult.OK,"reviewed fixtures and orientation can be approved");
  }
  var model=assembly.GetType("BeamNG.Cad.UI.GenerationReview").GetMethod("Load").Invoke(null,new object[]{path});
  Check((bool)model.GetType().GetField("approved").GetValue(model),"approval persists with this generation graph hash");
  var axis=assembly.GetType("BeamNG.Cad.Preparation.AxisMapping");
  var point=(double[])axis.GetMethod("ToCad").Invoke(null,new object[]{new[]{0.0,0.0,1.0},"+Y,+Z"});
  Check(point[0]==0&&point[1]==1&&point[2]==0,"BeamNG up maps back onto CAD Y in the SolidWorks overlay");
 }
}
'@
[CalibrationUiSmoke]::Run($OutputDirectory,(Resolve-Path -LiteralPath $ReviewFile).Path)
