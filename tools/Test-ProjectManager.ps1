param([Parameter(Mandatory=$true)][string]$Receipt,[Parameter(Mandatory=$true)][string]$PythonExecutable,[string]$OutputDirectory)
$ErrorActionPreference='Stop'
if(-not $OutputDirectory){$OutputDirectory=Join-Path $PSScriptRoot '../beamng.cad/bin/vehicle-system'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$folder=Join-Path $OutputDirectory ('project-manager-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($folder)
$record=Get-Content -LiteralPath $Receipt -Raw | ConvertFrom-Json
$document=Join-Path $folder 'fixture.SLDASM'
[IO.File]::WriteAllText($document,'fixture only; never opened in CAD')
$projectPath=Join-Path $folder 'fixture.beamng-project.json'
$project=@{Version=2;SourceDocument=$document;Identity=$record.identity;LastBuildReceipt=$Receipt;FrameBuildReceipt='';Components=@();Anchors=@();Connections=@()}
[IO.File]::WriteAllText($projectPath,($project | ConvertTo-Json -Depth 20),(New-Object Text.UTF8Encoding $false))
Add-Type -ReferencedAssemblies @('System.Core','System.Drawing','System.Windows.Forms') -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
public static class ProjectManagerTest {
 static void Check(bool value,string text){if(!value)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static Button Find(Control root,string text){foreach(Control c in root.Controls){if(c is Button&&c.Text==text)return (Button)c;var nested=Find(c,text);if(nested!=null)return nested;}return null;}
 static void Click(Form form,string text){Find(form,text).PerformClick();var busy=form.GetType().GetField("busy",BindingFlags.NonPublic|BindingFlags.Instance);var deadline=DateTime.UtcNow.AddSeconds(45);do{Application.DoEvents();Thread.Sleep(10);}while((bool)busy.GetValue(form)&&DateTime.UtcNow<deadline);Check(!(bool)busy.GetValue(form),"manager operation completed: "+text);}
 public static void Run(string dll,string folder,string projectPath,string python,string expected,string model){
  var code=Assembly.LoadFrom(dll);var settingsType=code.GetType("BeamNG.Cad.UI.ExporterSettings");var settings=Activator.CreateInstance(settingsType,new object[]{Path.Combine(folder,"settings.xml")});
  Action<string,string> set=(key,value)=>settingsType.GetProperty(key).SetValue(settings,value,null);
  var mods=Path.Combine(folder,"mods");var game=Path.Combine(folder,"game");Directory.CreateDirectory(mods);Directory.CreateDirectory(game);File.WriteAllText(Path.Combine(game,"BeamNG.drive.exe"),"fixture");
  set("FrameOutput",Path.Combine(folder,"builds"));set("LastBuildReceipt","missing-old-global-receipt");set("PythonExecutable",python);set("ModsDirectory",mods);set("GameDirectory",game);
  var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");var project=projectType.GetMethod("Load").Invoke(null,new object[]{projectPath});
  var type=code.GetType("BeamNG.Cad.UI.ModManager");
  using(var form=(Form)Activator.CreateInstance(type,new object[]{settings,null,project})){
   form.Show();Application.DoEvents();SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
   var receipt=(TextBox)form.Controls.Find("ModReceipt",true).Single();
   Check(receipt.Text==expected,"project build wins over stale global receipt");
   ((TextBox)form.Controls.Find("ModName",true).Single()).Text="Project component rename";
   Click(form,"Apply to selected build");var updated=receipt.Text;Check(updated!=expected&&File.Exists(updated),"component package revision selected");
   Click(form,"Install selected build");Check(File.Exists(Path.Combine(mods,model+".zip")),"install keeps project namespace after display-name edit");
   Check(!File.Exists(Path.Combine(mods,"ak1di_mochi.zip")),"project install does not create legacy package");
   var latest=projectType.GetMethod("Load").Invoke(null,new object[]{projectPath});projectType.GetField("LastBuildReceipt").SetValue(latest,"");projectType.GetMethod("Save").Invoke(latest,null);
   Click(form,"Refresh status");Check(!Find(form,"Apply to selected build").Enabled&&!Find(form,"Install selected build").Enabled,"no completed project build disables apply and install");
   form.Close();
  }
  Console.WriteLine("PROJECT_MANAGER_EVIDENCE="+folder);
 }
}
'@
[ProjectManagerTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$folder,$projectPath,$PythonExecutable,$Receipt,$record.identity.namespace)
