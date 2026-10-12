param([string]$OutputDirectory='artifacts/reconciliation',[string]$ReceiptPath)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
Add-Type -ReferencedAssemblies 'System.Core','System.Xml','System.Runtime.Serialization' -TypeDefinition @'
using System;
using System.IO;
using System.Collections;
using System.Linq;
using System.Reflection;
using System.Runtime.Serialization.Json;
public static class ProvenanceTest {
 static Assembly code;static Type owner;
 static object New(string n){return Activator.CreateInstance(code.GetType("BeamNG.Cad.Preparation."+n),true);}
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Set(object o,string n,object v){o.GetType().GetField(n).SetValue(o,v);}
 static object Call(string n,params object[] args){return owner.GetMethod(n,BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,args);}
 static void Check(bool b,string s){if(!b)throw new Exception(s);Console.WriteLine("PASS "+s);}
 public static void Receipt(string path){
  var receipt=code.GetType("BeamNG.Cad.Preparation.CompanionAssemblyLink").GetMethod("Read").Invoke(null,new object[]{path});
  var kept=((IEnumerable)Call("ReplacementIds",receipt)).Cast<string>().ToArray();Check(kept.Length>0,"saved working receipt is accepted and retains replacement ownership");
  foreach(var g in ((IEnumerable)Get(receipt,"Groups")).Cast<object>().Where(g=>(bool)Call("KeepsReplacement",g))){
   var members=(IList)Get(g,"Members");var parts=members!=null&&members.Count>0?members.Cast<object>():new[]{g};
   foreach(var p in parts){var origin=Call("AppearanceOrigin",receipt,p);Check(File.Exists((string)Get(origin,"SourceDocument"))&&File.Exists((string)Get(p,"Part")+".appearance-provenance.json"),(string)Get(p,"Name")+": saved source and part provenance exist");}
  }
 }
 public static void Run(string dll){
  code=Assembly.LoadFrom(dll);owner=code.GetType("BeamNG.Cad.Preparation.AssociationAssembly");
  var receipt=New("AssociationAssembly+Receipt");Set(receipt,"SourceDocument","old source");Set(receipt,"Configuration","Default");
  var ordinary=New("AssociationAssembly+Group");Set(ordinary,"Id","ordinary");
  var parent=New("AssociationAssembly+Group");Set(parent,"Id","rear");
  var member=New("AssociationAssembly+Group");Set(member,"Id","shaft");Set(member,"SourceOverride",true);Set(member,"SourceDocument","review assembly");Set(member,"SourceProject","review project");Set(member,"SourceConfiguration","Reviewed");Set(member,"NativePartCopy",true);Set(member,"AppearanceSnapshot",true);
  ((IList)Get(parent,"Members")).Add(member);((IList)Get(receipt,"Groups")).Add(ordinary);((IList)Get(receipt,"Groups")).Add(parent);
  var serializer=new DataContractJsonSerializer(receipt.GetType());using(var stream=new MemoryStream()){serializer.WriteObject(stream,receipt);stream.Position=0;receipt=serializer.ReadObject(stream);}
  parent=((IList)Get(receipt,"Groups"))[1];member=((IList)Get(parent,"Members"))[0];
  Check((int)Get(receipt,"Version")==4&&(bool)Get(member,"SourceOverride")&&(bool)Get(member,"NativePartCopy")&&(bool)Get(member,"AppearanceSnapshot"),"new receipt round-trip retains replacement and native appearance semantics");
  Check(!(bool)Call("KeepsReplacement",ordinary)&&(bool)Call("KeepsReplacement",parent),"ordinary groups update while member override protects the logical group");
  var removed=((IEnumerable)Call("RemovedSourceIds",receipt,new string[0])).Cast<string>().ToArray();
  Check(removed.SequenceEqual(new[]{"ordinary"}),"source deletion removes ordinary groups but retains reviewed replacements");
  var origin=Call("AppearanceOrigin",receipt,member);Check((string)Get(origin,"SourceDocument")=="review assembly"&&(string)Get(origin,"Configuration")=="Reviewed","appearance origin follows reviewed document and configuration");
  Check(object.ReferenceEquals(Call("AppearanceOrigin",receipt,ordinary),receipt),"legacy appearance source still uses root lineage");
  Set(member,"SourceDocument",null);bool failed=false;try{Call("AppearanceOrigin",receipt,member);}catch(TargetInvocationException e){failed=e.InnerException is InvalidDataException;}Check(failed,"incomplete replacement lineage cannot fall back to old source");
  var project=New("VehicleProject");var component=New("ComponentDefinition");Set(component,"Id","rear");Set(component,"Name","User edited donor");Set(component,"Thickness",0.007);((IList)Get(project,"Components")).Add(component);
  var item=New("AssociationAssembly+UpdateGroup");var stale=New("ComponentDefinition");Set(stale,"Id","rear");Set(stale,"Name","Old source");Set(item,"Source",stale);Set(item,"Old",parent);Set(item,"Replace",true);Set(item,"Rebind",true);
  Call("RetainReplacement",item,project);
  Check(!(bool)Get(item,"Replace")&&!(bool)Get(item,"Rebind")&&(string)Get(Get(item,"Source"),"Name")=="User edited donor"&&(double)Get(Get(item,"Source"),"Thickness")==0.007,"full refresh retains local settings, geometry and bindings");
  Check(!object.ReferenceEquals(Get(item,"Source"),component),"planning does not mutate live project definitions");
  ((IList)Get(project,"Components")).Clear();failed=false;try{Call("RetainReplacement",item,project);}catch(TargetInvocationException e){failed=e.InnerException is InvalidDataException;}Check(failed,"missing replacement fails instead of recreating old geometry");
 }
}
'@
[ProvenanceTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'))
if($ReceiptPath){[ProvenanceTest]::Receipt((Resolve-Path -LiteralPath $ReceiptPath).Path)}
