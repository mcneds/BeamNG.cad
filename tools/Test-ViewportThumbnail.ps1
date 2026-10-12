param([Parameter(Mandatory=$true)][int]$ProcessId,[string]$OutputDirectory)
$ErrorActionPreference='Stop'
if(-not $OutputDirectory){$OutputDirectory=Join-Path $PSScriptRoot '..\beamng.cad\bin\viewport-thumbnails'}
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
. (Join-Path $PSScriptRoot 'Connect-SolidWorks.ps1') -ProcessId $ProcessId
Add-Type -ReferencedAssemblies @('System.Core','System.Drawing','System.Windows.Forms',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll')) -TypeDefinition @'
using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
public static class ViewportCaptureSmoke {
 static void Check(bool ok,string text){if(!ok)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static Button Find(Control root){foreach(Control c in root.Controls){if(c is Button && c.Text=="Capture SolidWorks viewport")return (Button)c;var button=Find(c);if(button!=null)return button;}return null;}
 public static void Run(object connection,string directory){
 var app=(ISldWorks)connection;var model=(ModelDoc2)app.ActiveDoc;Check(model!=null,"a document is active");
 var dirty=model.GetSaveFlag();var view=(ModelView)model.ActiveView;var scale=view.Scale2;
 var orientation=(double[])((MathTransform)view.Orientation3).ArrayData;
 var translation=(double[])((MathVector)view.Translation3).ArrayData;
 var asm=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));
 var folder=Path.Combine(directory,"viewport-test-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);
 var profile=Path.Combine(folder,"profile.json");
 var settings=Activator.CreateInstance(asm.GetType("BeamNG.Cad.UI.ExporterSettings"),new object[]{Path.Combine(folder,"settings.xml")});
 var type=asm.GetType("BeamNG.Cad.UI.ModManager");
 using(var form=(Form)Activator.CreateInstance(type,settings,profile)){
 type.GetProperty("SolidWorksApplication").SetValue(form,app,null);
 form.StartPosition=FormStartPosition.Manual;form.Location=new Point(-30000,-30000);form.Show();Application.DoEvents();
 var button=Find(form);Check(button!=null,"viewport capture is exposed in Manage Mod");button.PerformClick();Application.DoEvents();
 var file=(string)type.GetField("imagePath",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form);
 Check(File.Exists(file),"capture button creates a thumbnail from the live viewport");
 using(var image=new Bitmap(file)){
 Check(image.Width==1024&&image.Height==576,"captured view is normalized to selector dimensions");
 var colors=new System.Collections.Generic.HashSet<int>();for(int x=0;x<image.Width;x+=16)for(int y=0;y<image.Height;y+=16)colors.Add(image.GetPixel(x,y).ToArgb());
 Check(colors.Count>10,"captured viewport contains visible graphics");
 }
 Check((bool)type.GetField("unappliedEdits",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(form),"capture requires applying the new image before installation");
 Check(!File.Exists(profile),"capture does not overwrite the saved profile automatically");
 Console.WriteLine("CAPTURE="+file);form.Close();
 }
 Check(model.GetSaveFlag()==dirty,"capture preserves document save state");
 Check(view.Scale2==scale && orientation.SequenceEqual((double[])((MathTransform)view.Orientation3).ArrayData) && translation.SequenceEqual((double[])((MathVector)view.Translation3).ArrayData),"capture preserves camera orientation, pan and zoom");
 }
}
'@
[ViewportCaptureSmoke]::Run([SwConnection]::Connect($ProcessId),$OutputDirectory)
