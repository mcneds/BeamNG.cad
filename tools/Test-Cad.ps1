param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\beamng.cad\bin\Debug\net472'), [string]$Gate)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$root=Join-Path $OutputDirectory ('cad-smoke-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
$refs=@('System.Core','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
$code=@'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class CadSmoke
{
 static Assembly addin; static ISldWorks sw; static string root;
 static object Invoke(object target,string method,params object[] args) { try {return target.GetType().GetMethod(method).Invoke(target,args);} catch(TargetInvocationException e){throw e.InnerException;} }
 static object Create(string type,params object[] args) {return Activator.CreateInstance(addin.GetType("BeamNG.Cad.Preparation."+type),args);}
 static void Check(bool yes,string text){if(!yes)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static ModelDoc2 New(string template){var doc=(ModelDoc2)sw.NewDocument(template,0,0,0);if(doc==null)throw new Exception("Missing SolidWorks document template");return doc;}
 static void Save(ModelDoc2 doc,string path){int errors=0,warnings=0;Check(doc.Extension.SaveAs(path,0,1,null,ref errors,ref warnings),"fixture saved: "+Path.GetFileName(path));}
 static Component2 Add(ModelDoc2 assembly,string part,double[] transform){var c=((AssemblyDoc)assembly).AddComponent5(part,0,"",false,"",0,0,0);Check(c!=null,"component inserted");assembly.ClearSelection2(true);c.Select4(false,null,false);((AssemblyDoc)assembly).UnfixComponent();c.Transform2=(MathTransform)((MathUtility)sw.GetMathUtility()).CreateTransform(transform);assembly.ClearSelection2(true);return c;}
 static double[] Transform(double x,double y,double z,bool rotated=false,bool mirrored=false){return new double[]{rotated?0:1,rotated?1:0,0,rotated?-1:0,rotated?0:1,0,0,0,mirrored?-1:1,x,y,z,1,0,0,0};}
 public static void Run(string dll,string folder)
 {
  addin=Assembly.LoadFrom(dll);root=folder;sw=(ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
  var original=sw.ActiveDoc as ModelDoc2;var opened=new System.Collections.Generic.List<string>();
  try {
   if(System.Diagnostics.Debugger.IsAttached) System.Diagnostics.Debugger.Break();
   var part=New(sw.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart));opened.Add(part.GetTitle());
   Check(part.Extension.SelectByID2("Front Plane","PLANE",0,0,0,false,0,null,0),"fixture sketch plane selected");
   part.SketchManager.InsertSketch(true);
   part.SketchManager.CreateCornerRectangle(-1,-2,0,1,2,0);
   part.SketchManager.InsertSketch(true);
   Check(part.FeatureManager.FeatureExtrusion2(true,false,false,0,0,1,1,false,false,false,false,0,0,false,false,false,false,true,true,true,0,0,false)!=null,"box body created");
   var path=Path.Combine(root,"source.SLDPRT");Save(part,path);opened.Add(part.GetTitle());
   var sub=New(sw.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly));opened.Add(sub.GetTitle());
   Add(sub,path,Transform(1,2,3));var subPath=Path.Combine(root,"nested.SLDASM");Save(sub,subPath);opened.Add(sub.GetTitle());
   var asm=New(sw.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly));opened.Add(asm.GetTitle());
   var a=Add(asm,path,Transform(3,4,5,true));var b=Add(asm,path,Transform(-3,1,2));var nested=Add(asm,subPath,Transform(10,20,30,true));
   var mirror=Add(asm,path,Transform(7,8,9,false,true));
   var asmPath=Path.Combine(root,"fixture.SLDASM");Save(asm,asmPath);opened.Add(asm.GetTitle());
   var child=(Component2)((object[])nested.GetChildren())[0];
   asm.ClearSelection2(true); foreach(var selected in new[]{a,b,nested,child,mirror}) Check(selected.Select4(true,null,false),"fixture component selected");
   var selection=Create("FrameSelection",sw,asm);var assignment=Invoke(selection,"Capture");
   var summary=(string)Invoke(selection,"Summary",assignment);Check(summary.StartsWith("4 bodies"),"overlapping selections deduplicate to four instance bodies");
   var prep=addin.GetType("BeamNG.Cad.Preparation.PreparationFile").GetMethod("Load").Invoke(null,new object[]{asmPath});Invoke(prep,"Save",assignment);
   var loaded=addin.GetType("BeamNG.Cad.Preparation.PreparationFile").GetMethod("Load").Invoke(null,new object[]{asmPath});assignment=Invoke(loaded,"Frame",asm.ConfigurationManager.ActiveConfiguration.Name);
   Invoke(selection,"Export",assignment,Path.Combine(root,"meshes"));Check(Directory.GetFiles(Path.Combine(root,"meshes"),"*.stl").Length==4,"one STL per component instance");
   Invoke(selection,"Show",assignment);Check(((SelectionMgr)asm.SelectionManager).GetSelectedObjectCount2(-1)==5,"saved selections restored");
   object info;var selectedBody=(Body2)((object[])a.GetBodies3(-1,out info))[0];
   asm.ClearSelection2(true); Check(selectedBody.Select2(true,null),"fixture body selected");
   var bodyAssignment=Invoke(selection,"Capture");Invoke(selection,"Export",bodyAssignment,Path.Combine(root,"body-only"));
   Check(Directory.GetFiles(Path.Combine(root,"body-only"),"*.stl").Length==1,"body-only scope exports one body");
   b.Transform2=(MathTransform)((MathUtility)sw.GetMathUtility()).CreateTransform(Transform(-4,1,2));
   Invoke(selection,"Export",assignment,Path.Combine(root,"edited"));
   Check((string)Invoke(selection,"Summary",assignment)==summary,"assignments survive placement edit");
   asm.ClearSelection2(true);b.Select4(false,null,false);asm.Extension.DeleteSelection2(0);
   bool invalid=false;try{Invoke(selection,"Summary",assignment);}catch(InvalidOperationException){invalid=true;}
   Check(invalid,"deleted component produces invalid-reference diagnostics");
   Console.WriteLine("CAD_FIXTURE="+root);
  } catch(Exception error) {Console.WriteLine(error.ToString());throw;}
  finally {foreach(var title in opened.AsEnumerable().Reverse().Distinct())sw.CloseDoc(title);if(original!=null){int errors=0;sw.ActivateDoc3(original.GetTitle(),false,0,ref errors);}}
 }
}
'@
Add-Type -TypeDefinition $code -ReferencedAssemblies $refs
if ($Gate) { Write-Output "CAD_TEST_PID=$PID"; while(-not (Test-Path -LiteralPath $Gate)) { Start-Sleep -Milliseconds 250 } }
[CadSmoke]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$root)
& py -3.14 (Join-Path $PSScriptRoot '..\tests\check_cad_fixture.py') $root
if ($LASTEXITCODE -ne 0) { throw 'CAD coordinate or identity validation failed.' }
