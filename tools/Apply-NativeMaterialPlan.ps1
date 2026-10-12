param([Parameter(Mandatory=$true)][string]$Plan,[Parameter(Mandatory=$true)][string]$Destination,
 [string]$OutputDirectory)
# Explicit material edits only. Own one hidden session, back up every source part,
# verify native readback and geometry, and journal before saving. No assembly mates
# or component transforms are edited. Refuse to share an interactive session.
$ErrorActionPreference='Stop'
if(-not $OutputDirectory){$OutputDirectory=Join-Path $PSScriptRoot '../artifacts/actual-cad-integration-20261010'}
if(Get-Process SLDWORKS -ErrorAction SilentlyContinue){throw 'Close SolidWorks before this owned material operation'}
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use PowerShell -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Plan=(Resolve-Path -LiteralPath $Plan).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new destination for backups and audit'}
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Web.Extensions','System.Xml.Linq','System.Xml',
 (Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using System.Security.Cryptography;
using System.Xml.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class NativeMaterialPlan {
 public class Edit {public string path;public string configuration;public string part_material;public string database;public Dictionary<string,string> bodies;public bool rebuild_references;}
 public class Plan {public Edit[] parts;}
 static string Hash(string path){using(var f=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite))using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(f)).Replace("-","").ToLowerInvariant();}
 static object[] Bodies(PartDoc part){return (object[])part.GetBodies2((int)swBodyType_e.swAllBodies,false)??new object[0];}
 static string Reference(PartDoc part,Body2 body){return Convert.ToBase64String((byte[])((ModelDoc2)part).Extension.GetPersistReference3(body));}
 static Dictionary<string,double[]> Shape(PartDoc part){return Bodies(part).Cast<Body2>().ToDictionary(b=>Reference(part,b),b=>(double[])b.GetMassProperties(1));}
 static void SameShape(Dictionary<string,double[]> before,PartDoc part){
  var after=Shape(part);if(!before.Keys.OrderBy(x=>x).SequenceEqual(after.Keys.OrderBy(x=>x)))throw new Exception("Body ownership changed");
  foreach(var p in before){var a=after[p.Key];if(a.Length!=p.Value.Length||a.Where((v,i)=>Math.Abs(v-p.Value[i])>Math.Max(1e-12,Math.Abs(p.Value[i])*1e-8)).Any())throw new Exception("Geometry changed: "+p.Key);}
 }
 static object Read(PartDoc part,string config){
  return Bodies(part).Cast<Body2>().Select(b=>{string db;var name=b.GetMaterialPropertyName(config,out db);var scope="body";
   if(string.IsNullOrWhiteSpace(name)){name=part.GetMaterialPropertyName2(config,out db);scope="inherited part";}
   double? density=null;if(b.GetType()==0){var mass=(MassProperty2)((ModelDoc2)part).Extension.CreateMassProperty2();mass.UseSystemUnits=true;mass.SelectedItems=new[]{new System.Runtime.InteropServices.DispatchWrapper(b)};if(mass.Recalculate()&&mass.Volume>0)density=mass.Mass/mass.Volume;}
   return new {body=b.Name,name=name,database=db,assignment=scope,native_density_kg_m3=density,reference=Convert.ToBase64String((byte[])((ModelDoc2)part).Extension.GetPersistReference3(b)),unit_density_properties=(double[])b.GetMassProperties(1)};}).ToArray();
 }
 static void Verify(PartDoc part,Edit edit){
  string db;if(edit.part_material!=null&&part.GetMaterialPropertyName2(edit.configuration,out db)!=edit.part_material)throw new Exception("Part material readback failed");
  foreach(Body2 b in Bodies(part)){var n=b.GetMaterialPropertyName(edit.configuration,out db);if(string.IsNullOrWhiteSpace(n))n=part.GetMaterialPropertyName2(edit.configuration,out db);
   var expected=edit.bodies.ContainsKey(b.Name)?edit.bodies[b.Name]:edit.part_material;if(expected!=null&&n!=expected)throw new Exception("Body material readback failed: "+b.Name);}
 }
 public static void Run(string planFile,string destination){
  var json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};var plan=json.Deserialize<Plan>(File.ReadAllText(planFile));
  if(plan.parts.Length==0||plan.parts.Select(p=>p.path.ToLowerInvariant()).Distinct().Count()!=plan.parts.Length)throw new Exception("Empty or duplicate part plan");
  foreach(var e in plan.parts){if(!File.Exists(e.path)||!File.Exists(e.database)||e.bodies==null)throw new Exception("Missing source/database/body map");
   var entries=XDocument.Load(e.database).Descendants().Where(x=>x.Name.LocalName=="material").Select(x=>(string)x.Attribute("name")).ToArray();
   foreach(var n in e.bodies.Values.Concat(e.part_material==null?new string[0]:new[]{e.part_material}))if(entries.Count(x=>x==n)!=1)throw new Exception("Unknown/ambiguous material: "+n);
  }
  File.Copy(planFile,Path.Combine(destination,"plan.json"));var records=new List<object>();ISldWorks app=null;
  try {
   app=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));app.Visible=false;app.UserControl=false;
   for(int i=0;i<plan.parts.Length;i++){
    var e=plan.parts[i];var backup=Path.Combine(destination,i.ToString("D3")+"-"+Path.GetFileName(e.path));File.Copy(e.path,backup);string sourceHash=Hash(e.path);
    Console.WriteLine("MATERIAL "+(i+1)+"/"+plan.parts.Length+" "+Path.GetFileName(e.path));
    int error=0,warning=0;var model=(ModelDoc2)app.OpenDoc6(e.path,1,1,e.configuration,ref error,ref warning);
    if(model==null||model.IsOpenedReadOnly())throw new Exception("Part open failed: "+error);
    if(model.ConfigurationManager.ActiveConfiguration.Name!=e.configuration&&!model.ShowConfiguration2(e.configuration))throw new Exception("Configuration absent");
    var part=(PartDoc)model;var before=Shape(part);var materialsBefore=Read(part,e.configuration);
    var originalNames=Bodies(part).Cast<Body2>().ToDictionary(b=>Reference(part,b),b=>b.Name);
    for(var feature=(Feature)model.FirstFeature();feature!=null;feature=(Feature)feature.GetNextFeature()){
     var definition=feature.GetDefinition();var mirror=definition as MirrorPartFeatureData;var derived=definition as DerivedPartFeatureData;
     if(mirror!=null){Console.WriteLine("MIRROR_SOURCE "+mirror.PathName);if(e.rebuild_references){int se=0,sw=0;var source=app.OpenDoc6(mirror.PathName,1,3,"",ref se,ref sw);if(source==null)throw new Exception("Mirror source cannot be loaded: "+se);
       if(!mirror.AccessSelections(model,null))throw new Exception("Mirror access failed");
       if(!feature.ModifyDefinition(mirror,model,null)){mirror.ReleaseSelectionAccess();throw new Exception("Mirror refresh failed");}
     }}
     if(derived!=null)Console.WriteLine("DERIVED_SOURCE "+derived.PathName+" IMPORT_MATERIAL="+derived.ImportMaterial);
    }
    if(e.rebuild_references){if(!model.ForceRebuild3(false))throw new Exception("Reference rebuild failed");File.WriteAllText(Path.Combine(destination,"reference-rebuild.json"),json.Serialize(new{before=materialsBefore,after=Read(part,e.configuration)}));SameShape(before,part);}
    var bodies=Bodies(part).Cast<Body2>().ToDictionary(b=>b.Name);
    if(e.rebuild_references){var revised=new Dictionary<string,string>();foreach(Body2 b in Bodies(part)){var old=originalNames[Reference(part,b)];if(e.bodies.ContainsKey(old))revised.Add(b.Name,e.bodies[old]);}if(revised.Count!=e.bodies.Count)throw new Exception("Material target reference lost");e.bodies=revised;}
    if(e.bodies.Keys.Any(n=>!bodies.ContainsKey(n)))throw new Exception("Requested body absent");
    var visual=part.GetMaterialVisualProperties();
    if(visual!=null){visual.ApplyAppearance=false;visual.ApplyMaterialColorToPart=false;part.SetMaterialVisualProperties(visual,(int)swInConfigurationOpts_e.swThisConfiguration,null);}
    if(e.part_material!=null){
     int activationError=0;var active=(ModelDoc2)app.ActivateDoc3(model.GetTitle(),false,0,ref activationError);
     if(active==null||!string.Equals(active.GetPathName(),model.GetPathName(),StringComparison.OrdinalIgnoreCase))throw new Exception("Cannot activate material target: "+activationError);
     part.SetMaterialPropertyName2(e.configuration,e.database,e.part_material);
     string assignedDatabase;
     Console.WriteLine("PART_MATERIAL_READBACK "+part.GetMaterialPropertyName2(e.configuration,out assignedDatabase));
    }
    if(visual!=null)part.SetMaterialVisualProperties(visual,(int)swInConfigurationOpts_e.swThisConfiguration,null);
    foreach(var entry in e.bodies){var b=bodies[entry.Key];string currentDb;var current=b.GetMaterialPropertyName(e.configuration,out currentDb);
     if(current==entry.Value)continue;
     if(!b.Select2(false,null))throw new Exception("Body selection failed");
     var status=b.SetMaterialProperty(e.configuration,Path.GetFileName(e.database),entry.Value);
     if(status!=1){var mass=(MassProperty2)model.Extension.CreateMassProperty2();mass.UseSystemUnits=true;mass.SelectedItems=new[]{new System.Runtime.InteropServices.DispatchWrapper(b)};mass.Recalculate();throw new Exception("Body material assignment failed: "+entry.Key+"; status="+status+"; previous="+current+"; native_density="+(mass.Mass/mass.Volume));}}
    model.ClearSelection2(true);Verify(part,e);SameShape(before,part);
    var record=new Dictionary<string,object>{{"path",e.path},{"backup",backup},{"before_sha256",sourceHash},{"before",materialsBefore},{"after",Read(part,e.configuration)},{"status","verified_not_saved"}};
    records.Add(record);File.WriteAllText(Path.Combine(destination,"audit.json"),json.Serialize(records));
    model.SetSaveFlag();if(!model.Save3(1,ref error,ref warning)||error!=0)throw new Exception("Save failed: "+error);
    record["after_sha256"]=Hash(e.path);record["status"]="saved";File.WriteAllText(Path.Combine(destination,"audit.json"),json.Serialize(records));
    app.CloseDoc(model.GetTitle());
    model=(ModelDoc2)app.OpenDoc6(e.path,1,3,e.configuration,ref error,ref warning);if(model==null)throw new Exception("Reopen failed");
    Verify((PartDoc)model,e);SameShape(before,(PartDoc)model);record["status"]="saved_and_reopened_verified";
    File.WriteAllText(Path.Combine(destination,"audit.json"),json.Serialize(records));app.CloseDoc(model.GetTitle());
   }
  }finally{if(app!=null)app.ExitApp();}
  Console.WriteLine("VERIFIED_PARTS "+records.Count);
 }
}
'@
[NativeMaterialPlan]::Run($Plan,$Destination)
