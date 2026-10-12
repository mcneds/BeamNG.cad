param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Web.Extensions','System.Runtime.Serialization' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Reflection;
public static class RearLayoutTest {
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Put(object o,string n,object v){o.GetType().GetField(n).SetValue(o,v);}
 static object New(Assembly a,string n){return Activator.CreateInstance(a.GetType("BeamNG.Cad.Preparation."+n),true);}
 static object Prop(object o,string n){return o.GetType().GetProperty(n).GetValue(o);}
 static void Check(bool v,string message){if(!v)throw new Exception(message);Console.WriteLine("PASS "+message);}
 public static void Run(string dll,string output){
  var a=Assembly.LoadFrom(dll);var p=New(a,"VehicleProject");var c=a.GetType("BeamNG.Cad.Preparation.MvpCatalog").GetMethod("Load").Invoke(null,null);
  Func<object[]> roles=()=>((IEnumerable)c.GetType().GetMethod("ActiveRoles").Invoke(c,new[]{p})).Cast<object>().ToArray();
  Action populate=()=>c.GetType().GetMethod("AddMissingGroups").Invoke(c,new[]{p});
  Func<string,object> role=id=>roles().Single(r=>(string)Get(r,"Id")==id);
  Func<string,string[]> points=id=>((IEnumerable)Prop(role(id),"Hardpoints")).Cast<string>().ToArray();
  populate();var groups=(IList)Get(p,"Components");
  var arm=groups.Cast<object>().Single(v=>(string)Get(v,"MvpRole")=="rl_trailing_arm");Put(arm,"Name","My saved CAD arm");
  var selection=New(a,"SelectionReference");Put(selection,"Reference","saved-reference");((IList)Get(arm,"Selections")).Add(selection);
  Check(points("rl_trailing_arm").Contains("hub_center"),"existing trailing-arm option keeps its hub hardpoints");
  var choice=New(a,"MvpTemplateChoice");Put(choice,"Category","rear_suspension");Put(choice,"Template","trailing_radius_toe");((IList)Get(p,"MvpTemplates")).Add(choice);
  populate();var count=groups.Count;populate();Check(groups.Count==count,"reapplying layout does not duplicate groups");
  Check(groups.Cast<object>().Single(v=>(string)Get(v,"MvpRole")=="rl_trailing_arm")==arm && ((IList)Get(arm,"Selections")).Count==1,"switching layout preserves saved arm and CAD assignment");
  Check(points("rl_trailing_arm").Contains("carrier_joint")&&!points("rl_trailing_arm").Contains("hub_center"),"linked arm requests its carrier ball centre instead of a hub");
  Check(points("rl_upright").Contains("upper_radius_joint")&&points("rl_upright").Contains("lower_radius_joint"),"carrier requests all rod ball centres");
  Check(new[]{"rl_upper_radius_rod","rl_lower_radius_rod","rr_upper_radius_rod","rr_lower_radius_rod"}.All(id=>points(id).SequenceEqual(new[]{"chassis_joint","upright_joint"})),"both ends of each radius rod are requested");
  Put(choice,"Template","trailing_arm");Check(points("rl_trailing_arm").Contains("hub_center"),"changing layout does not mutate catalog defaults");
  Check(!roles().Any(v=>((string)Get(v,"Id")).Contains("radius_rod")),"original layout does not require radius rods");
  Check(groups.Count==count,"inactive assignments retained when returning to original layout");
  File.WriteAllText(Path.Combine(output,"result.txt"),"PASS: 9 rear layout assertions");
 }
}
'@
[RearLayoutTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
