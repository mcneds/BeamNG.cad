param([string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonExecutable) {
    $localPython = Join-Path $env:LOCALAPPDATA 'Python'
    if (Test-Path -LiteralPath $localPython) {
        $PythonExecutable = Get-ChildItem -LiteralPath $localPython -Directory |
            Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'python.exe' } |
            Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
}
if (-not $PythonExecutable -or -not (Test-Path -LiteralPath $PythonExecutable)) {
    throw 'Pass -PythonExecutable with the full path to Python 3.10 or newer.'
}
Push-Location $root
$previousPythonPath=$env:PYTHONPATH
$env:PYTHONPATH=(Join-Path $root 'dependencies\cad-calibration\Test Harness')+';'+(Join-Path $root 'dependencies\cad-calibration\Vehicle Wizard')+$(if($previousPythonPath){';'+$previousPythonPath})
try {
    & dotnet build beamng.cad.slnx -c Debug -p:XCadRegDll=false -p:OutputPath=bin/gui-check/
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    & powershell -NoProfile -File tools/Test-CompanionProvenance.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check')
    if ($LASTEXITCODE -ne 0) { throw 'Companion replacement provenance failed.' }
    & powershell -NoProfile -File tools/Test-AppearanceAsset.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check') -Destination (Join-Path $root ('beamng.cad\bin\gui-check\appearance-assets-' + [Guid]::NewGuid().ToString('N')))
    if ($LASTEXITCODE -ne 0) { throw 'Native appearance asset sharing failed.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-ReferenceSkeleton.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check') -Destination (Join-Path $root 'beamng.cad\bin\gui-check\reference-screenshots')
    if ($LASTEXITCODE -ne 0) { throw 'Reference skeleton controls failed.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-JointWorkspace.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check') -Destination (Join-Path $root 'beamng.cad\bin\gui-check\joint-workspace')
    if ($LASTEXITCODE -ne 0) { throw 'Joint workspace migration or controls failed.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-AssignmentInspection.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check') -Destination (Join-Path $root 'beamng.cad\bin\gui-check\assignment-inspection')
    if ($LASTEXITCODE -ne 0) { throw 'Saved assignment inspection failed.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-AssignmentState.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check') -Destination (Join-Path $root 'beamng.cad\bin\gui-check\assignment-state')
    if ($LASTEXITCODE -ne 0) { throw 'Saved assignments/fresh project failed.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-TemplateImportPanel.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check')
    if ($LASTEXITCODE -ne 0) { throw 'Template import state controls failed.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-TemplateImportLayout.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check') -Destination (Join-Path $root 'beamng.cad\bin\gui-check\import-layout')
    if ($LASTEXITCODE -ne 0) { throw 'Template import/reset buttons are clipped.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-HullControls.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check')
    if ($LASTEXITCODE -ne 0) { throw 'Hull controls and saved options failed.' }
    & powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-ModManager.ps1 -OutputDirectory (Join-Path $root 'beamng.cad\bin\gui-check') -PythonExecutable $PythonExecutable
    if ($LASTEXITCODE -ne 0) { throw 'Mod management failed.' }
    foreach ($suite in @('tests','dependencies/cad-calibration/Test Harness/tests','dependencies/cad-calibration/Vehicle Wizard/tests')) {
        & $PythonExecutable tools/run-python-tests.py $suite
        if ($LASTEXITCODE -ne 0) { throw "Python tests failed: $suite" }
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Settings.ps1
    if ($LASTEXITCODE -ne 0) { throw 'Settings persistence failed.' }
    & powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Worker.ps1 -PythonExecutable $PythonExecutable
    if ($LASTEXITCODE -ne 0) { throw 'Preparation worker cancellation failed.' }
    Write-Output 'PASS compile, Python, settings persistence and preparation worker checks.'
}
finally { $env:PYTHONPATH=$previousPythonPath; Pop-Location }
