param([Parameter(Mandatory=$true)][int]$ProcessId, [string]$OpenDocument)
$ErrorActionPreference='Stop'
$dll=(Resolve-Path (Join-Path $PSScriptRoot '..\beamng.cad\bin\Debug\net472\SolidWorks.Interop.sldworks.dll')).Path
[void][Reflection.Assembly]::LoadFrom($dll)
Add-Type -ReferencedAssemblies $dll -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using SolidWorks.Interop.sldworks;
public static class SwConnection {
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out IBindCtx context);
 public static ISldWorks Connect(int pid) {
  IRunningObjectTable table;GetRunningObjectTable(0,out table);IEnumMoniker items;table.EnumRunning(out items);
  IBindCtx context;CreateBindCtx(0,out context);var moniker=new IMoniker[1];
  while(items.Next(1,moniker,IntPtr.Zero)==0){string name;moniker[0].GetDisplayName(context,null,out name);
   if(name=="SolidWorks_PID_"+pid){object app;table.GetObject(moniker[0],out app);return (ISldWorks)app;}}
  throw new InvalidOperationException("SolidWorks process not found in ROT: "+pid);
 }
 public static void Open(int pid,string file) {var app=Connect(pid);int errors=0,warnings=0;
  if(app.OpenDoc6(file,2,1,"",ref errors,ref warnings)==null)throw new Exception("Open failed: "+errors);
  app.Visible=true;
 }
}
'@
if($OpenDocument) { [SwConnection]::Open($ProcessId,$OpenDocument) }
