param([int]$SolidWorksProcessId,[string]$ProjectPath,[string]$Destination,[string]$OutputDirectory)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+@'
public static class CurrentNativeMass {
 public static void Run(int pid,string path,string destination){
 var app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});var model=(ModelDoc2)app.ActiveDoc;
 var json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};var project=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));
 if(!string.Equals(model.GetPathName(),(string)project["SourceDocument"],StringComparison.OrdinalIgnoreCase))throw new Exception("Wrong active document");
 var stamp=model.GetUpdateStamp();var dirty=model.GetSaveFlag();var utility=(MathUtility)app.GetMathUtility();var records=new Dictionary<string,object>();
 var sourceLookup=new Dictionary<string,ILookup<string,Body2>>();
 foreach(Dictionary<string,object> group in (IEnumerable)project["Components"]){
 Console.WriteLine("MASS "+group["Name"]);
 foreach(Dictionary<string,object> selection in (IEnumerable)group["Selections"]){
 if((string)selection["Kind"]!="body")throw new Exception("Expected persisted body assignment");
 var bodyRef=(string)selection["Reference"];var compRef=(string)selection["ComponentReference"];int error;
 var body=(Body2)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(bodyRef),out error);if(body==null||error!=0)throw new Exception("Body missing");
 var component=(Component2)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(compRef),out error);if(component==null||error!=0)throw new Exception("Component missing");
 var props=(double[])body.GetMassProperties(1);var transform=component.Transform2;
 var center=(MathPoint)utility.CreatePoint(props.Take(3).ToArray());if(transform!=null)center=(MathPoint)center.MultiplyTransform(transform);
 var axes=new List<double[]>();for(int i=0;i<3;i++){var unit=new double[3];unit[i]=1;var vector=(MathVector)utility.CreateVector(unit);if(transform!=null)vector=(MathVector)vector.MultiplyTransform(transform);axes.Add((double[])vector.ArrayData);}
 string id;using(var hash=System.Security.Cryptography.SHA256.Create())id="body_"+BitConverter.ToString(hash.ComputeHash(System.Text.Encoding.UTF8.GetBytes(compRef+"|"+bodyRef))).Replace("-","").ToLowerInvariant().Substring(0,24);
 double? effectiveMass=null,effectiveDensity=null;string massError=null;
 if(body.GetType()==0)try {
 var part=(ModelDoc2)component.GetModelDoc2();var key=part.GetPathName()+"|"+component.ReferencedConfiguration;
 if(part.ConfigurationManager.ActiveConfiguration.Name!=component.ReferencedConfiguration)throw new Exception("Inactive source configuration");
 ILookup<string,Body2> lookup;if(!sourceLookup.TryGetValue(key,out lookup)){lookup=(((PartDoc)part).GetBodies2(0,false) as object[]??new object[0]).Cast<Body2>().ToLookup(b=>b.Name);sourceLookup.Add(key,lookup);}
 var source=lookup[body.Name].SingleOrDefault();if(source==null)throw new Exception("Source body absent");
 var mass=(MassProperty2)part.Extension.CreateMassProperty2();mass.UseSystemUnits=true;mass.SelectedItems=new[]{new System.Runtime.InteropServices.DispatchWrapper(source)};
 if(!mass.Recalculate()||mass.Volume<=0)throw new Exception("Native mass calculation failed");effectiveDensity=mass.Mass/mass.Volume;
 if(props[3]<=0||Math.Abs(mass.Volume/props[3]-1)>1e-6)throw new Exception("Native selected mass volume mismatch");
 if(mass.Mass<=0||double.IsNaN(mass.Mass)||double.IsInfinity(mass.Mass))throw new Exception("Invalid native mass");effectiveMass=mass.Mass;
 }catch(Exception e){massError=e.Message;}
 records[id]=new{properties=props,center_assembly=(double[])center.ArrayData,axes_assembly=axes,body_kind=body.GetType(),effective_mass_kg=effectiveMass,effective_density_kg_m3=effectiveDensity,mass_error=massError,source="IBody2.GetMassProperties(1); assembly-transformed COM and basis; part-body MassProperty2 effective mass (may use document default density)"};
 }
 }
 if(model.GetUpdateStamp()!=stamp||model.GetSaveFlag()!=dirty)throw new Exception("CAD changed during native mass capture");
 File.WriteAllText(destination,json.Serialize(records));Console.WriteLine("MASS_CAPTURE "+records.Count);
 }
}
'@
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
[CurrentNativeMass]::Run($SolidWorksProcessId,$ProjectPath,$Destination)

