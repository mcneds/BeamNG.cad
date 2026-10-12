param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination,[string]$DebugGate)
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
using System.Runtime.Serialization.Json;
public static class AssignmentInspectionTest {
 static object New(Assembly code,string name){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+name),true);}
 static void Put(object value,string name,object item){value.GetType().GetField(name).SetValue(value,item);}
 static object Get(object value,string name){return value.GetType().GetField(name).GetValue(value);}
 static string Snapshot(object value){using(var bytes=new MemoryStream()){new DataContractJsonSerializer(value.GetType()).WriteObject(bytes,value);return Convert.ToBase64String(bytes.ToArray());}}
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static void Failure(Action action,string message){try{action();}catch(TargetInvocationException e){Check(e.InnerException is InvalidOperationException && e.InnerException.Message.Contains(message),message);return;}throw new Exception("Expected failure: "+message);}
 static bool Exposed(Control item){var bounds=item.RectangleToScreen(item.ClientRectangle);for(var p=item.Parent;p!=null;p=p.Parent)if(!p.RectangleToScreen(p.ClientRectangle).Contains(bounds))return false;return bounds.Width>0&&bounds.Height>0&&item.Visible;}
 public static void Run(string dll,string output){
  var code=Assembly.LoadFrom(dll);var json=new JavaScriptSerializer();var type=code.GetType("BeamNG.Cad.Preparation.AssignmentInspection");
  var component=New(code,"Preparation.ComponentDefinition");Put(component,"Name","Engine");Put(component,"Configuration","Physics configuration");Put(component,"AppearanceConfiguration","Display configuration");
  foreach(var entry in new[]{new[]{"Selections","physics-reference"},new[]{"AppearanceSelections","appearance-reference"}}){
   var reference=New(code,"Preparation.SelectionReference");Put(reference,"Kind","body");Put(reference,"Name",entry[1]);Put(reference,"Reference",entry[1]);Put(reference,"ComponentReference","owner");((IList)Get(component,entry[0])).Add(reference);}
  var initial=Snapshot(component);
  using(var form=new Form {Width=850,Height=650})using(var panel=(Control)New(code,"UI.AssignmentInspectionPanel")){
   // Match the production left column, so an AutoSize/Dock regression is visible.
   var outer=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=2,RowCount=1};outer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,34));outer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,66));
   var left=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=1,RowCount=2};left.RowStyles.Add(new RowStyle(SizeType.AutoSize));left.RowStyles.Add(new RowStyle(SizeType.Percent,100));
   left.Controls.Add(panel,0,0);left.Controls.Add(new ListBox {Dock=DockStyle.Fill},0,1);outer.Controls.Add(left,0,0);outer.Controls.Add(new Panel {Dock=DockStyle.Fill},1,0);form.Controls.Add(outer);form.Show();Application.DoEvents();
   var source=(ComboBox)panel.Controls.Find("AssignmentSource",true).Single();var show=(Button)panel.Controls.Find("ShowAssignedGeometry",true).Single();
   var zoom=(CheckBox)panel.Controls.Find("ZoomToAssignedGeometry",true).Single();var summary=(Label)panel.Controls.Find("AssignmentSummary",true).Single();
   int shown=0;panel.GetType().GetEvent("ShowRequested").AddEventHandler(panel,(Action)(()=>shown++));
   var set=panel.GetType().GetMethod("SetComponent");
   Check(!show.Enabled,"no action without a selected group");set.Invoke(panel,new[]{component});
   Check(source.SelectedIndex==0&&show.Enabled,"saved appearance is the default inspection source");Check(shown==0,"choosing a group does not overwrite a CAD selection");
   var appearance=type.GetMethod("Capture").Invoke(null,new object[]{component,true});
   Check((string)Get(appearance,"Configuration")=="Display configuration" && (string)Get(((IList)Get(appearance,"Selections"))[0],"Reference")=="appearance-reference","appearance uses its own references and configuration");
   Put(((IList)Get(appearance,"Selections"))[0],"Reference","edited-copy");
   Check(Snapshot(component)==initial,"inspection snapshot cannot mutate saved associations");
   source.SelectedIndex=1;show.PerformClick();Check(shown==1,"physical inspection is explicitly requested");
   var physical=type.GetMethod("Capture").Invoke(null,new object[]{component,false});
   Check((string)Get(physical,"Configuration")=="Physics configuration" && (string)Get(((IList)Get(physical,"Selections"))[0],"Reference")=="physics-reference","physical inspection keeps the physical references");
   zoom.Checked=false;Check(!(bool)panel.GetType().GetProperty("Zoom").GetValue(panel),"zoom can be disabled");
   ((IList)Get(component,"AppearanceSelections")).Clear();set.Invoke(panel,new[]{component});source.SelectedIndex=0;
   Check(!show.Enabled&&summary.Text.Contains("No saved appearance"),"missing appearance cannot fall back to a different group");
   Failure(()=>type.GetMethod("Capture").Invoke(null,new object[]{component,true}),"no saved appearance");
   source.SelectedIndex=1;Put(component,"GeometryDirectory",output);
   File.WriteAllText(Path.Combine(output,"geometry.json"),json.Serialize(new{SourceDocument=Path.Combine(output,"other.SLDASM")}));
   Failure(()=>type.GetMethod("CheckDocument").Invoke(null,new object[]{component,false,Path.Combine(output,"current.SLDASM")}),"another assembly");
   type.GetMethod("CheckDocument").Invoke(null,new object[]{component,false,Path.Combine(output,"other.SLDASM")});Check(true,"same assembly is accepted");
   Put(component,"GeometryDirectory",Path.Combine(output,"missing-export"));
   type.GetMethod("CheckDocument").Invoke(null,new object[]{component,false,Path.Combine(output,"current.SLDASM")});Check(true,"missing cached export does not erase persistent CAD assignments");
   Put(component,"Configuration","");Failure(()=>type.GetMethod("Capture").Invoke(null,new object[]{component,false}),"no configuration");
   foreach(var fontSize in new[]{8.25f,10f,12f})using(var font=new Font("Segoe UI",fontSize)){
    form.Font=font;form.PerformLayout();Application.DoEvents();
    Check(Exposed(show)&&Exposed(source)&&Exposed(zoom),"inspection controls visible at minimum window size / "+fontSize+"pt");form.Font=SystemFonts.MessageBoxFont;}
   using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(0,0,image.Width,image.Height));image.Save(Path.Combine(output,"inspection-panel.png"));}
   set.Invoke(panel,new object[]{null});Check(!show.Enabled&&!source.Enabled,"clearing group selection disables inspection");form.Close();
  }
  File.WriteAllText(Path.Combine(output,"result.txt"),"PASS");
 }
}
'@
if($DebugGate){
 [void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
 [IO.File]::WriteAllText($DebugGate+'.pid',[string]$PID)
 $inspectionDeadline=(Get-Date).AddMinutes(3)
 while(Test-Path -LiteralPath $DebugGate){if((Get-Date) -gt $inspectionDeadline){throw 'Owned debugger gate timed out'};Start-Sleep -Milliseconds 250}
}
[AssignmentInspectionTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
