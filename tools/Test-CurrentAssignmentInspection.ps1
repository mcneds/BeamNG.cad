param(
 [Parameter(Mandatory=$true)][int]$SolidWorksProcessId,
 [Parameter(Mandatory=$true)][string]$ProjectPath,
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [Parameter(Mandatory=$true)][string]$Destination
)
# Explicit, reversible probe of an already-open assembly. Never opens, saves,
# closes, activates or rebuilds a document; restores the original selection.
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$ProjectPath=(Resolve-Path -LiteralPath $ProjectPath).Path
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Web.Extensions',
 (Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public static class CurrentAssignmentInspectionTest {
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out IBindCtx context);
 static ISldWorks Find(int pid){
  IRunningObjectTable table;IBindCtx context;GetRunningObjectTable(0,out table);CreateBindCtx(0,out context);IEnumMoniker list;table.EnumRunning(out list);var item=new IMoniker[1];
  try{while(list.Next(1,item,IntPtr.Zero)==0){try{string name;item[0].GetDisplayName(context,null,out name);if(name=="SolidWorks_PID_"+pid){object value;table.GetObject(item[0],out value);return (ISldWorks)value;}}finally{Marshal.ReleaseComObject(item[0]);}}throw new Exception("Requested SolidWorks process is not available.");}
  finally{Marshal.ReleaseComObject(list);Marshal.ReleaseComObject(context);Marshal.ReleaseComObject(table);}
 }
 static object Get(object value,string name){return value.GetType().GetField(name).GetValue(value);}
 static void Check(bool value,string text){if(!value)throw new Exception(text);Console.WriteLine("PASS "+text);}
 static object New(Type type,params object[] args){return Activator.CreateInstance(type,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,args,null);}
 static string[] Selected(ModelDoc2 model){var manager=(SelectionMgr)model.SelectionManager;return Enumerable.Range(1,manager.GetSelectedObjectCount2(-1)).Select(i=>manager.GetSelectedObjectMark(i)+":"+Convert.ToBase64String((byte[])model.Extension.GetPersistReference3(manager.GetSelectedObject6(i,-1)))).ToArray();}
 public static void Run(int pid,string dll,string path,string output){
  var originalFile=File.ReadAllBytes(path);var code=Assembly.LoadFrom(dll);
  var project=code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Load").Invoke(null,new object[]{path});
  var source=(string)Get(project,"SourceDocument");var app=Find(pid);var model=app.ActiveDoc as ModelDoc2;
  Check(model!=null && string.Equals(model.GetPathName(),source,StringComparison.OrdinalIgnoreCase),"active assembly matches saved project");
  var groups=((IEnumerable)Get(project,"Components")).Cast<object>().Where(c=>((IList)Get(c,"AppearanceSelections")).Count>0).ToArray();
  Check(groups.Length>0,"project has saved appearance assignments");
  var inspection=code.GetType("BeamNG.Cad.Preparation.AssignmentInspection");
  var selection=New(code.GetType("BeamNG.Cad.Preparation.FrameSelection"),app,model,true);
  var show=selection.GetType().GetMethod("Show");
  var original=Selected(model);var dirty=model.GetSaveFlag();var config=model.ConfigurationManager.ActiveConfiguration.Name;
  var results=new List<object>();
  using(var preserved=(IDisposable)New(code.GetType("BeamNG.Cad.Preparation.SelectionSnapshot"),model)){
   foreach(var group in groups){
    var assignment=inspection.GetMethod("Capture").Invoke(null,new object[]{group,true});
    inspection.GetMethod("CheckDocument").Invoke(null,new object[]{group,true,model.GetPathName()});
    show.Invoke(selection,new[]{assignment});
    var refs=((IEnumerable)Get(assignment,"Selections")).Cast<object>().ToArray();
    var selected=Selected(model);var expected=refs.Select(r=>"0:"+(string)Get(r,"Reference")).ToArray();
    if(!selected.SequenceEqual(expected))throw new Exception("Selected references differ for "+Get(group,"Name")+": expected="+string.Join(",",expected)+"; actual="+string.Join(",",selected));
    Check(true,"actual CAD selection matches "+Get(group,"Name")+" ("+refs.Length+")");
    results.Add(new {name=Get(group,"Name"),role=Get(group,"MvpRole"),references=refs.Length,kinds=refs.Select(r=>(string)Get(r,"Kind")).Distinct().ToArray()});
    // Resolve all entries before clearing the existing selection.
    var invalid=New(refs[0].GetType());invalid.GetType().GetField("Kind").SetValue(invalid,"body");invalid.GetType().GetField("Name").SetValue(invalid,"Unavailable regression reference");invalid.GetType().GetField("Reference").SetValue(invalid,"not-base64");((IList)Get(assignment,"Selections")).Add(invalid);
    bool failed=false;try{show.Invoke(selection,new[]{assignment});}catch(TargetInvocationException e){failed=e.InnerException is InvalidOperationException;}
    Check(failed && Selected(model).SequenceEqual(selected),"unavailable reference leaves the prior selection intact");
   }
  }
  Check(Selected(model).SequenceEqual(original),"original selection restored");
  Check(app.IsSame(app.ActiveDoc,model)==(int)swObjectEquality.swObjectSame && model.ConfigurationManager.ActiveConfiguration.Name==config && model.GetSaveFlag()==dirty,"active document, configuration and dirty flag unchanged");
  Check(File.ReadAllBytes(path).SequenceEqual(originalFile),"saved project remains byte-identical");
  File.WriteAllText(Path.Combine(output,"native-inspection.json"),new JavaScriptSerializer().Serialize(new {status="passed",process_id=pid,project=path,groups=results,restored_selection_count=original.Length,scope="Saved appearance highlighting and failed-reference preservation in existing SolidWorks; no document saves, exports, full workflow launch or zoom."}));
 }
}
'@
[CurrentAssignmentInspectionTest]::Run($SolidWorksProcessId,(Join-Path $OutputDirectory 'beamng.cad.dll'),$ProjectPath,[IO.Path]::GetFullPath($Destination))
