param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\hull-controls'))
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
Add-Type -ReferencedAssemblies @('System.Core','System.Drawing','System.Windows.Forms','System.Runtime.Serialization','System.Xml') -TypeDefinition @'
using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.Serialization.Json;
using System.Text;
using System.Windows.Forms;
public static class HullControlsSmoke {
 static void Check(bool condition,string message) {if(!condition)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static object Field(object value,string name) {return value.GetType().GetField(name).GetValue(value);}
 public static void Run(string directory) {
  var assembly=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));var type=assembly.GetType("BeamNG.Cad.Preparation.HullOptions");
  var serializer=new DataContractJsonSerializer(type);
  var old="{\"Width\":3,\"Height\":5,\"Length\":7,\"Offset\":0.01,\"Weld\":0.15,\"ProxyDivisor\":7,\"Symmetry\":false,\"Orientation\":\"XYZ\"}";
  object options;using(var input=new MemoryStream(Encoding.UTF8.GetBytes(old)))options=serializer.ReadObject(input);
  Check((double)Field(options,"ProxyOffsetRatio")==100 && (double)Field(options,"SymmetryMergeDistance")==.0001 && !(bool)Field(options,"SymmetryBisectFlip"),"old assignments retain generator defaults");
  using(var form=new Form {Width=760,Height=860,StartPosition=FormStartPosition.Manual,Location=new Point(-30000,-30000)})
  using(var panel=(Control)Activator.CreateInstance(assembly.GetType("BeamNG.Cad.UI.HullOptionsPanel"))) {
   form.Controls.Add(panel);var value=panel.GetType().GetProperty("Value");int edits=0;
   panel.GetType().GetEvent("ValueChanged").AddEventHandler(panel,new EventHandler((s,e)=>edits++));
   value.SetValue(panel,options,null);Check(edits==0,"loading saved options does not invalidate preview");
   form.Show();Application.DoEvents();
   ((CheckBox)panel.Controls.Find("HullSymmetry",true)[0]).Checked=true;
   ((CheckBox)panel.Controls.Find("HullSymmetryBisectFlip",true)[0]).Checked=true;
   ((NumericUpDown)panel.Controls.Find("HullProxyOffsetRatio",true)[0]).Value=42;
   ((NumericUpDown)panel.Controls.Find("HullSymmetryMergeDistance",true)[0]).Value=.002m;
   ((NumericUpDown)panel.Controls.Find("HullWidth",true)[0]).Value=9;
   Check(panel.Controls.Find("CadUp",true).Length==0 && panel.Controls.Find("CadForward",true).Length==0,"coordinate convention is automatic");
   Check(edits==5,"each user edit notifies the workflow to discard the old preview");
   options=value.GetValue(panel,null);type.GetMethod("Validate").Invoke(options,null);
   using(var stream=new MemoryStream()) {serializer.WriteObject(stream,options);stream.Position=0;options=serializer.ReadObject(stream);}
   value.SetValue(panel,options,null);
   Check(edits==5 && (double)Field(options,"ProxyOffsetRatio")==42 && (double)Field(options,"SymmetryMergeDistance")==.002 && (bool)Field(options,"SymmetryBisectFlip") && (string)Field(options,"Orientation")=="X-ZY","advanced controls survive JSON round trip and reload");
   ((NumericUpDown)panel.Controls.Find("HullWidth",true)[0]).Value=4;
   bool rejected=false;try{type.GetMethod("Validate").Invoke(value.GetValue(panel,null),null);}catch(TargetInvocationException e){rejected=e.InnerException is InvalidDataException;}
   Check(rejected,"even width with symmetry is rejected before exporting geometry");
   edits=0;((Button)panel.Controls.Find("ResetHullDefaults",true)[0]).PerformClick();
   options=value.GetValue(panel,null);
   Check(edits==1 && (int)Field(options,"Width")==3 && (double)Field(options,"ProxyOffsetRatio")==100 && !(bool)Field(options,"Symmetry"),"reset restores defaults and invalidates preview once");
   Check(!panel.Controls.Find("HullSymmetryBisectFlip",true)[0].Enabled && !panel.Controls.Find("HullSymmetryMergeDistance",true)[0].Enabled,"symmetry-only controls are disabled when unused");
   Application.DoEvents();using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(0,0,form.Width,form.Height));image.Save(Path.Combine(directory,"hull-controls.png"));}
   form.Close();
  }
 }
}
'@
[HullControlsSmoke]::Run($OutputDirectory)
