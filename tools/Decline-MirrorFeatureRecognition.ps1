param([int]$SolidWorksProcessId,[int]$WorkerProcessId)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public static class MirrorPrompt{[DllImport("user32.dll")]public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);}'
$processCondition=New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::ProcessIdProperty,$SolidWorksProcessId)
$featureCondition=New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::NameProperty,'FeatureWorks')
$noCondition=New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::NameProperty,'No')
$deadline=[DateTime]::UtcNow.AddMinutes(20)
while((Get-Process -Id $WorkerProcessId -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline){
 foreach($window in [Windows.Automation.AutomationElement]::RootElement.FindAll([Windows.Automation.TreeScope]::Children,$processCondition)){
  $dialog=$window.FindFirst([Windows.Automation.TreeScope]::Descendants,$featureCondition)
  if($dialog){
   $text=@($dialog.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)|ForEach-Object{$_.Current.Name}) -join ' '
   if($text -like '*Do you want to proceed with feature recognition?*'){
    $button=$dialog.FindFirst([Windows.Automation.TreeScope]::Descendants,$noCondition)
    if($button){[void][MirrorPrompt]::PostMessage([IntPtr]$button.Current.NativeWindowHandle,245,[IntPtr]::Zero,[IntPtr]::Zero);Write-Output 'Declined optional FeatureWorks recognition in copied part'}
   }
  }
 }
 Start-Sleep -Seconds 1
}
