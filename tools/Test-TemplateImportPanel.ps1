param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
public static class TemplateImportPanelTest {
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 public static void Run(string dll){
  var code=Assembly.LoadFrom(dll);var type=code.GetType("BeamNG.Cad.UI.TemplateImportPanel");
  using(var form=new Form())using(var panel=(Control)Activator.CreateInstance(type,true)){
   int imports=0,continues=0,resets=0,fresh=0,opens=0;
   type.GetEvent("ImportRequested").AddEventHandler(panel,(Action)(()=>imports++));
   type.GetEvent("ContinueRequested").AddEventHandler(panel,(Action)(()=>continues++));
   type.GetEvent("ResetRequested").AddEventHandler(panel,(Action)(()=>resets++));
   type.GetEvent("FreshRequested").AddEventHandler(panel,(Action)(()=>fresh++));
   type.GetEvent("OpenRequested").AddEventHandler(panel,(Action)(()=>opens++));
   form.Controls.Add(panel);form.Show();Application.DoEvents();
   var button=(Button)panel.Controls.Find("ImportPhysicsTemplate",true).Single();var label=panel.Controls.Find("TemplateImportState",true).Single();
   var reset=(Button)panel.Controls.Find("ResetPhysicsTemplate",true).Single();
   var state=type.GetMethod("SetState");
   Check(button.Enabled&&button.Text=="Import physics template","empty project offers picker action");button.PerformClick();
   Check(imports==1&&continues==0,"empty project dispatches import");
   state.Invoke(panel,new object[]{35,@"H:\base\static_frame_build.json"});Application.DoEvents();
   Check(button.Enabled&&button.Text=="Continue with imported template","imported state offers continuation");
   Check(label.Text.Contains("hardpoints and physics are loaded")&&label.Text.Contains(@"H:\base\static_frame_build.json"),"source and loaded hardpoints visible");
   button.PerformClick();button.PerformClick();Check(imports==1&&continues==2,"repeat clicks navigate without reimport");
   Check(reset.Visible&&reset.Enabled&&label.Text.Contains("backup"),"reset is explicit and explains preserved backup");
   reset.PerformClick();Check(resets==1&&imports==1,"reset dispatches separately from import");
   state.Invoke(panel,new object[]{2,""});
   ((Button)panel.Controls.Find("StartFreshCadProject",true).Single()).PerformClick();
   ((Button)panel.Controls.Find("OpenSavedProject",true).Single()).PerformClick();
   Check(fresh==1&&opens==1&&imports==1,"fresh/open project work independently of template import");
   Check(!button.Enabled&&label.Text.Contains("already has CAD groups"),"manual assignments show blocking reason beside import");
   Check(!reset.Enabled&&!reset.Visible,"no reset without a template baseline");
   button.PerformClick();Check(imports==1&&continues==2,"disabled import cannot replace manual groups");
   state.Invoke(panel,new object[]{0,""});button.PerformClick();Check(imports==2,"empty state restores picker action");
   form.Close();
  }
 }
}
'@
[TemplateImportPanelTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'))
