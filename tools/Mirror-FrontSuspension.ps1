param([int]$SolidWorksProcessId,[string]$OutputDirectory='beamng.cad/bin/Debug/net472',[string]$Destination,[ValidateSet('prepare','inspect','apply','verify','project','recover','releaseoriginal','status','tidy','steering','steeringdrive','finish','promote','closeparts')][string]$Action='prepare')
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'MirrorFrontSuspension.cs') -Raw)
$refs=@('System.Core','System.Web.Extensions',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[2..3]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
try{[MirrorFrontSuspension]::Run($SolidWorksProcessId,$OutputDirectory,[IO.Path]::GetFullPath($Destination),$Action)}catch{Write-Output $_.Exception.ToString();throw}








