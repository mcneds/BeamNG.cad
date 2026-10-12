param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$Destination,
    [ValidateSet('All','Write','Read')][string]$Stage='All'
)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
$Destination=(Resolve-Path -LiteralPath $Destination).Path
if($Stage -eq 'All') {
    $case=Join-Path $Destination ('case-'+[Guid]::NewGuid().ToString('N'))
    foreach($phase in @('Write','Read')) {
        & powershell -NoProfile -File $PSCommandPath -OutputDirectory $OutputDirectory -Destination $case -Stage $phase
        if($LASTEXITCODE -ne 0){throw "Project selection failed: $phase"}
    }
    exit 0
}
$code=[Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
$projectType=$code.GetType('BeamNG.Cad.Preparation.VehicleProject',$true)
$componentType=$code.GetType('BeamNG.Cad.Preparation.ComponentDefinition',$true)
$settingsType=$code.GetType('BeamNG.Cad.UI.ExporterSettings',$true)
$settingsPath=Join-Path $Destination 'settings.xml'
$document=Join-Path $Destination 'base.SLDASM'
$companionDocument=Join-Path $Destination 'working.SLDASM'
$oldPath=$document+'.beamng-project.json'
$sourcePath=Join-Path $Destination 'saved-work-61.beamng-project.json'
$companionPath=$companionDocument+'.beamng-project.json'
function Preferences { return [Activator]::CreateInstance($settingsType,@([string]$settingsPath)) }
function LoadProject([string]$path) { return $projectType.GetMethod('Load').Invoke($null,@([string]$path)) }
function Check([bool]$value,[string]$message) { if(-not $value){throw $message}; Write-Output ('PASS '+$message) }
function CountIs($project,[int]$count,[string]$path) { return $project.Components.Count -eq $count -and $project.FilePath -eq $path }
function Reject($preferences,[string]$message) {
    try { [void]$preferences.ProjectForDocument($document); throw 'Unexpected fallback' }
    catch {
        $inner=$_.Exception
        while($inner.InnerException -and $inner.GetType().Name -ne 'SelectedProjectUnavailableException'){$inner=$inner.InnerException}
        Check ($inner.GetType().Name -eq 'SelectedProjectUnavailableException') $message
    }
}
if($Stage -eq 'Write') {
    [IO.File]::WriteAllText($document,'Placeholder - never opened in CAD')
    [IO.File]::WriteAllText($companionDocument,'Placeholder - never opened in CAD')
    $old=$projectType.GetMethod('Open').Invoke($null,@([string]$document))
    for($i=0;$i -lt 33;$i++) {
        $c=[Activator]::CreateInstance($componentType,$true);$c.Name='Synthetic '+$i;$old.Components.Add($c)
    }
    $old.Save();$source=$old.Fork($sourcePath)
    for($i=33;$i -lt 61;$i++) {
        $c=[Activator]::CreateInstance($componentType,$true);$c.Name='Extra panel '+$i;$source.Components.Add($c)
    }
    $source.Save();$companion=$source.Fork($companionPath);$companion.SourceDocument=$companionDocument;$companion.Save()
    $hashes=@{}
    foreach($path in @($oldPath,$sourcePath,$companionPath)){$hashes[$path]=(Get-FileHash -LiteralPath $path).Hash}
    $hashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Destination 'hashes.json') -Encoding UTF8
    $p=Preferences;$p.LastProjectPath=$sourcePath;$p.Save()
    Check (CountIs ($p.ProjectForDocument($document)) 61 $sourcePath) 'legacy external source project is migrated instead of the adjacent 33-group default'
    $stale=Preferences
    $p.SelectProject($companion);$p.Save()
    Check (CountIs ($p.ProjectForDocument($companionDocument)) 61 $companionPath) 'working assembly resolves its own 61-group project'
    Check (CountIs ((Preferences).ProjectForDocument($document)) 61 $sourcePath) 'returning to base retains all 61 groups after opening working copy'
    Check (CountIs ($stale.ProjectForDocument($document)) 61 $sourcePath) 'existing frame window resolves the current source selection'
    $switch=Preferences;$switch.SelectProject($old);$switch.Save()
    Check (CountIs ($stale.ProjectForDocument($document)) 33 $oldPath) 'explicitly choosing the old project remains supported and is seen by stale windows'
    $stale.FrameOutput='new-build-directory';$stale.LastProjectPath=$sourcePath;$stale.Save()
    Check (CountIs ((Preferences).ProjectForDocument($document)) 33 $oldPath) 'saving settings or a build from a stale window cannot switch the active source project'
    Check (CountIs ((Preferences).ProjectForDocument($companionDocument)) 61 $companionPath) 'stale settings saves preserve choices for other assemblies'
    $switch.SelectProject($source);$switch.Save()
    $fork=$source.Fork((Join-Path $Destination 'independent.json'))
    Check (CountIs ((Preferences).ProjectForDocument($document)) 61 $sourcePath) 'loading and forking projects alone does not change the active choice'
    $switch.SelectProject($fork);$switch.Save()
    Check ((Preferences).ProjectForDocument($document).Identity.Id -eq $fork.Identity.Id) 'explicitly selecting an independent mod copy persists its identity'
    $switch.SelectProject($source);$switch.Save()
    $caseVariant=$document.ToUpperInvariant().Replace('\','/')
    Check (CountIs ((Preferences).ProjectForDocument($caseVariant)) 61 $sourcePath) 'document path matching tolerates Windows casing and separator differences'

    $sourceBytes=[IO.File]::ReadAllBytes($sourcePath)
    [IO.File]::Delete($sourcePath)
    try { Reject (Preferences) 'missing saved project is rejected without falling back to the 33-group default' }
    finally { [IO.File]::WriteAllBytes($sourcePath,$sourceBytes) }
    try {
        [IO.File]::WriteAllBytes($sourcePath,[IO.File]::ReadAllBytes($companionPath))
        Reject (Preferences) 'remembered project belonging to another assembly is rejected'
    } finally { [IO.File]::WriteAllBytes($sourcePath,$sourceBytes) }
    try {
        [IO.File]::WriteAllText($sourcePath,'broken JSON')
        Reject (Preferences) 'corrupt remembered project is rejected without substituting older work'
    } finally { [IO.File]::WriteAllBytes($sourcePath,$sourceBytes) }
    $choiceBytes=[IO.File]::ReadAllBytes($settingsPath+'.projects.xml')
    try {
        [IO.File]::WriteAllText($settingsPath+'.projects.xml','<Unexpected/>')
        $failed=$false
        try { [void](Preferences).ProjectForDocument($document) } catch { $failed=$true }
        Check $failed 'corrupt selection registry fails visibly instead of overwriting the choice'
    } finally { [IO.File]::WriteAllBytes($settingsPath+'.projects.xml',$choiceBytes) }
    $p=Preferences;$p.SelectProject($companion);$p.Save()
    # Simulate an already-running older add-in rewriting its original settings.
    [IO.File]::WriteAllText($settingsPath,'<BeamNGCadSettings version="2"><LastProjectPath>'+[Security.SecurityElement]::Escape($oldPath)+'</LastProjectPath></BeamNGCadSettings>')
    Check (CountIs ((Preferences).ProjectForDocument($document)) 61 $sourcePath) 'legacy settings writes cannot erase per-assembly choices'
    $isolated=[Activator]::CreateInstance($settingsType,@([string](Join-Path $Destination 'isolated.xml')))
    Check (CountIs ($isolated.ProjectForDocument($document)) 33 $oldPath) 'independent settings files have independent project selections'
} else {
    $p=Preferences
    Check (CountIs ($p.ProjectForDocument($document)) 61 $sourcePath) 'source selection survives a separate process with an old global path'
    Check (CountIs ($p.ProjectForDocument($companionDocument)) 61 $companionPath) 'companion selection independently survives a separate process'
    $p.SelectProject((LoadProject $companionPath));$p.Save()
    Check (CountIs ($p.ProjectForDocument($document)) 61 $sourcePath) 'opening working assembly after restart keeps the base at 61 groups'
    $p.SelectProject((LoadProject $sourcePath));$p.Save()
    Check (CountIs ($p.ProjectForDocument($companionDocument)) 61 $companionPath) 'opening base after restart keeps the working assembly at 61 groups'
    $hashes=Get-Content -LiteralPath (Join-Path $Destination 'hashes.json') -Raw | ConvertFrom-Json
    foreach($item in $hashes.PSObject.Properties) {
        Check ((Get-FileHash -LiteralPath $item.Name).Hash -eq $item.Value) ('project content preserved: '+[IO.Path]::GetFileName($item.Name))
    }
}
