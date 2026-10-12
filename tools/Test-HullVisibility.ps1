param([Parameter(Mandatory=$true)][int]$ProcessId,[Parameter(Mandatory=$true)][string]$HullFile,[string]$OutputDirectory)
$ErrorActionPreference='Stop'
if(-not $OutputDirectory){$OutputDirectory=Join-Path $PSScriptRoot '..\beamng.cad\bin\hull-visibility'}
$OutputDirectory=(Resolve-Path $OutputDirectory).Path
. (Join-Path $PSScriptRoot 'Connect-SolidWorks.ps1') -ProcessId $ProcessId
Add-Type -ReferencedAssemblies @('System.Core','System.Drawing','System.Windows.Forms',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll')) -TypeDefinition @'
using System;
using System.Drawing;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
public static class HullVisibilitySmoke {
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static object Field(object target,string name){return target.GetType().GetField(name,BindingFlags.NonPublic|BindingFlags.Instance).GetValue(target);}
 static void Set(object target,string name,object value){target.GetType().GetField(name,BindingFlags.NonPublic|BindingFlags.Instance).SetValue(target,value);}
 static int Orange(ModelDoc2 model,string file){Check(model.SaveBMP(file,0,0),"viewport evidence captured");int count=0;using(var image=new Bitmap(file))for(int x=0;x<image.Width;x+=2)for(int y=0;y<image.Height;y+=2){var c=image.GetPixel(x,y);if(c.R>230&&c.G>130&&c.G<200&&c.B<70)count++;}return count;}
 public static void Run(object connection,string directory,string hull){
 var app=(ISldWorks)connection;var model=(ModelDoc2)app.ActiveDoc;var dirty=model.GetSaveFlag();var features=model.GetFeatureCount();
 var output=Path.Combine(directory,"visibility-test-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(output);
 // Offset this test overlay so it is distinguishable from any user's existing preview.
 var lines=File.ReadAllLines(hull);var n=int.Parse(lines[1].Split(' ')[0]);
 for(int i=2;i<2+n;i++){var point=lines[i].Split(new[]{' ','\t'},StringSplitOptions.RemoveEmptyEntries).Select(v=>double.Parse(v,CultureInfo.InvariantCulture)).ToArray();point[0]+=.08;lines[i]=string.Join(" ",point.Select(v=>v.ToString("R",CultureInfo.InvariantCulture)));}
 var file=Path.Combine(output,"mochi_hull.off");File.WriteAllLines(file,lines);
 var asm=Assembly.LoadFrom(Path.Combine(directory,"beamng.cad.dll"));var previewType=asm.GetType("BeamNG.Cad.Preparation.HullPreview");
 var baseline=Orange(model,Path.Combine(output,"before.bmp"));
 var first=Activator.CreateInstance(previewType,app,model,file,"XYZ",false);
 var second=Activator.CreateInstance(previewType,app,model,file,"XYZ",false);
 Func<object,bool> visible=p=>(bool)previewType.GetProperty("Visible").GetValue(p,null);
 Action<object,bool> show=(p,v)=>previewType.GetMethod("SetVisible").Invoke(p,new object[]{v});
 try{
 Check(!visible(first)&&!visible(second),"each hull can start hidden");
 var bodies=(System.Collections.IList)Field(first,"bodies");var firstBody=bodies[0];var count=bodies.Count;Check(count<40,"hull edges batched into fewer than 40 paths");Console.WriteLine("DISPLAY_PATHS="+count);
 show(first,true);Check(visible(first)&&!visible(second),"showing one hull does not show another component's hull");
 var shown=Orange(model,Path.Combine(output,"shown.bmp"));Check(shown>baseline+20,"visible hull actually renders orange edges");
 using(var form=(Form)Activator.CreateInstance(asm.GetType("BeamNG.Cad.UI.FrameWorkflow"),app,model)){
 Set(form,"preview",first);Set(form,"prepared",output);var toggle=(CheckBox)Field(form,"showHull");var accept=(Button)Field(form,"accept");toggle.Enabled=true;accept.Enabled=true;
 form.StartPosition=FormStartPosition.Manual;form.Location=new Point(-30000,-30000);form.Show();Application.DoEvents();
 toggle.Checked=false;Application.DoEvents();Check(!visible(first)&&accept.Enabled&&(string)Field(form,"prepared")==output,"Hide preserves the prepared build and acceptance");
 Check(Orange(model,Path.Combine(output,"hidden.bmp"))<shown-20,"hidden hull disappears from the viewport");
 Check(bodies.Count==count&&object.ReferenceEquals(firstBody,bodies[0]),"hide retains existing bodies without regeneration");
 show(second,true);toggle.Checked=true;Check(visible(first)&&visible(second),"multiple hulls can be shown independently");
 toggle.Checked=false;Check(!visible(first)&&visible(second),"hiding one hull leaves another visible");
 show(second,false);toggle.Checked=true;
 var timings=new System.Collections.Generic.List<double>();
 for(int i=0;i<40;i++){var clock=Stopwatch.StartNew();show(first,i%2==0);timings.Add(clock.Elapsed.TotalMilliseconds);}
 timings.Sort();Console.WriteLine("TOGGLE_P95_MS="+timings[37].ToString("F1",CultureInfo.InvariantCulture));
 // External COM automation includes RPC latency; the 200 ms target is measured in the add-in host.
 show(first,true);
 Check(Orange(model,Path.Combine(output,"reshown.bmp"))>baseline+20,"the retained hull renders again after toggling");
 toggle.Checked=false;form.Close();
 }
 Check(bodies.Count==0,"closing the workflow disposes even a hidden hull");
 }finally{((IDisposable)first).Dispose();((IDisposable)second).Dispose();}
 Check(model.GetSaveFlag()==dirty&&model.GetFeatureCount()==features,"visibility changes preserve CAD features and save state");
 Console.WriteLine("VISIBILITY_EVIDENCE="+output);
 }
}
'@
[HullVisibilitySmoke]::Run([SwConnection]::Connect($ProcessId),$OutputDirectory,$HullFile)
