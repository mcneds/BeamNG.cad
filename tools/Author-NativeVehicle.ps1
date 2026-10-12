param(
 [Parameter(Mandatory=$true)][string]$SourceProject,
 [Parameter(Mandatory=$true)][string]$Plan,
 [Parameter(Mandatory=$true)][string]$Destination,
 [string]$OutputDirectory='beamng.cad/bin/joints-v41',
 [switch]$Resume,
 [string]$ProbeComponent,
 [string]$DebugGate
)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$SourceProject=(Resolve-Path -LiteralPath $SourceProject).Path
$Plan=(Resolve-Path -LiteralPath $Plan).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if((Test-Path -LiteralPath $Destination) -and -not $Resume){throw 'Use a fresh fixture directory or resume its unchanged native authoring'}
[void][IO.Directory]::CreateDirectory($Destination)
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[5..6]){[void][Reflection.Assembly]::LoadFrom($ref)}
$helper=Get-Content -Raw (Join-Path $PSScriptRoot 'New-SyntheticVehicle.ps1')
$start=$helper.IndexOf('using System;');$end=$helper.IndexOf("'@",$start)
$source=$helper.Substring($start,$end-$start)+(Get-Content -Raw (Join-Path $PSScriptRoot 'NativeVehicleAuthor.cs'))
Add-Type -ReferencedAssemblies $refs -TypeDefinition $source
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
$ownedPid=$null
$runFailed=$false
try {
 $process=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS\sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
 $ownedPid=$process.Id
 if($existing -contains $ownedPid){throw 'Refusing existing user process'}
 $until=(Get-Date).AddSeconds(120)
 do {$app=[SyntheticNativeCad]::Find($ownedPid);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and (Get-Date) -lt $until)
 if(-not $app){throw 'Owned SolidWorks did not register'}
 Write-Output "OWNED_CAD_PROCESS=$ownedPid"
 Write-Output "OWNED_HOST_PROCESS=$PID"
 [SyntheticNativeCad]::GuardOwnedPrompt($ownedPid)
 if($DebugGate){$gateDeadline=(Get-Date).AddMinutes(10);while(-not (Test-Path -LiteralPath $DebugGate)){if((Get-Date) -gt $gateDeadline){throw 'Debugger gate timed out'};Start-Sleep -Milliseconds 200}}
 if($ProbeComponent){[NativeVehicleAuthor]::CopyProbe($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$SourceProject,$Destination,$ProbeComponent)}
 else{[NativeVehicleAuthor]::Run($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$SourceProject,$Plan,$Destination,$Resume.IsPresent)}
} catch {
 $runFailed=$true
 Write-Output $_.Exception.ToString()
 throw
} finally {
 if($ownedPid -and $existing -notcontains $ownedPid){
  $cleanupError=$null;$forced=$false
  Write-Output 'Owned CAD cleanup starting'
  try{if($app){[SyntheticNativeCad]::Finish($app)}}catch{$cleanupError=$_.Exception.Message;Write-Warning ('Owned cleanup: '+$cleanupError)}
  Write-Output 'Owned CAD exit requested'
  $remaining=Get-Process -Id $ownedPid -ErrorAction SilentlyContinue
  if($remaining -and -not $remaining.WaitForExit(60000)){$forced=$true;Stop-Process -Id $ownedPid -ErrorAction SilentlyContinue}
  if(-not $process.WaitForExit(10000)){$cleanupError='Owned process did not finish shutdown within the deadline'}
  @{pid=$ownedPid;exit_code=$process.ExitCode;forced=$forced;cleanup_error=$cleanupError;run_failed=$runFailed} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Destination 'owned-process.json')
  if(-not $runFailed -and ($cleanupError -or $forced -or $process.ExitCode -ne 0)){throw 'Owned SolidWorks shutdown failed; inspect owned-process.json'}
 }
}
