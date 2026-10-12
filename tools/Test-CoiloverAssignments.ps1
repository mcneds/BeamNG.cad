param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing','System.Runtime.Serialization','System.Xml' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Windows.Forms;
using System.Drawing;
public static class CoiloverAssignmentsTest {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Put(object o,string n,object v){o.GetType().GetField(n).SetValue(o,v);}
 static object New(Assembly a,string n){return Activator.CreateInstance(a.GetType("BeamNG.Cad.Preparation."+n),true);}
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 public static void Run(string dll,string root){
  var code=Assembly.LoadFrom(dll);var document=Path.Combine(root,"fixture.SLDASM");File.WriteAllText(document,"Never opened in CAD");
  var type=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var project=type.GetMethod("Open").Invoke(null,new object[]{document});
  var component=New(code,"ComponentDefinition");Put(component,"MvpRole","fl_spring_damper");((IList)Get(project,"Components")).Add(component);
  var service=code.GetType("BeamNG.Cad.Preparation.CoiloverAppearance");
  foreach(var kind in new[]{"housing","shaft","spring"}){
   var selection=New(code,"FrameAssignment");Put(selection,"Configuration","Default");var reference=New(code,"SelectionReference");Put(reference,"Kind","body");Put(reference,"Reference",kind);((IList)Get(selection,"Selections")).Add(reference);
   service.GetMethod("Assign").Invoke(null,new object[]{component,kind,selection,new List<string>{kind},document});
   Put(reference,"Reference","changed-source");
  }
  service.GetMethod("Validate").Invoke(null,new object[]{component,document});
  Check(((IList)Get(component,"Selections")).Count==0&&((IList)Get(component,"BodyIds")).Count==0,"visual pieces do not add physical ownership");
  Put(Get(component,"AppearanceCoilover"),"HousingMount","bottom");
  var spring=New(code,"CoiloverSpring");Put(spring,"Mode","dual_rate");Put(spring,"MainRateNPerM",45000d);Put(spring,"TenderRateNPerM",20000d);Put(spring,"CrossoverCompressionM",.0125d);Put(component,"CoiloverSpring",spring);
  type.GetMethod("Save").Invoke(project,null);
  var path=(string)type.GetProperty("FilePath").GetValue(project);var restored=type.GetMethod("Load").Invoke(null,new object[]{path});var saved=((IList)Get(restored,"Components"))[0];var split=Get(saved,"AppearanceCoilover");
  Check((string)Get(split,"HousingMount")=="bottom"&&((IList)Get(split,"Pieces")).Count==3,"inverted mount and all three pieces survive restart");
  Check((string)Get(Get(saved,"CoiloverSpring"),"Mode")=="dual_rate"&&(double)Get(Get(saved,"CoiloverSpring"),"MainRateNPerM")==45000,"dual-rate physics settings survive restart");
  foreach(var piece in (IEnumerable)Get(split,"Pieces"))Check((string)Get(((IList)Get(piece,"Selections"))[0],"Reference")== (string)Get(piece,"Kind"),"durable reference is copied for "+Get(piece,"Kind"));
  var duplicate=New(code,"FrameAssignment");Put(duplicate,"Configuration","Default");((IList)Get(duplicate,"Selections")).Add(New(code,"SelectionReference"));
  bool rejected=false;try{service.GetMethod("Assign").Invoke(null,new object[]{saved,"shaft",duplicate,new List<string>{"housing"},document});}catch(TargetInvocationException e){rejected=e.InnerException is InvalidOperationException;}
  Check(rejected&&((IList)Get(split,"Pieces")).Count==3,"duplicate moving-body assignment rejected atomically");
  var panel=(Control)Activator.CreateInstance(code.GetType("BeamNG.Cad.UI.CoiloverPanel"),true);
  panel.GetType().GetMethod("SetComponent").Invoke(panel,new[]{saved});
  using(var form=new Form {Text="Coilover assignments",Width=620,Height=650}){
   form.Controls.Add(panel);form.Show();Application.DoEvents();
   var list=(ListBox)panel.Controls.Find("CoiloverPieces",true).Single();Check(list.Items.Count==3&&list.Items.Cast<object>().All(v=>v.ToString().Contains("1 bodies saved")),"each moving piece shows its saved status");
   var mount=(ComboBox)panel.Controls.Find("CoiloverHousingMount",true).Single();Check(mount.SelectedIndex==1,"inverted housing orientation visible");
   var main=(NumericUpDown)panel.Controls.Find("MainSpringRate",true).Single();var tender=(NumericUpDown)panel.Controls.Find("TenderSpringRate",true).Single();var crossover=(NumericUpDown)panel.Controls.Find("CrossoverCompression",true).Single();
   Check(main.Value==45&&tender.Value==20&&crossover.Value==12.5m&&main.Enabled,"saved SI values shown as N/mm and mm");
   main.Value=50;crossover.Value=15;var settings=panel.GetType().GetProperty("SpringSettings").GetValue(panel);
   Check((double)Get(settings,"MainRateNPerM")==50000&&(double)Get(settings,"CrossoverCompressionM")==.015,"edited display values convert back to SI");
   using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(Point.Empty,image.Size));image.Save(Path.Combine(root,"coilover-ui.png"));}
   ((ComboBox)panel.Controls.Find("CoiloverSpringMode",true).Single()).SelectedIndex=0;
   Check(!main.Enabled&&!tender.Enabled&&!crossover.Enabled&&(string)Get(panel.GetType().GetProperty("SpringSettings").GetValue(panel),"Mode")=="auto","automatic spring mode disables dual-rate inputs");
   form.Close();
  }
  ((IList)Get(split,"Pieces")).RemoveAt(2);rejected=false;try{service.GetMethod("Validate").Invoke(null,new object[]{saved,document});}catch(TargetInvocationException e){rejected=e.InnerException.Message.Contains("spring");}
  Check(rejected,"incomplete split names missing spring and keeps saved pieces");
  File.WriteAllText(Path.Combine(root,"result.txt"),"PASS");
 }
}
'@
[CoiloverAssignmentsTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
