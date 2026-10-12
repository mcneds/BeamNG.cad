param([int]$SolidWorksProcessId=36872,[string]$OutputDirectory='beamng.cad/bin/Debug/net472',[string]$Destination='H:/beamng project programs/BeamNG.cad/WorkingAsm/rear-donor-review-20261010-01',[string]$Action='prepare')
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'MirrorFrontSuspension.cs') -Raw)+"`r`n"+(Get-Content (Join-Path $PSScriptRoot 'RearCompanion.cs') -Raw)
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'RearHalfshafts.cs') -Raw)
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'RearPromotion.cs') -Raw)
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
if($Action -eq 'compile'){Write-Output 'PASS rear companion tool compiles';return}
try{[MirrorFrontSuspension]::RearRun($SolidWorksProcessId,$OutputDirectory,[IO.Path]::GetFullPath($Destination),$Action)}catch{Write-Output $_.Exception.ToString();throw}
