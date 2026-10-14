param(
    [ValidateSet('m10','workbench')][string]$Mode = 'm10',
    [switch]$CheckOnly,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$ProgramArgs
)
# Local discovery only: no installation and no system PATH changes.
$projectPath = Split-Path $PSScriptRoot -Parent
$candidates = [System.Collections.Generic.List[string]]::new()
if ($env:POSE_PYTHON) { $candidates.Add($env:POSE_PYTHON) }
$candidates.Add((Join-Path $projectPath '.venv\Scripts\python.exe'))
$candidates.Add((Join-Path $projectPath 'venv\Scripts\python.exe'))
foreach ($name in @('python','python3','py')) {
    $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command -and $command.Source -notlike '*\WindowsApps\*') { $candidates.Add($command.Source) }
}
foreach ($registry in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore')) {
    foreach ($version in (Get-ChildItem -LiteralPath $registry -ErrorAction SilentlyContinue | Sort-Object PSChildName -Descending)) {
        $install = Get-Item -LiteralPath ($version.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
        if ($install) { $candidates.Add((Join-Path $install.GetValue('') 'python.exe')) }
    }
}
foreach ($base in @((Join-Path $env:USERPROFILE 'AppData\Local\Programs\Python'), $env:ProgramFiles)) {
    if ($base) {
        foreach ($folder in (Get-ChildItem -LiteralPath $base -Directory -Filter 'Python*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
            $candidates.Add((Join-Path $folder.FullName 'python.exe'))
        }
    }
}
$candidates.Add((Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$probe = "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'; from PIL import Image; print(sys.executable)"
if ($Mode -in @('m10','workbench')) { $probe += "; import tkinter as tk; r=tk.Tk(); r.withdraw(); r.update(); r.destroy()" }
$attempts = [System.Collections.Generic.List[string]]::new()
$selectedPython = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $output = & $candidate -X utf8 -B -c $probe 2>&1
        if ($LASTEXITCODE -eq 0) { $selectedPython = [string]($output | Select-Object -First 1); break }
        $attempts.Add("$candidate`n$($output -join "`n")")
    } catch { $attempts.Add("$candidate`n$($_.Exception.Message)") }
}
$logPath = Join-Path $projectPath 'logs'
New-Item -ItemType Directory -Force -Path $logPath | Out-Null
$startupLog = Join-Path $logPath "$Mode-startup.log"
if (-not $selectedPython) {
    @('No usable Python 3.10+ with Pillow was found.', 'M10 also requires working Tk.', $attempts) | Set-Content -LiteralPath $startupLog -Encoding UTF8
    Write-Host "[ERROR] No usable runtime. Details: $startupLog"
    Write-Host 'Set POSE_PYTHON to an existing python.exe, or install Python with Tcl/Tk and Pillow.'
    exit 1
}
"Python: $selectedPython" | Set-Content -LiteralPath $startupLog -Encoding UTF8
Write-Host "Python: $selectedPython"
if ($CheckOnly) { exit 0 }
$entry = if ($Mode -eq 'm10') { 'm10\control_center.py' } else { 'm11\pose_workbench.py' }
Push-Location $projectPath
try {
    & $selectedPython -X utf8 -B (Join-Path $PSScriptRoot $entry) @ProgramArgs
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
if ($resultCode -ne 0) { Write-Host "[ERROR] $Mode exited with code $resultCode. See messages above." }
exit $resultCode
