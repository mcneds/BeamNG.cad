$ErrorActionPreference = 'Stop'
$git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $git) { return }

$repo = Split-Path -Parent $PSScriptRoot
$targetBranch = & $git.Source -C $repo config --local --get beamngcad.pushOnBuildBranch 2>$null
if ($LASTEXITCODE -ne 0 -or -not $targetBranch) { return }

$branch = & $git.Source -C $repo branch --show-current
if ($LASTEXITCODE -ne 0) { throw 'Could not read the current Git branch.' }
if ($branch -cne $targetBranch) { return }

$changes = & $git.Source -C $repo status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0) { throw 'Could not check the Git working tree.' }
if ($changes) {
    Write-Output 'Build push skipped. Commit or set aside the working tree changes first.'
    return
}

$revision = & $git.Source -C $repo rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Could not read the current commit.' }
$knownRemote = & $git.Source -C $repo rev-parse --verify --quiet "refs/remotes/origin/$branch"
if ($LASTEXITCODE -eq 0 -and $knownRemote -eq $revision) { return }

$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'Never'
& $git.Source -C $repo push origin "${revision}:refs/heads/$branch"
if ($LASTEXITCODE -ne 0) { throw "Build push failed for $branch. Git reported the reason above." }
