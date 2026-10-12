param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\mod-manager'),[string]$PythonExecutable)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
if(-not $PythonExecutable){$PythonExecutable=Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'}
$folder=Join-Path $OutputDirectory ('manager-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $folder | Out-Null
& $PythonExecutable (Join-Path $PSScriptRoot '../tests/test_static_frame.py') --make-fixture (Join-Path $folder 'prepared')
if($LASTEXITCODE -ne 0){throw 'Fixture failed'}
& $PythonExecutable (Join-Path $PSScriptRoot '../tests/test_static_frame.py') --make-package (Join-Path $folder 'prepared') (Join-Path $folder 'original') *> (Join-Path $folder 'fixture.log')
if($LASTEXITCODE -ne 0){throw 'Fixture build failed'}
Add-Type -ReferencedAssemblies @('System.Core','System.Drawing','System.Windows.Forms') -TypeDefinition @'
using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
public static class ModManagerSmoke {
 static void Check(bool ok,string text){if(!ok)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static Button Find(Control root,string text){foreach(Control c in root.Controls){if(c is Button && c.Text==text)return (Button)c;var b=Find(c,text);if(b!=null)return b;}return null;}
 public static void Run(string dll,string folder,string python){
 var asm=Assembly.LoadFrom(dll);var settingType=asm.GetType("BeamNG.Cad.UI.ExporterSettings");var settings=Activator.CreateInstance(settingType,new object[]{Path.Combine(folder,"settings.xml")});
 var game=Path.Combine(folder,"game");var mods=Path.Combine(folder,"user","mods");Directory.CreateDirectory(game);Directory.CreateDirectory(mods);File.WriteAllText(Path.Combine(game,"BeamNG.drive.exe"),"fixture");
 Action<string,string> set=(key,value)=>settingType.GetProperty(key).SetValue(settings,value,null);
 set("GameDirectory",game);set("ModsDirectory",mods);set("PythonExecutable",python);set("LastBuildReceipt",Path.Combine(folder,"original","static_frame_build.json"));
 var package=asm.GetType("BeamNG.Cad.FramePipeline.ModPackage");var profile=Path.Combine(folder,"mod-profile.json");
 var receipt=(string)settingType.GetProperty("LastBuildReceipt").GetValue(settings,null);
 var image=(string)package.GetMethod("HullImage").Invoke(null,new object[]{receipt,profile});
 using(var picture=Image.FromFile(image))Check(picture.Width==1024 && picture.Height==576,"hull preview is a decodable 1024x576 image");
 var imported=(string)package.GetMethod("ImportImage").Invoke(null,new object[]{image,profile});
 using(var picture=Image.FromFile(imported))Check(picture.Width==1024 && picture.Height==576,"chosen image is normalized for the selector");
 var type=asm.GetType("BeamNG.Cad.UI.ModManager");
 using(var form=(Form)Activator.CreateInstance(type,settings,profile)){
 form.StartPosition=FormStartPosition.Manual;form.Location=new Point(-30000,-30000);form.Show();Application.DoEvents();
 ((TextBox)form.Controls.Find("ModName",true)[0]).Text="Frame UI test";
 type.GetMethod("SetImage",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,new object[]{imported});
 Find(form,"Install selected build").PerformClick();Application.DoEvents();
 Check(!File.Exists(Path.Combine(mods,"ak1di_mochi.zip")),"unapplied edits cannot silently install an older package");
 Find(form,"Apply to selected build").PerformClick();
 var busy=type.GetField("busy",BindingFlags.NonPublic|BindingFlags.Instance);
 var watch=System.Diagnostics.Stopwatch.StartNew();while((bool)busy.GetValue(form)&&watch.ElapsedMilliseconds<30000){Application.DoEvents();System.Threading.Thread.Sleep(20);}Application.DoEvents();
 var named=((TextBox)form.Controls.Find("ModReceipt",true)[0]).Text;Check(named!=receipt && File.Exists(named),"Apply creates and selects a new package revision");
 Find(form,"Install selected build").PerformClick();watch.Restart();while((bool)busy.GetValue(form)&&watch.ElapsedMilliseconds<30000){Application.DoEvents();System.Threading.Thread.Sleep(20);}Application.DoEvents();
 var status=form.Controls.Find("ModStatus",true)[0].Text;
 Check(status.Contains("Installed ZIP matches this build") && status.Contains("Mochi Frame UI test") && status.Contains("Preview included"),"manager verifies installed hash, name and preview");
 var installed=Path.Combine(mods,"ak1di_mochi.zip");var before=File.ReadAllBytes(installed);
 ((CheckBox)form.Controls.Find("ReinstallMod",true)[0]).Checked=true;
 Find(form,"Install selected build").PerformClick();watch.Restart();while((bool)busy.GetValue(form)&&watch.ElapsedMilliseconds<30000){Application.DoEvents();System.Threading.Thread.Sleep(20);}Application.DoEvents();
 var backups=Directory.GetFiles(Path.Combine(folder,"user","TrueMeshExporter-backups"),"*.zip.bak");
 Check(backups.Length==1 && before.SequenceEqual(File.ReadAllBytes(backups[0])) && before.SequenceEqual(File.ReadAllBytes(installed)),"reinstall checkbox replaces matching ZIP and keeps a complete backup");
 Check(form.Controls.Find("ModLog",true)[0].Text.Contains("INSTALL ACTION reinstalled"),"manager reports a completed reinstall");
 Check(File.Exists(Path.Combine(folder,"original","static_frame_build.json")),"original build remains available");
 using(var screenshot=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(screenshot,new Rectangle(0,0,form.Width,form.Height));screenshot.Save(Path.Combine(folder,"manager.png"));}
 form.Close();
 }
 Console.WriteLine("MANAGER_EVIDENCE="+folder);
 }
}
'@
[ModManagerSmoke]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$folder,$PythonExecutable)
