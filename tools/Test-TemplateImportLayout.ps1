param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination,[string]$DebugGate)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing' -TypeDefinition @'
using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
public static class TemplateImportLayoutTest {
 static string Describe(Control c){return c.GetType().Name+" "+c.Name+" bounds="+c.Bounds+" preferred="+c.GetPreferredSize(Size.Empty)+" visible="+c.Visible;}
 static void Dump(Control c,System.Text.StringBuilder text){text.AppendLine(Describe(c));foreach(Control child in c.Controls)Dump(child,text);}
 static bool Exposed(Control control){var area=control.RectangleToScreen(control.ClientRectangle);for(var p=control.Parent;p!=null;p=p.Parent)if(!p.RectangleToScreen(p.ClientRectangle).Contains(area))return false;return control.Visible&&control.Width>10&&control.Height>10;}
 public static void Run(string dll,string folder,string gate){
  var code=Assembly.LoadFrom(dll);var workflow=code.GetType("BeamNG.Cad.UI.ComponentWorkflow");
  var panelType=code.GetType("BeamNG.Cad.UI.TemplateImportPanel");
  var sections=workflow.GetMethod("Sections",BindingFlags.NonPublic|BindingFlags.Static);
  var section=workflow.GetMethod("Section",BindingFlags.NonPublic|BindingFlags.Static);
  using(var form=new Form {Text="Owned import layout test",Width=1020,Height=860}){
   var stack=(TableLayoutPanel)sections.Invoke(null,null);
   for(var i=0;i<2;i++){
    var filler=(FlowLayoutPanel)section.Invoke(null,new object[]{stack,"Setup "+i,"Earlier setup controls"});
    filler.Controls.Add(new Panel {Size=new Size(460,150)});
   }
   var import=(FlowLayoutPanel)section.Invoke(null,new object[]{stack,"Project","Start fresh without importing physics, open saved work, or optionally reuse an existing physics package. A fresh project is saved separately; your current work is kept."});
   var panel=(Control)Activator.CreateInstance(panelType,true);import.Controls.Add(panel);
   var scroll=new Panel {Dock=DockStyle.Fill,AutoScroll=true};scroll.Controls.Add(stack);
   var layout=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=1,RowCount=2};
   layout.RowStyles.Add(new RowStyle(SizeType.Percent,60));layout.RowStyles.Add(new RowStyle(SizeType.Percent,40));
   layout.Controls.Add(scroll,0,0);layout.Controls.Add(new TextBox {Dock=DockStyle.Fill,Multiline=true,Text="Checklist"},0,1);form.Controls.Add(layout);
   panelType.GetMethod("SetState").Invoke(panel,new object[]{35,@"H:\beamng project programs\builds\synthetic-mvp-20261007\primary-vehicle-bt\static_frame_build.json"});
   form.Show();Application.DoEvents();
   if(!string.IsNullOrEmpty(gate)){
    File.WriteAllText(gate+".pid",System.Diagnostics.Process.GetCurrentProcess().Id.ToString());
    var deadline=DateTime.UtcNow.AddMinutes(3);
    while(File.Exists(gate)){Application.DoEvents();Thread.Sleep(50);if(DateTime.UtcNow>deadline)throw new Exception("Debugger gate timeout");}
   }
   var reset=(Button)panel.Controls.Find("ResetPhysicsTemplate",true).Single();
   scroll.ScrollControlIntoView(reset);Application.DoEvents();
   var text=new System.Text.StringBuilder();Dump(form,text);File.WriteAllText(Path.Combine(folder,"bounds.txt"),text.ToString());
   using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(0,0,image.Width,image.Height));image.Save(Path.Combine(folder,"layout.png"));}
   // This executes only the UI's event delegate; the probe never connects a
   // project reset handler and cannot mutate any user project.
   ((Button)panel.Controls.Find("ImportPhysicsTemplate",true).Single()).PerformClick();
   Console.WriteLine(Describe(panel));Console.WriteLine(Describe(reset));
   if(!Exposed(reset))throw new Exception("Reset button is clipped even after scrolling into view");
   Console.WriteLine("PASS reset button has a visible clickable rectangle in the setup layout");
   // Match the production layout's promoted import section and ensure reset
   // does not need scrolling at the supported minimum size or larger fonts.
   stack.SuspendLayout();
   var earlier=stack.Controls.Cast<Control>().Where(c=>c!=import.Parent).OrderBy(c=>stack.GetRow(c)).ToArray();
   stack.SetRow(import.Parent,0);for(var i=0;i<earlier.Length;i++)stack.SetRow(earlier[i],i+1);stack.ResumeLayout(true);
   foreach(var size in new[]{new Size(1020,860),new Size(850,650)})foreach(var fontSize in new[]{8.25f,10f,12f}){
    using(var font=new Font("Segoe UI",fontSize)){
     form.Font=font;form.Size=size;scroll.AutoScrollPosition=Point.Empty;form.PerformLayout();Application.DoEvents();
     if(!Exposed(reset))throw new Exception("Reset clipped at "+size+" / "+fontSize+"pt: "+Describe(panel));
     if(!Exposed(panel.Controls.Find("StartFreshCadProject",true).Single())||!Exposed(panel.Controls.Find("OpenSavedProject",true).Single()))throw new Exception("Fresh/open project clipped at "+size+" / "+fontSize+"pt");
     Console.WriteLine("PASS reset visible without scrolling: "+size+" / "+fontSize+"pt");
     using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(0,0,image.Width,image.Height));image.Save(Path.Combine(folder,"layout-"+size.Width+"-"+fontSize.ToString(System.Globalization.CultureInfo.InvariantCulture)+".png"));}
    }
   }
   form.Close();
  }
 }
}
'@
[TemplateImportLayoutTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination),$DebugGate)
