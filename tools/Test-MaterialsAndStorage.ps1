param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\material-integration'))
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
Add-Type -ReferencedAssemblies @('System.Core','System.Xml','System.Xml.Linq') -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Diagnostics;
using System.Xml.Linq;
public static class MaterialsStorageTest {
 static void Check(bool ok,string message){if(!ok)throw new Exception(message);Console.WriteLine("PASS "+message);}
 public static void Run(string dll,string library,string root){
  var code=Assembly.LoadFrom(dll);
  var material=code.GetType("BeamNG.Cad.Preparation.BodyMaterial");
  var parse=code.GetType("BeamNG.Cad.Preparation.SolidWorksMaterials").GetMethod("ReadEntry",BindingFlags.Static|BindingFlags.NonPublic);
  var entry=XDocument.Load(library).Descendants().Single(e=>e.Name.LocalName=="material" && (string)e.Attribute("name")=="Plain Carbon Steel");
  var captured=Activator.CreateInstance(material,true);parse.Invoke(null,new object[]{entry,captured});
  Check((double)material.GetField("Density").GetValue(captured)==7800,"native library density is read exactly");
  Check((double)material.GetField("Young").GetValue(captured)==210e9,"native library Young modulus is read exactly");
  var derived=new XElement(entry);derived.Descendants().Single(e=>e.Name.LocalName=="GXY").Remove();
  var value=Activator.CreateInstance(material,true);parse.Invoke(null,new object[]{derived,value});
  Check(Math.Abs((double)material.GetField("Shear").GetValue(value)-210e9/(2*1.28))<.01,"missing shear modulus is derived and labelled");
  foreach(var property in new[]{"DENS","EX","SIGYLD","SIGXT"}){
   var bad=new XElement(entry);bad.Descendants().Single(e=>e.Name.LocalName==property).Remove();bool rejected=false;
   try{parse.Invoke(null,new object[]{bad,Activator.CreateInstance(material,true)});}catch(TargetInvocationException e){rejected=e.InnerException.Message.Contains(property);}
   Check(rejected,"missing "+property+" blocks calibration");
  }
  var storage=code.GetType("BeamNG.Cad.FramePipeline.BuildStorage");
  Directory.CreateDirectory(root);var settingsType=code.GetType("BeamNG.Cad.UI.ExporterSettings");
  var path=Path.Combine(root,"settings.xml");var settings=Activator.CreateInstance(settingsType,new object[]{path});
  Check((string)settingsType.GetProperty("SaveBuildReports").GetValue(settings,null)=="false","full reports default off");
  var output=Path.Combine(root,"new build directory");
  settingsType.GetProperty("FrameOutput").SetValue(settings,output,null);settingsType.GetProperty("SaveBuildReports").SetValue(settings,"true",null);
  settingsType.GetMethod("Save").Invoke(settings,null);settings=Activator.CreateInstance(settingsType,new object[]{path});
  Check((string)settingsType.GetProperty("FrameOutput").GetValue(settings,null)==output && (string)settingsType.GetProperty("SaveBuildReports").GetValue(settings,null)=="true","directory and report preference persist");
  var start=new ProcessStartInfo();storage.GetMethod("ConfigureScratch").Invoke(null,new object[]{start,output});
  Check(Directory.Exists(start.EnvironmentVariables["TEMP"]) && start.EnvironmentVariables["TEMP"].StartsWith(output+Path.DirectorySeparatorChar),"worker scratch follows the selected build drive");
  Check(start.EnvironmentVariables["TEMP"]==start.EnvironmentVariables["TMP"],"child processes receive matching temp paths");
  bool invalid=false;try{storage.GetMethod("EnsureDirectory").Invoke(null,new object[]{"relative-build"});}catch(TargetInvocationException){invalid=true;}
  Check(invalid,"relative build directory rejected");
 }
}
'@
[MaterialsStorageTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english\sldmaterials\solidworks materials.sldmat',(Join-Path $OutputDirectory ('material-storage-test-'+[Guid]::NewGuid().ToString('N'))))
