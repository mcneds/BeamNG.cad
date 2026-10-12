param([int]$SolidWorksProcessId=36872,[string]$Action='inspect',[string]$OutputDirectory='artifacts/reconciliation')
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$helper=Get-Content (Join-Path $PSScriptRoot 'Test-CurrentAssignmentInspection.ps1') -Raw
$code=[regex]::Match($helper,"(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'RearHubs.cs') -Raw)
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'MirrorFrontSuspension.cs') -Raw)
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'RearHubRepair.cs') -Raw)
$code+="`r`n"+(Get-Content (Join-Path $PSScriptRoot 'RearHubMerge.cs') -Raw)
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[4..5]){[void][Reflection.Assembly]::LoadFrom($ref)}
Add-Type -ReferencedAssemblies $refs -TypeDefinition $code
if($Action -eq 'compile'){Write-Output 'PASS hub repair tooling compiles';return}
if($Action -eq 'repair'){[MirrorFrontSuspension]::RepairHubs($SolidWorksProcessId,$OutputDirectory)}
elseif($Action -eq 'verify'){[MirrorFrontSuspension]::VerifyHubReview($SolidWorksProcessId,$OutputDirectory)}
elseif($Action -eq 'merge'){[MirrorFrontSuspension]::MergeHubs($SolidWorksProcessId,$OutputDirectory)}
elseif($Action -eq 'audit'){[MirrorFrontSuspension]::AuditHubChanges($SolidWorksProcessId,$OutputDirectory)}
else{[RearHubs]::Run($SolidWorksProcessId,$Action,$OutputDirectory)}
