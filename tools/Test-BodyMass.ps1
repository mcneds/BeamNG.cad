param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\beamng.cad\bin\frame-validated'),[string]$Gate)
$ErrorActionPreference='Stop'
if(Get-Process SLDWORKS -ErrorAction SilentlyContinue){throw 'This test requires no existing SolidWorks session; it owns its temporary host.'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$root=Join-Path $OutputDirectory ('body-mass-test-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
$refs=@('System.Core','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class BodyMassSmoke {
 static void Check(bool ok,string message){if(!ok)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static void Box(ModelDoc2 part,double x,double width){
  part.ClearSelection2(true);
  Check(part.Extension.SelectByID2("Front Plane","PLANE",0,0,0,false,0,null,0),"box sketch plane");
  part.SketchManager.InsertSketch(true);part.SketchManager.CreateCornerRectangle(x,0,0,x+width,.1,0);part.SketchManager.InsertSketch(true);
  Check(part.FeatureManager.FeatureExtrusion2(true,false,false,0,0,.1,.1,false,false,false,false,0,0,false,false,false,false,false,true,true,0,0,false)!=null,"independent box created");
 }
 static void Save(ModelDoc2 doc,string path){int errors=0,warnings=0;Check(doc.Extension.SaveAs(path,0,1,null,ref errors,ref warnings),"temporary fixture saved");}
 public static void Run(string dll,string folder){
  var app=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));
  try {
   app.Visible=false;Console.WriteLine("OWNED_CAD_PID="+app.GetProcessID());
   var part=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
   Check(part!=null,"temporary part created");Box(part,0,.1);Box(part,.3,.2);
   Check(((object[])((PartDoc)part).GetBodies2((int)swBodyType_e.swSolidBody,false)).Length==2,"two unequal bodies");
   var databases=((System.Collections.IEnumerable)app.GetMaterialDatabases()).Cast<string>();
   var materialDatabase=databases.First(p=>Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
   ((PartDoc)part).SetMaterialPropertyName2(part.ConfigurationManager.ActiveConfiguration.Name,materialDatabase,"Plain Carbon Steel");
   string selectedDatabase;
   Check(((PartDoc)part).GetMaterialPropertyName2(part.ConfigurationManager.ActiveConfiguration.Name,out selectedDatabase)=="Plain Carbon Steel","known material assigned to the fixture");
   var partPath=Path.Combine(folder,"two-bodies.SLDPRT");Save(part,partPath);
   var assembly=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
   Check(assembly!=null,"temporary assembly created");
   var component=((AssemblyDoc)assembly).AddComponent5(partPath,0,"",false,"",0,0,0);
   Check(component!=null,"two-body component inserted");Save(assembly,Path.Combine(folder,"fixture.SLDASM"));
   assembly.ClearSelection2(true);Check(component.Select4(false,null,false),"component selected");
   var code=Assembly.LoadFrom(dll);var type=code.GetType("BeamNG.Cad.Preparation.FrameSelection");
   var selection=Activator.CreateInstance(type,app,assembly);var frame=type.GetMethod("Capture").Invoke(selection,null);
   var package=type.GetMethod("Export").Invoke(selection,new object[]{frame,Path.Combine(folder,"export")});
   var meshes=(System.Collections.IEnumerable)package.GetType().GetField("Meshes").GetValue(package);
   var masses=meshes.Cast<object>().Select(m=>Convert.ToDouble(m.GetType().GetField("MassKg").GetValue(m))).OrderBy(v=>v).ToArray();
   Check(masses.Length==2 && masses[0]>0,"each body has a positive mass");
   Check(Math.Abs(masses[1]/masses[0]-2)<1e-8,"body masses follow independent 1:2 volumes rather than repeating the part total");
   assembly.ClearSelection2(true);var total=assembly.Extension.CreateMassProperty();total.UseSystemUnits=true;
   Check(Math.Abs(masses.Sum()/total.Mass-1)<1e-8,"individual body masses sum to the assembly mass");
   var snapshot=type.GetMethod("ReadMaterials").Invoke(selection,new[]{frame});
   var records=((System.Collections.IEnumerable)snapshot.GetType().GetField("Bodies").GetValue(snapshot)).Cast<object>().ToArray();
   Check(records.All(r=>(string)r.GetType().GetField("Name").GetValue(r)=="Plain Carbon Steel" && r.GetType().GetField("Error").GetValue(r)==null),"native part material is inherited by both bodies");
   var overrideBody=(Body2)((object[])((PartDoc)part).GetBodies2((int)swBodyType_e.swSolidBody,false))[0];
   int activationError=0;app.ActivateDoc3(part.GetTitle(),false,0,ref activationError);
   var overrideStatus=overrideBody.SetMaterialProperty(part.ConfigurationManager.ActiveConfiguration.Name,Path.GetFileName(materialDatabase),"1060 Alloy");
   Check(overrideStatus==1,"isolated fixture body override assigned (API status "+overrideStatus+")");
   part.ForceRebuild3(false);
   app.ActivateDoc3(assembly.GetTitle(),false,0,ref activationError);
   snapshot=type.GetMethod("ReadMaterials").Invoke(selection,new[]{frame});
   records=((System.Collections.IEnumerable)snapshot.GetType().GetField("Bodies").GetValue(snapshot)).Cast<object>().ToArray();
   Check(records.All(r=>r.GetType().GetField("Error").GetValue(r)==null),"mixed native materials have valid physical properties");
   Check(records.Count(r=>(string)r.GetType().GetField("Name").GetValue(r)=="1060 Alloy")==1 && records.Count(r=>(string)r.GetType().GetField("Name").GetValue(r)=="Plain Carbon Steel")==1,"body override takes precedence without replacing the other body's inherited material: "+snapshot.GetType().GetMethod("Summary").Invoke(snapshot,null));
   Console.WriteLine("BODY_MASSES_KG="+string.Join(",",masses));Console.WriteLine("CAD_MASS_EVIDENCE="+folder);
  } finally {app.ExitApp();}
 }
}
'@
if($Gate){Write-Output "MASS_TEST_PID=$PID";while(-not (Test-Path -LiteralPath $Gate)){Start-Sleep -Milliseconds 250}}
[BodyMassSmoke]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$root)
