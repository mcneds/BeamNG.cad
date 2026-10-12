param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\beamng.cad\bin\Debug\net472'))
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitProcess) { throw 'Run this script in 64-bit Windows PowerShell.' }
$guid = '{CC0A1EB8-E2C8-435C-BFFE-A3A0DCBC4A60}'
if (-not (Test-Path "HKLM:\SOFTWARE\SolidWorks\Addins\$guid")) {
    throw 'First installation requires an administrator build to create the SolidWorks add-in entry.'
}
$dll = (Resolve-Path -LiteralPath (Join-Path $OutputDirectory 'beamng.cad.dll')).Path
$registration = Join-Path (Split-Path $dll) ('registration-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($registration)
foreach ($key in @("CLSID\$guid", 'BeamNG.Cad.MainSwAddIn')) {
    if (Test-Path "Registry::HKEY_CURRENT_USER\Software\Classes\$key") {
        $backup = Join-Path $registration (($key -replace '[\\{}]', '_') + '.backup.reg')
        & reg.exe export "HKCU\Software\Classes\$key" $backup /y
        if ($LASTEXITCODE -ne 0) { throw 'Could not back up existing per-user registration.' }
    }
}
$generated = Join-Path $registration 'generated.reg'
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe" $dll /codebase "/regfile:$generated"
if ($LASTEXITCODE -ne 0) { throw 'Could not generate COM registration.' }
$currentUser = Join-Path $registration 'current-user.reg'
(Get-Content -LiteralPath $generated -Raw).Replace('HKEY_CLASSES_ROOT\', 'HKEY_CURRENT_USER\Software\Classes\') |
    Set-Content -LiteralPath $currentUser -Encoding Unicode
& reg.exe import $currentUser /reg:64
if ($LASTEXITCODE -ne 0) { throw 'Could not register the add-in for this user.' }
$actual = (Get-ItemProperty "Registry::HKEY_CLASSES_ROOT\CLSID\$guid\InprocServer32").CodeBase
if (([Uri]$actual).LocalPath -ne $dll) { throw "Unexpected effective COM path: $actual" }
Write-Output "Registered existing beamng.cad add-in for this user: $actual"
Write-Output "Registration files and prior per-user backups: $registration"
