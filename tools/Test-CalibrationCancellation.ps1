param([string]$OutputDirectory='beamng.cad/bin/cad-calibration',[Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$testFolder=Join-Path $OutputDirectory ('calibration-cancel-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($testFolder)
$testScript=Join-Path $testFolder 'worker.py'
@'
import subprocess, sys, time
from pathlib import Path
root=Path(sys.argv[1]);child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])
(root/'child.txt').write_text(str(child.pid))
try:
    while not (root/'cancel.signal').exists():time.sleep(.05)
finally:
    child.terminate();child.wait(timeout=5)
    (root/'cleaned.txt').write_text('owned child shut down and evidence retained')
'@ | Set-Content -LiteralPath $testScript -Encoding UTF8
$assembly=[Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
$run=$assembly.GetType('BeamNG.Cad.FramePipeline.OwnedWorker').GetMethod('Run')
$cancel=New-Object Threading.CancellationTokenSource
try {
    $task=$run.Invoke($null,@([string]$PythonExecutable,[string]$testScript,[string]('"'+$testFolder+'"'),$null,$cancel.Token,[string](Join-Path $testFolder 'cancel.signal')))
    $deadline=[DateTime]::UtcNow.AddSeconds(15)
    while (-not (Test-Path -LiteralPath (Join-Path $testFolder 'child.txt'))) {
        if($task.IsCompleted){$task.GetAwaiter().GetResult();throw 'Worker exited before startup'}
        if([DateTime]::UtcNow -gt $deadline){throw 'Worker startup timed out'}
        Start-Sleep -Milliseconds 50
    }
    $cancel.Cancel()
    try {[void]$task.Wait(10000)} catch {if(-not $task.IsCanceled){throw}}
    if(-not $task.IsCanceled -or -not (Test-Path -LiteralPath (Join-Path $testFolder 'cleaned.txt'))){throw 'Graceful cancellation did not complete cleanup'}
    $childId=[int](Get-Content -LiteralPath (Join-Path $testFolder 'child.txt'))
    if(Get-Process -Id $childId -ErrorAction SilentlyContinue){throw 'Owned child survived cancellation'}
    Write-Output 'PASS calibration cancellation allows cleanup and retains cancellation evidence'
}finally{$cancel.Cancel();$cancel.Dispose()}
