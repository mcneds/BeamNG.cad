param([string]$OutputDirectory='beamng.cad/bin/cad-calibration',[Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$PreparedSource)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$PreparedSource=(Resolve-Path -LiteralPath $PreparedSource).Path
$assembly=[Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
$testRoot=Join-Path $OutputDirectory ('boundary-test-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($testRoot)
$settings=[Activator]::CreateInstance($assembly.GetType('BeamNG.Cad.UI.ExporterSettings'),@([string](Join-Path $testRoot 'settings.xml')))
$settings.CalibrationPythonExecutable=$PythonExecutable
$settings.FrameOutput=$testRoot
$method=$assembly.GetType('BeamNG.Cad.FramePipeline.CalibrationBuilder').GetMethod('PrepareAsync')
$task=$method.Invoke($null,@($settings,[string]$PreparedSource,$null,[Threading.CancellationToken]::None))
if(-not $task.Wait(30000)){throw 'Calibration worker boundary timed out'}
$job=$task.GetAwaiter().GetResult()
$review=Get-Content -LiteralPath (Join-Path $job 'review.json') -Raw | ConvertFrom-Json
if($review.approved -or $review.nodes.Count -eq 0 -or -not $review.graph_sha256){throw 'Expected an unapproved generation-specific graph'}
foreach($legacy in @('JBeamMaterialTuner.py','JBeamFlexbodyAssociator.py')){
    if(Test-Path -LiteralPath (Join-Path $job "source\$legacy")){throw "Calibrated worker selected legacy stage: $legacy"}
}
$manifest=Get-Content -LiteralPath (Join-Path $job 'source\generation.json') -Raw | ConvertFrom-Json
if($manifest.raw -ne 'mochi_raw.jbeam' -or $manifest.mesh -ne 'mochi.dae'){throw 'Missing explicit geometry/graph contract'}
Write-Output 'PASS C# worker uses deployed CAD calibration package and creates a new unapproved graph without legacy tuning or association'
Write-Output "BOUNDARY_EVIDENCE=$job"
