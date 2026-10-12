param([string]$OutputDirectory, [ValidateSet('All','Write','Read')][string]$Stage = 'All', [string]$SettingsPath)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '..\beamng.cad\bin\gui-check' }
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($Stage -eq 'All') {
    $folder = Join-Path $OutputDirectory ('settings-smoke-' + [Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($folder)
    $SettingsPath = Join-Path $folder 'settings.xml'
    foreach ($part in @('Write','Read')) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Stage $part -SettingsPath $SettingsPath -OutputDirectory $OutputDirectory
        if ($LASTEXITCODE -ne 0) { throw "Settings check failed: $part" }
    }
    exit 0
}
$assembly = [Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
$type = $assembly.GetType('BeamNG.Cad.UI.ExporterSettings', $true)
if ($Stage -eq 'Write') {
    '<TrueMeshExporterSettings version="1"><FrameSource>legacy materials</FrameSource><FrameOutput>C:\old-output</FrameOutput></TrueMeshExporterSettings>' |
        Set-Content -LiteralPath $SettingsPath -Encoding UTF8
}
$settings = [Activator]::CreateInstance($type, @([string]$SettingsPath))
if ($Stage -eq 'Write') {
    if ($settings.FrameSource -ne 'legacy materials') { throw 'Legacy settings did not load.' }
    if ($settings.VerificationMode -ne 'quick') { throw 'New verification settings must default to Quick.' }
    $settings.VerificationMode = 'full'
    $settings.FrameOutput = 'C:\new-output'
    $settings.BlenderExecutable = 'C:\custom-blender.exe'
    $settings.Save()
    if ((Get-Content -LiteralPath ($SettingsPath + '.bak') -Raw) -notmatch 'TrueMeshExporterSettings') {
        throw 'Legacy settings were not preserved in the backup.'
    }
    Write-Output 'PASS legacy settings load and save preserves the previous file'
} else {
    if ($settings.FrameSource -ne 'legacy materials' -or $settings.FrameOutput -ne 'C:\new-output' -or $settings.BlenderExecutable -ne 'C:\custom-blender.exe' -or $settings.VerificationMode -ne 'full') {
        throw 'Settings failed to survive a separate process without a build.'
    }
    Write-Output 'PASS settings and explicit overrides survive a separate process without building'
}
