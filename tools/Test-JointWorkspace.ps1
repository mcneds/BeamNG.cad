param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing','System.Web.Extensions','System.Runtime.Serialization' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Reflection;
using System.Windows.Forms;
using System.Drawing;
using System.Web.Script.Serialization;
public static class JointWorkspaceTest {
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine("PASS "+label);}
 static object Get(object o,string name){return o.GetType().GetField(name).GetValue(o);}
 static void Set(object o,string name,object value){o.GetType().GetField(name).SetValue(o,value);}
 static object New(Assembly a,string type,params object[] args){return Activator.CreateInstance(a.GetType("BeamNG.Cad."+type),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,args,null);}
 public static void Run(string dll,string folder){
  var code=Assembly.LoadFrom(dll);var type=code.GetType("BeamNG.Cad.Preparation.VehicleProject");
  var document=Path.Combine(folder,"fixture-"+Guid.NewGuid().ToString("N")+".SLDASM");File.WriteAllText(document,"offline migration fixture, not native CAD");
  var project=type.GetMethod("Open").Invoke(null,new object[]{document});type.GetMethod("Save").Invoke(project,null);
  var path=document+".beamng-project.json";var json=new JavaScriptSerializer();var data=json.Deserialize<System.Collections.Generic.Dictionary<string,object>>(File.ReadAllText(path));
  data["Version"]=2;data.Remove("JointWorkspace");var original=json.Serialize(data);File.WriteAllText(path,original);
  project=type.GetMethod("Load").Invoke(null,new object[]{path});var workspace=Get(project,"JointWorkspace");
  Check((string)Get(workspace,"Mode")=="legacy","version 2 loads without changing its physics route");
  var members=(IList)Get(workspace,"Members");var member=New(code,"Preparation.MovingMember");Set(member,"ComponentId","panel");Set(member,"Name","Panel shell");members.Add(member);
  var joint=New(code,"Preparation.JointDefinition");Set(joint,"Name","Upper ball");Set(joint,"Kind","spherical");Set(joint,"Status","approved");((IList)Get(workspace,"Joints")).Add(joint);
  var binding=New(code,"Preparation.HardpointBinding");Set(binding,"Request","FL.upper_inner_front");Set(binding,"ComponentId","fl_upper_wishbone");Set(binding,"JointId",Get(joint,"Id"));Set(binding,"AnchorId","captured_front_pivot");Set(binding,"Point","anchor");((IList)Get(workspace,"Bindings")).Add(binding);
  var connection=New(code,"Preparation.MountConnection");Set(connection,"ReleaseSet","left_clips");Set(connection,"AttachmentLength",.008);((IList)Get(project,"Connections")).Add(connection);
  Set(connection,"GeneratedSource","auto_connect");Set(connection,"GeneratedHash","saved-provenance");Set(connection,"UserEdited",true);Set(connection,"SupportPosition",new double[]{1,2,3});
  var skin=New(code,"Preparation.ComponentDefinition");Set(skin,"Name","Test skin");Set(skin,"Representation","visual_only");Set(skin,"MassPolicy","custom");Set(skin,"CustomMassKg",2.5);Set(skin,"VisualParentId","panel");Set(skin,"VisualParentMemberId",Get(member,"Id"));((IList)Get(project,"Components")).Add(skin);
  var placement=New(code,"Preparation.NativePlacement");Set(placement,"ComponentId","panel");Set(placement,"Fixed",true);((IList)Get(workspace,"Placements")).Add(placement);
  type.GetMethod("Save").Invoke(project,null);
  Check(File.ReadAllText(path+".v2.bak")==original,"migration preserves exact version 2 backup");
  project=type.GetMethod("Load").Invoke(null,new object[]{path});workspace=Get(project,"JointWorkspace");
  Check((int)Get(project,"Version")==3&&((IList)Get(workspace,"Members")).Count==1,"moving-member records survive a save/reload");
  var savedBinding=((IList)Get(workspace,"Bindings"))[0];Check((string)Get(savedBinding,"Point")=="anchor"&&(string)Get(savedBinding,"AnchorId")=="captured_front_pivot"&&(string)Get(savedBinding,"JointId")== (string)Get(joint,"Id"),"captured pivot retains its reviewed joint and distinct CAD point across reload");
  var saved=((IList)Get(project,"Connections"))[0];Check((string)Get(saved,"ReleaseSet")=="left_clips"&&Math.Abs((double)Get(saved,"AttachmentLength")-.008)<1e-12,"linked release and short connector length survive persistence");
  Check((bool)Get(saved,"UserEdited")&&(string)Get(saved,"GeneratedHash")=="saved-provenance"&&((double[])Get(saved,"SupportPosition"))[2]==3,"edited generated fastener and provenance survive reload");
  var savedSkin=((IList)Get(project,"Components"))[0];Check((string)Get(savedSkin,"Representation")=="visual_only"&&(string)Get(savedSkin,"MassPolicy")=="custom"&&(double)Get(savedSkin,"CustomMassKg")==2.5&&(string)Get(savedSkin,"VisualParentMemberId")== (string)Get(member,"Id"),"visual-only representation, positive mass and moving parent survive reload");
  Check(((IList)Get(workspace,"Placements")).Count==1&&(bool)Get(((IList)Get(workspace,"Placements"))[0],"Fixed"),"fixed native placement survives reload");
  var catalogType=code.GetType("BeamNG.Cad.Preparation.MvpCatalog");var catalog=catalogType.GetMethod("Load").Invoke(null,null);
  catalogType.GetMethod("AddMissingGroups").Invoke(catalog,new[]{project});
  var reference=(Control)New(code,"UI.ReferenceSkeleton");
  reference.GetType().GetMethod("Configure").Invoke(reference,new[]{catalog,project});
  var panel=(Control)New(code,"UI.JointWorkspacePanel",reference,new TabPage("Points"),new TabPage("Fasteners"));
  using(var form=new Form {Text="Joints & mounts - test fixture",Width=1100,Height=740}){
   form.Controls.Add(panel);form.Show();panel.GetType().GetMethod("Configure").Invoke(panel,new[]{catalog,project});Application.DoEvents();
   var list=(ListBox)panel.Controls.Find("JointRequests",true).Single();var search=(TextBox)panel.Controls.Find("JointSearch",true).Single();
   Check(list.Items.Count>20,"unified editor lists required hardpoints and saved joints");search.Text="upper ball";Application.DoEvents();Check(list.Items.Count>=1&&list.Items.Cast<object>().All(v=>v.ToString().IndexOf("upper",StringComparison.OrdinalIgnoreCase)>=0),"search finds joints and hardpoint requests");
   search.Clear();list.SelectedIndex=0;Application.DoEvents();Check(panel.Controls.Find("JointDetail",true).Single().Text.Length>20,"selection explains capture and review steps");
   using(var bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(0,0,bitmap.Width,bitmap.Height));bitmap.Save(Path.Combine(folder,"joints-and-mounts.png"));}
  }
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS migration, release persistence and unified editor checks");
 }
}
'@
[JointWorkspaceTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
