param(
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Debug',
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot "..\beamng.cad\bin\$Configuration\net472"
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

# Exercise command creation from a host whose app base is elsewhere.
# Do not preload resource dependencies: doing so hides native-host lookup failures.
if ([AppDomain]::CurrentDomain.GetAssemblies().GetName().Name -contains 'System.Resources.Extensions') {
    throw 'Run this check in a fresh Windows PowerShell process; resource reader is already loaded.'
}
$addInAssembly = [Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
if ($addInAssembly.GetReferencedAssemblies().Name -contains 'System.Resources.Extensions') {
    throw 'The add-in must not depend on a serialized bitmap resource reader.'
}

# Build the same command specification as OnConnect, without a SolidWorks session.
$xcad = [Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'Xarial.XCad.dll'))
$extension = $xcad.GetType('Xarial.XCad.UI.Commands.XCommandManagerExtension', $true)
foreach($group in @('Commands_e','FrameCommands','ModCommands')) {
    $commandType = $addInAssembly.GetType('BeamNG.Cad.MainSwAddIn+'+$group, $true)
    $create = $extension.GetMethod('CreateSpecFromEnum').MakeGenericMethod($commandType)
    $spec = $create.Invoke($null, @($null, $null, [Nullable[int]]1))
    foreach ($command in $spec.Commands) {
        if ($null -eq $command.Icon) { throw "Missing command icon: $($command.Title)" }
        if ($command.Title -match 'About') { throw 'About must stay inside Settings.' }
        Write-Output "PASS command specification: $($command.Title)"
    }
}
$icons = $addInAssembly.GetType('BeamNG.Cad.Properties.CommandIcons', $true)
$load = $icons.GetMethod('Load', [Reflection.BindingFlags]'NonPublic,Static')
foreach ($key in @('about-icon.png', 'box-icon.png', 'height-icon.png', 'length-icon.png', 'parametric-box-icon.png', 'width-icon.png')) {
    $bitmap = $load.Invoke($null, @($key))
    try {
        if ($null -eq $bitmap -or $bitmap.Width -le 0 -or $bitmap.Height -le 0) {
            throw "Invalid bitmap resource: $key"
        }
        Write-Output "PASS $key ($($bitmap.Width)x$($bitmap.Height))"
    }
    finally { if ($null -ne $bitmap) { $bitmap.Dispose() } }
}
