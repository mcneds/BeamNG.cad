param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core','System.Windows.Forms','System.Drawing' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Reflection;
using System.Linq.Expressions;
using System.Windows.Forms;
using System.Drawing;
public static class MountOwnerTest {
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine("PASS "+label);}
 public static void Run(string dll,string folder){
  var code=Assembly.LoadFrom(dll);var type=code.GetType("BeamNG.Cad.Preparation.ComponentDefinition");var panelType=code.GetType("BeamNG.Cad.UI.MountOwnerPanel");
  var items=(IList)Activator.CreateInstance(typeof(System.Collections.Generic.List<>).MakeGenericType(type));
  for(var i=0;i<3;i++){var item=Activator.CreateInstance(type,true);type.GetField("Id").SetValue(item,"id-"+i);type.GetField("Name").SetValue(item,i==2?"Nose panel":"Same name");items.Add(item);}
  using(var panel=(Control)Activator.CreateInstance(panelType,true))using(var form=new Form {Width=850,Height=300}){
   var changed=0;Action action=()=>changed++;var parameter=Expression.Parameter(type,"value");var handler=Expression.Lambda(typeof(Action<>).MakeGenericType(type),Expression.Invoke(Expression.Constant(action)),parameter).Compile();panelType.GetEvent("OwnerChanged").AddEventHandler(panel,handler);
   Action<string> select=id=>panelType.GetMethod("SelectOwner").Invoke(panel,new object[]{id});Action<string> bind=id=>panelType.GetMethod("SetComponents").Invoke(panel,new object[]{items,id});
   form.Controls.Add(panel);form.Show();bind("id-1");var combo=(ComboBox)panel.Controls.Find("MountOwner",true).Single();
   Check(combo.SelectedItem==items[1]&&changed==0,"duplicate names bind by stable component ID without user callbacks");
   select("id-2");Check(combo.SelectedItem==items[2]&&changed==0,"main component selection synchronizes silently");
   combo.SelectedIndex=0;Check(changed==1&&panelType.GetProperty("SelectedOwner").GetValue(panel,null)==items[0],"mount owner selection reports the chosen component");
   bind("id-0");Check(changed==1&&combo.SelectedItem==items[0],"refresh preserves selected owner without spurious changes");
   items.RemoveAt(0);bind("id-0");Check(combo.SelectedItem==items[0]&&changed==1,"removed owner safely falls back to an existing group");
   Application.DoEvents();Check(combo.Right<=panel.Width&&panel.Width<form.ClientSize.Width,"owner selector fits minimum workflow width");
   using(var image=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(image,new Rectangle(0,0,image.Width,image.Height));image.Save(Path.Combine(folder,"mount-owner.png"));}
   items.Clear();bind(null);Check(!combo.Enabled&&combo.SelectedItem==null&&changed==1,"empty project disables owner selection without stale owner");
  }
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS 7 mount owner checks");
 }
}
'@
[MountOwnerTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),[IO.Path]::GetFullPath($Destination))
