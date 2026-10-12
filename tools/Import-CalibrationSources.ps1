param([string]$SourceRoot = 'H:\beamng project programs\BeamNG.cad')
$ErrorActionPreference = 'Stop'
$destination = Join-Path $PSScriptRoot '..\dependencies\cad-calibration'
if (Test-Path -LiteralPath $destination) { throw 'Dependency snapshot already exists; review updates explicitly.' }
$files = @()
foreach ($package in @('Test Harness','Vehicle Wizard')) {
    $source = Join-Path $SourceRoot $package
    foreach ($folder in @('tests', $(if ($package -eq 'Test Harness') {'frame_harness'} else {'vehicle_wizard'}), 'examples')) {
        $path = Join-Path $source $folder
        if (Test-Path -LiteralPath $path) {
            $files += Get-ChildItem -LiteralPath $path -Recurse -File | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' }
        }
    }
    $files += Get-ChildItem -LiteralPath $source -File | Where-Object { $_.Extension -in '.md','.toml' }
}
$archive = Join-Path $SourceRoot 'Test Harness\comparisons\4130-complete-20261004'
$files += Get-Item -LiteralPath (Join-Path $SourceRoot 'Vehicle Wizard\runtime\verification.json')
$files += Get-ChildItem -LiteralPath $archive -File | Where-Object { $_.Extension -in '.json','.html','.png','.csv' }
foreach ($case in @('4130-annealed','4130-normalized')) {
    foreach ($name in @('calibration.json','mochi.jbeam','report.json')) { $files += Get-Item -LiteralPath (Join-Path $archive "$case\$name") }
}
$records = @()
foreach ($file in $files) {
    $relative = $file.FullName.Substring($SourceRoot.TrimEnd('\').Length + 1)
    $target = Join-Path $destination $relative
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    Copy-Item -LiteralPath $file.FullName -Destination $target
    $records += @{path=$relative.Replace('\','/'); source=$file.FullName; sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$spec = Get-Content -LiteralPath (Join-Path $archive '4130-annealed\calibration.json') -Raw | ConvertFrom-Json
foreach ($property in $spec.source_hashes.PSObject.Properties) {
    $source = Join-Path (Join-Path (Split-Path $SourceRoot) 'Test Programs') $property.Name
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) { throw "Archived input changed: $source" }
    $target = Join-Path $destination (Join-Path 'Test Programs' $property.Name)
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    Copy-Item -LiteralPath $source -Destination $target
    $records += @{path=('Test Programs/'+$property.Name); source=$source; sha256=$property.Value}
}
@{version=1; source_root=$SourceRoot; files=$records} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $destination 'upstream-snapshot.json') -Encoding UTF8
Write-Output "Imported $($records.Count) source and reference files into $destination"
