param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\beamng.cad\bin\quiet-materials'))
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
Add-Type -ReferencedAssemblies @('System.Core','System.Windows.Forms','System.Drawing') -TypeDefinition @'
using System;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Windows.Forms;
public static class MaterialUiCleanupSmoke {
 [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern IntPtr GetProp(IntPtr h,string name);
 [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(System.Drawing.Point point);
 static void Check(bool value,string message){if(!value)throw new Exception(message);Console.WriteLine("PASS "+message);}
 static void Set(Type type,object value,string name,object data){type.GetField(name,BindingFlags.Instance|BindingFlags.NonPublic).SetValue(value,data);}
 public static void Run(string path){
  var type=Assembly.LoadFrom(path).GetType("BeamNG.Cad.Preparation.MaterialUiUpdateScope");
  using(var window=new Form()){
   window.ShowInTaskbar=false;window.Show();var handle=window.Handle;
   foreach(var originallyVisible in new[]{true,false}){
    window.Visible=originallyVisible;
    var guard=FormatterServices.GetUninitializedObject(type);
    Set(type,guard,"frame",handle);Set(type,guard,"ownsRedraw",originallyVisible);
    foreach(var name in new[]{"trees","views"})Set(type,guard,name,Activator.CreateInstance(type.GetField(name,BindingFlags.Instance|BindingFlags.NonPublic).FieldType));
    if(originallyVisible)
    {
     using(var progress=new Form()){
      progress.ShowInTaskbar=false;progress.StartPosition=FormStartPosition.Manual;progress.Bounds=window.Bounds;var stop=new Button();progress.Controls.Add(stop);var cancelled=false;stop.Click+=(s,e)=>cancelled=true;
      progress.Show(window);
      SendMessage(handle,0xB,IntPtr.Zero,IntPtr.Zero);
      type.GetMethod("CoverDocumentTransitions").Invoke(guard,null);
      Application.DoEvents();stop.PerformClick();
      Check(IsWindowVisible(progress.Handle) && cancelled,"owned progress window and Stop remain interactive during frame redraw suppression");
      Check(WindowFromPoint(stop.PointToScreen(new System.Drawing.Point(10,10)))==stop.Handle,"workspace cover stays behind the progress window and Stop button");
     }
    }
    // No app stands in for a disconnected native application during cleanup.
    bool reported=false;try{((IDisposable)guard).Dispose();}catch(InvalidOperationException e){reported=e.Message.Contains("restore SolidWorks display");}
    Check(reported,"cleanup failure is reported");
    Check(IsWindowVisible(handle)==originallyVisible,"cleanup preserves original frame visibility despite a native failure");
    Check(GetProp(handle,"SysSetRedraw")==IntPtr.Zero,"cleanup failure still releases owned redraw lock");
    Check(Application.OpenForms.Count==1,"cleanup failure removes the workspace cover");
    ((IDisposable)guard).Dispose();Check(IsWindowVisible(handle)==originallyVisible,"repeated disposal does not change display state");
   }
  }
 }
}
'@
[MaterialUiCleanupSmoke]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'))
