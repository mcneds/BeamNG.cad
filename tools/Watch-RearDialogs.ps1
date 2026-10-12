param([int]$Seconds=180,[int]$SolidWorksProcessId=36872)
$ErrorActionPreference='Stop'
Add-Type @'
using System;using System.Text;using System.Collections.Generic;using System.Runtime.InteropServices;
public class RearDialogWatcher {
 delegate bool E(IntPtr h,IntPtr l);
 [DllImport("user32.dll")]static extern bool EnumWindows(E e,IntPtr l);
 [DllImport("user32.dll")]static extern bool EnumChildWindows(IntPtr h,E e,IntPtr l);
 [DllImport("user32.dll")]static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")]static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetWindowText(IntPtr h,StringBuilder s,int c);
 [DllImport("user32.dll")]static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
 static string Text(IntPtr h){var s=new StringBuilder(4096);GetWindowText(h,s,s.Capacity);return s.ToString();}
 public static string[] Scan(int pid){var log=new List<string>();EnumWindows((h,l)=>{uint p;GetWindowThreadProcessId(h,out p);if(p!=pid||!IsWindowVisible(h))return true;var title=Text(h);if(title!="FeatureWorks"&&title!="What's Wrong"&&title!="SOLIDWORKS")return true;var children=new Dictionary<IntPtr,string>();EnumChildWindows(h,(c,x)=>{children[c]=Text(c);return true;},IntPtr.Zero);var all=string.Join(" ",children.Values);string button=null;if(title=="FeatureWorks"&&all.IndexOf("feature recognition",StringComparison.OrdinalIgnoreCase)>=0)button="No";if(title=="What's Wrong")button="Close";if(title=="SOLIDWORKS"&&all.IndexOf("critically low",StringComparison.OrdinalIgnoreCase)>=0)button="No";if(button!=null)foreach(var c in children)if(c.Value.Replace("&","")==button){log.Add(title+": "+all+" -> "+button);PostMessage(c.Key,0xF5,IntPtr.Zero,IntPtr.Zero);break;}return true;},IntPtr.Zero);return log.ToArray();}
}
'@
$deadline=[DateTime]::UtcNow.AddSeconds($Seconds)
do { [RearDialogWatcher]::Scan($SolidWorksProcessId); Start-Sleep -Seconds 2 } while([DateTime]::UtcNow -lt $deadline)
