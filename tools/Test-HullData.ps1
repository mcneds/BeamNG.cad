param([string]$OutputDirectory='beamng.cad/bin/responsive-hull')
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
$fixture=(Resolve-Path (Join-Path $PSScriptRoot '../tests/fixtures/internal-motion.off')).Path
Add-Type -ReferencedAssemblies @('System.Core','System.Runtime.Serialization') -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Reflection;
public static class HullDataSmoke {
 static void Check(bool value,string text){if(!value)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static object Get(object value,string name){return value.GetType().GetField(name).GetValue(value);}
 static void Set(object value,string name,object data){value.GetType().GetField(name).SetValue(value,data);}
 static string Key(double[] a,double[] b){var x=string.Join(",",a);var y=string.Join(",",b);return string.CompareOrdinal(x,y)<0?x+"|"+y:y+"|"+x;}
 public static void Run(string directory,string file){
  var asm=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));
  var type=asm.GetType("BeamNG.Cad.Preparation.HullPreview");
  var flags=BindingFlags.Static|BindingFlags.NonPublic;
  var edges=(double[][][])type.GetMethod("Read",flags).Invoke(null,new object[]{file,"XYZ"});
  var paths=(double[][][])type.GetMethod("Paths",flags).Invoke(null,new object[]{edges});
  var original=edges.Select(e=>Key(e[0],e[1])).OrderBy(x=>x).ToArray();
  var output=paths.SelectMany(p=>Enumerable.Range(1,p.Length-1).Select(i=>Key(p[i-1],p[i]))).OrderBy(x=>x).ToArray();
  Check(original.SequenceEqual(output),"batched paths preserve every edge exactly once");
  Check(paths.All(p=>p.Length>1&&p.Distinct().Count()==p.Length),"paths have no zero edges or repeated vertices");
  var isolated=new[]{new[]{new[]{10d,0d,0d},new[]{11d,0d,0d}},new[]{new[]{20d,0d,0d},new[]{21d,0d,0d}}};
  var islands=(double[][][])type.GetMethod("Paths",flags).Invoke(null,new object[]{isolated});
  Check(islands.Length==2&&islands.All(p=>p.Length==2),"separate components get no invented connecting edges");
  var root=Path.Combine(directory,"migration-test-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
  var document=Path.Combine(root,"fixture.SLDASM");var path=document+".truemesh-prep.json";
  var prepType=asm.GetType("BeamNG.Cad.Preparation.PreparationFile");var prep=Activator.CreateInstance(prepType);Set(prep,"SourceDocument",document);
  var assignment=Activator.CreateInstance(asm.GetType("BeamNG.Cad.Preparation.FrameAssignment"));Set(assignment,"Configuration","Default");
  var hull=Get(assignment,"Hull");Set(hull,"Orientation","+X,+Y");Set(hull,"CoordinateConvention",null);((IList)Get(prep,"Assignments")).Add(assignment);
  var json=asm.GetType("BeamNG.Cad.Preparation.JsonFile");json.GetMethod("Write").MakeGenericMethod(prepType).Invoke(null,new object[]{path,prep});
  var before=File.ReadAllBytes(path);var loaded=prepType.GetMethod("Load").Invoke(null,new object[]{document});
  var restored=Get(((IList)Get(loaded,"Assignments"))[0],"Hull");
  Check((string)Get(restored,"Orientation")=="X-ZY"&&(string)Get(restored,"CoordinateConvention")=="solidworks-y-up-to-beamng-z-up-v1","old editable axes migrate to fixed versioned convention");
  var backups=Directory.GetFiles(root,"*.coordinates-*.bak");Check(backups.Length==1&&before.SequenceEqual(File.ReadAllBytes(backups[0])),"migration preserves exact previous assignment bytes");
  prepType.GetMethod("Load").Invoke(null,new object[]{document});Check(Directory.GetFiles(root,"*.coordinates-*.bak").Length==1,"migration is idempotent");
  var old=json.GetMethod("Read").MakeGenericMethod(prepType).Invoke(null,new object[]{backups[0]});
  Check((string)Get(Get(((IList)Get(old,"Assignments"))[0],"Hull"),"Orientation")=="+X,+Y","archived JSON retains its recorded orientation");
 }
}
'@
[HullDataSmoke]::Run($OutputDirectory,$fixture)
