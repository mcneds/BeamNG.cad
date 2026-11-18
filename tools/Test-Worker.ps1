param([string]$OutputDirectory,
      [Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '..\beamng.cad\bin\gui-check' }
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$folder = Join-Path $OutputDirectory ('worker-smoke-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($folder)
$script = Join-Path $folder 'worker.py'
@'
import os, subprocess, sys, time, tempfile
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
Path(sys.argv[1]+'.temp').write_text(tempfile.gettempdir())
Path(sys.argv[1]).write_text(str(os.getpid()) + ',' + str(child.pid))
time.sleep(120)
'@ | Set-Content -LiteralPath $script -Encoding UTF8
$assembly = [Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
$run = $assembly.GetType('BeamNG.Cad.FramePipeline.OwnedWorker', $true).GetMethod('RunWithScratch')
# Exercise the real gated launcher from outside the worker's directory, including
# nested entry points, arguments with spaces, and import-error reporting.
$imports = Join-Path $folder 'nested worker'
[void][IO.Directory]::CreateDirectory($imports)
[IO.File]::WriteAllText((Join-Path $imports 'sibling.py'), 'VALUE = "sibling loaded"')
$entry = Join-Path $imports 'entry.py'
@'
import sys
from pathlib import Path
from sibling import VALUE
assert Path(sys.argv[0]).resolve() == Path(__file__).resolve()
assert sys.argv[2] == 'argument with spaces'
assert Path.cwd() != Path(__file__).parent
Path(sys.argv[1]).write_text(VALUE)
'@ | Set-Content -LiteralPath $entry -Encoding UTF8
$importResult = Join-Path $folder 'import result.txt'
$task = $run.Invoke($null, @([string]$PythonExecutable, [string]$entry, [string]('"'+$importResult+'" "argument with spaces"'), $null, [Threading.CancellationToken]::None, $null, [string]$folder))
if(-not $task.Wait(15000)){throw 'Sibling import smoke test timed out'}
if((Get-Content -LiteralPath $importResult -Raw) -ne 'sibling loaded'){throw 'Worker did not import its sibling module'}
Write-Output 'PASS gated worker imports siblings from a nested script directory and preserves arguments'
$prepare = Join-Path $OutputDirectory 'FramePipeline/prepare_frame.py'
$task = $run.Invoke($null, @([string]$PythonExecutable, [string]$prepare, '--help', $null, [Threading.CancellationToken]::None, $null, [string]$folder))
if(-not $task.Wait(15000)){throw 'Preparation import smoke test timed out'}
Write-Output 'PASS shipped preparation entry point imports successfully through the gated worker'
[IO.File]::WriteAllText($entry, 'import deliberately_missing_worker_smoke_module')
$task = $run.Invoke($null, @([string]$PythonExecutable, [string]$entry, '', $null, [Threading.CancellationToken]::None, $null, [string]$folder))
try { if(-not $task.Wait(15000)){throw 'Import failure smoke test timed out'}; throw 'Missing import unexpectedly succeeded' }
catch {
    if(-not $task.IsFaulted -or $task.Exception.InnerException.Message -notlike "ModuleNotFoundError:*deliberately_missing_worker_smoke_module*"){throw}
}
Write-Output 'PASS missing-module failure includes the actual import error'
$signal = Join-Path $folder 'started.txt'
$cancel = New-Object Threading.CancellationTokenSource
try {
    $task = $run.Invoke($null, @([string]$PythonExecutable, [string]$script, [string]('"' + $signal + '"'), $null, $cancel.Token, $null, [string]$folder))
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not (Test-Path -LiteralPath $signal)) {
        if ($task.IsCompleted) { $task.GetAwaiter().GetResult(); throw 'Worker exited before creating its child.' }
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Worker did not start.' }
        Start-Sleep -Milliseconds 50
    }
    $ownedIds = (Get-Content -LiteralPath $signal -Raw).Split(',') | ForEach-Object { [int]$_ }
    if((Get-Content -LiteralPath ($signal+'.temp') -Raw) -ne (Join-Path $folder 'scratch')){throw 'Worker temporary files escaped the selected build directory'}
    $cancel.Cancel()
    try { [void]$task.Wait(5000) } catch { if (-not $task.IsCanceled) { throw } }
    if (-not $task.IsCanceled) { throw 'Worker did not report cancellation.' }
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $remaining = @($ownedIds | ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 50
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($remaining.Count) { throw 'Cancellation left an owned worker process running.' }
    Write-Output 'PASS preparation cancellation terminates parent and child processes'
} finally { $cancel.Cancel(); $cancel.Dispose() }
