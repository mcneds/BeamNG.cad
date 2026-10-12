param(
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [Parameter(Mandatory=$true)][string]$Receipt,
 [Parameter(Mandatory=$true)][string]$Destination,
 [string]$PythonExecutable='H:/beamng project programs/BeamNG.cad/.venv/Scripts/python.exe'
)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Receipt=(Resolve-Path -LiteralPath $Receipt).Path
if(Test-Path -LiteralPath $Destination){throw 'Use a fresh reset evidence directory'}
[void][IO.Directory]::CreateDirectory($Destination)
$Destination=(Resolve-Path -LiteralPath $Destination).Path
Add-Type -ReferencedAssemblies 'System.Core','System.Web.Extensions' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Web.Script.Serialization;
public static class TemplateResetTest {
 static readonly JavaScriptSerializer Json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};
 static object Get(object value,string name){return value.GetType().GetField(name).GetValue(value);}
 static void Set(object value,string name,object data){value.GetType().GetField(name).SetValue(value,data);}
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static void Write(string path,object value){File.WriteAllText(path,Json.Serialize(value));}
 static object Candidate(object plan){return plan.GetType().GetProperty("Candidate").GetValue(plan,null);}
 public static void Run(string dll,string receipt,string folder,string python){
  var code=Assembly.LoadFrom(dll);var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject");
  var resetType=code.GetType("BeamNG.Cad.Preparation.TemplateProjectReset");
  var source=File.ReadAllBytes(Path.Combine(Path.GetDirectoryName(receipt),"project.snapshot.json"));
  var doc=Json.Deserialize<Dictionary<string,object>>(System.Text.Encoding.UTF8.GetString(source));
  var identity=new Dictionary<string,object>{{"id",Guid.NewGuid().ToString("N")},{"namespace","reset_fixture_"+Guid.NewGuid().ToString("N").Substring(0,8)}};
  doc["Identity"]=identity;doc["SourceDocument"]=Path.Combine(folder,"owned-fixture.SLDASM");doc["PhysicsTemplateReceipt"]=receipt;
  var originalComponents=((ArrayList)doc["Components"]).Count;
  var parts=(ArrayList)doc["Components"];var engine=parts.Cast<Dictionary<string,object>>().Single(c=>(string)c["MvpRole"]=="engine");
  var expectedName=(string)engine["Name"];engine["Name"]="Accidental CAD reassignment";engine["AppearanceDirectory"]="wrong-appearance";
  parts.Add(new Dictionary<string,object>{{"Id","accidental"},{"Name","Extra CAD group"},{"MvpRole","accessory"}});
  var path=Path.Combine(folder,"project.json");Write(path,doc);var before=File.ReadAllBytes(path);
  var profile=path+".profile.json";File.WriteAllText(profile,"profile preserved");
  var plan=Activator.CreateInstance(resetType,new object[]{path});var candidate=Candidate(plan);
  Check(File.ReadAllBytes(path).SequenceEqual(before),"staging reset leaves current project untouched");
  Check(((IList)Get(candidate,"Components")).Count==originalComponents,"staged reset removes accidental extra group");
  var resetEngine=((IList)Get(candidate,"Components")).Cast<object>().Single(c=>(string)Get(c,"MvpRole")=="engine");
  Check((string)Get(resetEngine,"Name")==expectedName&&(string)Get(resetEngine,"AppearanceDirectory")!="wrong-appearance","baseline ownership and appearance restored");
  Check((string)Get(Get(candidate,"Identity"),"Namespace")== (string)identity["namespace"],"user package identity preserved");
  // A worker failure is a plan that never commits: even its staged candidate
  // is serialized to a separate job file, never over the user's project.
  var job=Path.Combine(folder,"reset-job.json");
  code.GetType("BeamNG.Cad.Preparation.JsonFile").GetMethod("Write").MakeGenericMethod(projectType).Invoke(null,new object[]{job,candidate});
  var output=Path.Combine(folder,"reset-build");
  var worker=Path.Combine(Path.GetDirectoryName(dll),"FramePipeline","component_worker.py");
  var start=new ProcessStartInfo(python,"\""+worker+"\" fork-template --project \""+job+"\" --output \""+output+"\""){
   UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
  start.EnvironmentVariables["OPENBLAS_NUM_THREADS"]="1";
  using(var process=Process.Start(start)){
   var stdout=process.StandardOutput.ReadToEndAsync();var stderr=process.StandardError.ReadToEndAsync();
   if(!process.WaitForExit(120000)){process.Kill();throw new Exception("Reset worker timeout");}
   File.WriteAllText(Path.Combine(folder,"worker.log"),stdout.Result+stderr.Result);Check(process.ExitCode==0,"actual fork worker packages baseline");
  }
  Check(File.ReadAllBytes(path).SequenceEqual(before),"completed worker still has not overwritten assignments");
  resetType.GetMethod("Commit").Invoke(plan,new object[]{output});
  var backup=(string)resetType.GetProperty("BackupPath").GetValue(plan,null);
  Check(File.ReadAllBytes(backup).SequenceEqual(before),"durable backup exactly preserves prior assignments");
  var restored=projectType.GetMethod("Load").Invoke(null,new object[]{path});
  Check(((IList)Get(restored,"Components")).Count==originalComponents,"committed project has baseline component count");
  Check((string)Get(restored,"SourceDocument")== (string)doc["SourceDocument"],"current CAD document preserved");
  Check(File.ReadAllText(profile)=="profile preserved","mod profile unchanged");
  Check(File.Exists((string)Get(restored,"LastBuildReceipt"))&&File.Exists((string)Get(restored,"TemplateDefinitionPath")),"new package and local hardpoints exist");
  Check(File.ReadAllBytes(Path.Combine(Path.GetDirectoryName(receipt),"project.snapshot.json")).SequenceEqual(source),"original template snapshot unchanged");
  var migration=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(output,"provenance","namespace-migration.json")));
  Check((bool)migration["physical_values_preserved"],"fork preserves baseline physical values");
  var racing=Activator.CreateInstance(resetType,new object[]{path});
  Set(restored,"SourceDocument","concurrent edit");restored.GetType().GetMethod("Save").Invoke(restored,null);var edited=File.ReadAllBytes(path);
  bool rejected=false;try{resetType.GetMethod("Commit").Invoke(racing,new object[]{output});}catch(TargetInvocationException e){rejected=e.InnerException.Message.Contains("changed during reset");}
  Check(rejected&&File.ReadAllBytes(path).SequenceEqual(edited),"concurrent project edits block commit without data loss");
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS");
 }
}
'@
[TemplateResetTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$Receipt,$Destination,$PythonExecutable)
