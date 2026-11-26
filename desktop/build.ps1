# Build the Windows WebView2 portable client.
# Requirements: .NET Framework 4.x csc (Windows), WebView2 SDK NuGet.
# Usage: powershell -ExecutionPolicy Bypass -File desktop/build.ps1
param(
    [string]$SdkDir = "E:\toolchain\webview2",
    [string]$Version = "3.1.1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $root "webview2"
$outRoot = Join-Path $src "release"
$outDir = Join-Path $outRoot "Dreikanterbot-$Version-win-x64"
$nupkg = Join-Path $env:TEMP "microsoft.web.webview2.nupkg"

function Ensure-Sdk {
    if (Test-Path (Join-Path $SdkDir "lib\net462\Microsoft.Web.WebView2.Core.dll")) { return }
    Write-Host "Downloading WebView2 SDK..."
    New-Item -ItemType Directory -Force $SdkDir | Out-Null
    Invoke-WebRequest -Uri "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/1.0.2903.40" -OutFile $nupkg
    Copy-Item $nupkg (Join-Path $SdkDir "sdk.zip") -Force
    Expand-Archive (Join-Path $SdkDir "sdk.zip") -DestinationPath $SdkDir -Force
}

Ensure-Sdk
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "csc.exe not found: $csc" }

New-Item -ItemType Directory -Force $outDir | Out-Null
$exe = Join-Path $outDir "Dreikanterbot.exe"
& $csc /nologo /target:winexe /platform:x64 /optimize+ "/out:$exe" "/win32icon:$(Join-Path $src 'app.ico')" `
    "/r:$(Join-Path $SdkDir 'lib\net462\Microsoft.Web.WebView2.Core.dll')" `
    "/r:$(Join-Path $SdkDir 'lib\net462\Microsoft.Web.WebView2.WinForms.dll')" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.dll /r:System.Core.dll `
    (Join-Path $src "Program.cs")
if ($LASTEXITCODE -ne 0) { throw "csc failed with $LASTEXITCODE" }

Copy-Item (Join-Path $SdkDir "lib\net462\Microsoft.Web.WebView2.Core.dll") $outDir -Force
Copy-Item (Join-Path $SdkDir "lib\net462\Microsoft.Web.WebView2.WinForms.dll") $outDir -Force
Copy-Item (Join-Path $SdkDir "build\native\x64\WebView2Loader.dll") $outDir -Force
@(
    "Dreikanterbot $Version desktop client",
    "",
    "1. Double-click Dreikanterbot.exe.",
    "2. Enter your deployed server URL on first launch (for example https://chat.example.com).",
    "3. Sign in and use chat, memory and plugins.",
    "",
    "The desktop shell only renders the web workspace; model keys and conversations stay on your server.",
    "Use File -> Change server address if the URL is wrong.",
    "Requires Microsoft Edge WebView2 Runtime (usually included with Windows 10/11)."
) | Set-Content (Join-Path $outDir "README.txt") -Encoding UTF8

$zip = Join-Path $outRoot "Dreikanterbot-$Version-win-x64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $zip -CompressionLevel Optimal
Write-Host "EXE: $exe"
Write-Host "ZIP: $zip"
