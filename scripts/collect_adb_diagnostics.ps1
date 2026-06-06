Param(
    [string]$Serial = "",
    [string]$AdbPath = ""
)

function Run-ADB {
    param(
        [string[]]$Args,
        [string]$OutFile
    )
    $errFile = "$OutFile.err"
    try {
        Start-Process -FilePath $adbCmd -ArgumentList $Args -NoNewWindow -Wait -RedirectStandardOutput $OutFile -RedirectStandardError $errFile
    } catch {
        "ERROR running: adb $($Args -join ' ')" | Out-File -FilePath $OutFile -Encoding utf8
        "Exception: $($_.Exception.Message)" | Out-File -FilePath $errFile -Encoding utf8
    }
}

# determine adb command: use provided path or system adb
if ($AdbPath -and (Test-Path $AdbPath)) {
    $adbCmd = $AdbPath
} elseif (Get-Command adb -ErrorAction SilentlyContinue) {
    $adbCmd = (Get-Command adb).Source
} else {
    Write-Error "adb not found in PATH and no -AdbPath provided. Install Android Platform Tools or pass -AdbPath '<full path to adb.exe>'"
    exit 2
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = "playpulse_adb_diag_$ts"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

# common helper to build args with optional -s
function Build-Args([string[]]$parts) {
    if ($Serial -and $Serial.Trim().Length -gt 0) {
        return ,"-s",$Serial + $parts
    }
    return $parts
}

# Collect basic info
Run-ADB -Args (Build-Args @("devices","-l")) -OutFile (Join-Path $outDir "devices.txt")
Run-ADB -Args (Build-Args @("shell","pm","list","packages")) -OutFile (Join-Path $outDir "packages.txt")

# Check the two expected remote paths
$remote1 = "/sdcard/Download/PlayPulseScreenshots/com.silverhorse.speakerclock"
$remote2 = "/sdcard/Android/data/com.silverhorse.speakerclock/files/PlayPulseScreenshots"
Run-ADB -Args (Build-Args @("shell","ls","-la",$remote1)) -OutFile (Join-Path $outDir "remote_path_download.txt")
Run-ADB -Args (Build-Args @("shell","ls","-la",$remote2)) -OutFile (Join-Path $outDir "remote_path_android_data.txt")

# Try finding PlayPulseScreenshots directories under /sdcard (may take time)
Run-ADB -Args (Build-Args @("shell","sh","-c","find /sdcard -maxdepth 4 -type d -name PlayPulseScreenshots 2>/dev/null")) -OutFile (Join-Path $outDir "found_dirs.txt")

# Find PNG files (may be large) - limit depth for speed
Run-ADB -Args (Build-Args @("shell","sh","-c","find /sdcard -type f -name ""*.png"" 2>/dev/null | sed -n '1,200p'")) -OutFile (Join-Path $outDir "png_samples.txt")

# Attempt run-as listing (may fail if app not debuggable)
Run-ADB -Args (Build-Args @("shell","run-as","com.silverhorse.speakerclock","ls","-la","files")) -OutFile (Join-Path $outDir "run_as_files.txt")

# Logcat dump and filtered PlayPulse entries
Run-ADB -Args (Build-Args @("logcat","-d")) -OutFile (Join-Path $outDir "logcat_full.txt")
# Simple filter for PlayPulse tags in logcat (findstr on Windows)
$logcatFiltered = Join-Path $outDir "logcat_playpulse.txt"
try {
    Get-Content (Join-Path $outDir "logcat_full.txt") | Select-String -Pattern "PlayPulse|PlayPulseScreenshot|PlayPulseLocaleHelper|PlayPulseScreenshotHelper|PlayPulseScreenshotTest" -SimpleMatch | Out-File $logcatFiltered -Encoding utf8
} catch {
    "(failed to filter logcat)" | Out-File $logcatFiltered
}

# Attempt to pull the two expected remote folders (results will be saved under pulled/)
$pulledDir = Join-Path $outDir "pulled"
New-Item -ItemType Directory -Path $pulledDir -Force | Out-Null

function Try-PullRemote([string]$remote, [string]$localSub) {
    $localPath = Join-Path $pulledDir $localSub
    New-Item -ItemType Directory -Path $localPath -Force | Out-Null
    $args = Build-Args @("pull", $remote, $localPath)
    $outFile = Join-Path $outDir ("pull_" + ($localSub -replace '[^a-zA-Z0-9_-]','_') + ".txt")
    Run-ADB -Args $args -OutFile $outFile
}

Try-PullRemote -remote $remote1 -localSub "download_path"
Try-PullRemote -remote $remote2 -localSub "android_data_path"

# Compress results
$zipPath = "$outDir.zip"
try {
    Compress-Archive -Path $outDir -DestinationPath $zipPath -Force
    Write-Host "Diagnostics collected: $zipPath"
} catch {
    Write-Host "Collected files at: $outDir (failed to zip: $($_.Exception.Message))"
}

Write-Host "Done. Upload the zip or paste key files: devices.txt, found_dirs.txt, png_samples.txt, logcat_playpulse.txt, remote_path_download.txt, remote_path_android_data.txt"