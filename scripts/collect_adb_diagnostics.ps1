Param(
    [string]$Serial = "",
    [string]$AdbPath = "",
    [string]$PackageName = "com.silverhorse.speakerclock"
)

function Resolve-AdbPath {
    if ($AdbPath -and (Test-Path $AdbPath)) {
        return $AdbPath
    }
    $pathAdb = Get-Command adb -ErrorAction SilentlyContinue
    if ($pathAdb) {
        return $pathAdb.Source
    }
    $localAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    if (Test-Path $localAdb) {
        return $localAdb
    }
    throw "adb not found. Pass -AdbPath or install Android Platform Tools."
}

function Build-Args {
    param([string[]]$Parts)
    $all = New-Object System.Collections.Generic.List[string]
    if ($Serial -and $Serial.Trim().Length -gt 0) {
        $all.Add("-s")
        $all.Add($Serial.Trim())
    }
    foreach ($part in $Parts) {
        $all.Add($part)
    }
    return $all.ToArray()
}

function Run-ADB {
    param(
        [string[]]$Args,
        [string]$OutFile
    )
    $errFile = "$OutFile.err"
    try {
        & $script:adbCmd @Args 1> $OutFile 2> $errFile
        "exit_code=$LASTEXITCODE" | Out-File -Append -FilePath $OutFile -Encoding utf8
    } catch {
        "ERROR running: $script:adbCmd $($Args -join ' ')" | Out-File -FilePath $OutFile -Encoding utf8
        "Exception: $($_.Exception.Message)" | Out-File -FilePath $errFile -Encoding utf8
    }
}

try {
    $script:adbCmd = Resolve-AdbPath
} catch {
    Write-Error $_.Exception.Message
    exit 2
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = "playpulse_adb_diag_$ts"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

"adb=$script:adbCmd" | Out-File -FilePath (Join-Path $outDir "diagnostics_meta.txt") -Encoding utf8
"serial=$Serial" | Out-File -Append -FilePath (Join-Path $outDir "diagnostics_meta.txt") -Encoding utf8
"package=$PackageName" | Out-File -Append -FilePath (Join-Path $outDir "diagnostics_meta.txt") -Encoding utf8

Run-ADB -Args (Build-Args @("devices","-l")) -OutFile (Join-Path $outDir "devices.txt")
Run-ADB -Args (Build-Args @("shell","getprop","ro.build.version.sdk")) -OutFile (Join-Path $outDir "android_sdk.txt")
Run-ADB -Args (Build-Args @("shell","pm","list","packages")) -OutFile (Join-Path $outDir "packages.txt")

$remoteDownload = "/sdcard/Download/PlayPulseScreenshots/$PackageName"
$remoteAppSpecificLower = "/sdcard/Android/data/$PackageName/files/playpulse_screenshots"
$remoteAppSpecificLegacy = "/sdcard/Android/data/$PackageName/files/PlayPulseScreenshots"

Run-ADB -Args (Build-Args @("shell","ls","-la",$remoteDownload)) -OutFile (Join-Path $outDir "remote_path_download.txt")
Run-ADB -Args (Build-Args @("shell","ls","-la",$remoteAppSpecificLower)) -OutFile (Join-Path $outDir "remote_path_android_data_lower.txt")
Run-ADB -Args (Build-Args @("shell","ls","-la",$remoteAppSpecificLegacy)) -OutFile (Join-Path $outDir "remote_path_android_data_legacy.txt")

Run-ADB -Args (Build-Args @("shell","sh","-c","find /sdcard -type d \( -name 'PlayPulseScreenshots' -o -name 'playpulse_screenshots' \) 2>/dev/null")) -OutFile (Join-Path $outDir "found_dirs.txt")
Run-ADB -Args (Build-Args @("shell","sh","-c","find /sdcard -type f -name '*.png' 2>/dev/null | sed -n '1,200p'")) -OutFile (Join-Path $outDir "png_samples.txt")
Run-ADB -Args (Build-Args @("shell","run-as",$PackageName,"ls","-la","files")) -OutFile (Join-Path $outDir "run_as_files.txt")
Run-ADB -Args (Build-Args @("logcat","-d")) -OutFile (Join-Path $outDir "logcat_full.txt")

$logcatFiltered = Join-Path $outDir "logcat_playpulse.txt"
try {
    Get-Content (Join-Path $outDir "logcat_full.txt") | Select-String -Pattern "PlayPulse|PlayPulseScreenshot|PlayPulseLocaleHelper|PlayPulseScreenshotHelper|PlayPulseScreenshotTest|PlayPulseLocaleBridge" | Out-File $logcatFiltered -Encoding utf8
} catch {
    "failed to filter logcat" | Out-File $logcatFiltered -Encoding utf8
}

$pulledDir = Join-Path $outDir "pulled"
New-Item -ItemType Directory -Path $pulledDir -Force | Out-Null

function Try-PullRemote {
    param([string]$Remote, [string]$LocalSub)
    $localPath = Join-Path $pulledDir $LocalSub
    New-Item -ItemType Directory -Path $localPath -Force | Out-Null
    Run-ADB -Args (Build-Args @("pull", $Remote, $localPath)) -OutFile (Join-Path $outDir "pull_$LocalSub.txt")
}

Try-PullRemote -Remote $remoteDownload -LocalSub "download_path"
Try-PullRemote -Remote $remoteAppSpecificLower -LocalSub "android_data_lower"
Try-PullRemote -Remote $remoteAppSpecificLegacy -LocalSub "android_data_legacy"

$zipPath = "$outDir.zip"
try {
    Compress-Archive -Path $outDir -DestinationPath $zipPath -Force
    Write-Host "Diagnostics collected: $zipPath"
} catch {
    Write-Host "Collected files at: $outDir (failed to zip: $($_.Exception.Message))"
}
