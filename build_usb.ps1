[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$UsbPath
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$UsbRoot = (Resolve-Path -LiteralPath $UsbPath).Path
$Destination = Join-Path $UsbRoot "MarkLIVPortable"

if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Build this USB bundle on 64-bit Intel/AMD Windows. Other operating systems and ARM64 need separate builds."
}

if (Test-Path -LiteralPath $Destination) {
    if (Get-ChildItem -LiteralPath $Destination -Force | Select-Object -First 1) {
        throw "Destination is not empty: $Destination. Choose an empty folder so existing USB files are not overwritten."
    }
} else {
    New-Item -ItemType Directory -Path $Destination | Out-Null
}

$PythonCommand = Get-Command python -ErrorAction Stop
$Python = $PythonCommand.Source
$PythonVersion = (& $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
$VersionParts = $PythonVersion.Split('.')
$Major = [int]$VersionParts[0]
$Minor = [int]$VersionParts[1]
if ($Major -ne 3 -or $Minor -lt 11 -or $Minor -gt 13) {
    throw "Build requires Python 3.11-3.13; found $PythonVersion."
}

$BuildRoot = Join-Path $env:TEMP ("MarkLIV-build-" + [guid]::NewGuid().ToString("N"))
$RuntimeDirectory = Join-Path $Destination "python"
$RuntimePython = Join-Path $RuntimeDirectory "python.exe"
$RuntimeZip = Join-Path $BuildRoot "python-embed.zip"
$GetPip = Join-Path $BuildRoot "get-pip.py"
$BrowserPath = Join-Path $Destination "playwright-browsers"
$env:PLAYWRIGHT_BROWSERS_PATH = $BrowserPath

try {
    New-Item -ItemType Directory -Path $BuildRoot, $RuntimeDirectory, $BrowserPath -Force | Out-Null

    & robocopy $ProjectRoot $Destination /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 `
        /XD (Join-Path $ProjectRoot ".git") (Join-Path $ProjectRoot ".vscode") `
            (Join-Path $ProjectRoot "__pycache__") (Join-Path $ProjectRoot "plugins") `
            (Join-Path $ProjectRoot "uploads") (Join-Path $ProjectRoot "config\certs") `
        /XF "api_keys.json" "long_term.json" /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "Could not copy the application to the USB destination." }

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Invoke-WebRequest -Uri $EmbedUrl -OutFile $RuntimeZip
    Expand-Archive -LiteralPath $RuntimeZip -DestinationPath $RuntimeDirectory -Force

    $PthName = "python$Major$Minor._pth"
    $PthFile = Join-Path $RuntimeDirectory $PthName
    if (-not (Test-Path -LiteralPath $PthFile)) {
        throw "The downloaded embedded Python archive did not contain $PthName."
    }
    $PthText = "python$Major$Minor.zip`r`n.`r`n..`r`nLib\site-packages`r`nimport site`r`n"
    [System.IO.File]::WriteAllText($PthFile, $PthText, [System.Text.Encoding]::ASCII)
    New-Item -ItemType Directory -Path (Join-Path $RuntimeDirectory "Lib\site-packages") -Force | Out-Null

    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
    & $RuntimePython $GetPip --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "Could not bootstrap pip into the USB Python runtime." }

    & $RuntimePython -m pip install --disable-pip-version-check -r (Join-Path $Destination "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check the build PC's internet connection and requirements.txt." }

    & $RuntimePython -m playwright install chromium firefox
    if ($LASTEXITCODE -ne 0) { throw "Playwright browser installation failed." }

    $ConfigDir = Join-Path $Destination "config"
    $MemoryDir = Join-Path $Destination "memory"
    New-Item -ItemType Directory -Path $ConfigDir, $MemoryDir -Force | Out-Null

    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $ApiConfig = Join-Path $ConfigDir "api_keys.json"
    if (-not (Test-Path -LiteralPath $ApiConfig)) {
        [System.IO.File]::WriteAllText($ApiConfig, "{}", $Utf8NoBom)
    }
    $MemoryFile = Join-Path $MemoryDir "long_term.json"
    if (-not (Test-Path -LiteralPath $MemoryFile)) {
        [System.IO.File]::WriteAllText(
            $MemoryFile,
            '{"identity":{},"preferences":{},"projects":{},"relationships":{},"wishes":{},"notes":{}}',
            $Utf8NoBom
        )
    }

    Write-Host "Portable bundle created: $Destination"
    Write-Host "Run Run-Jarvis.bat from the USB drive. Enter API keys on that USB copy."
    Write-Host "This bundle targets 64-bit Intel/AMD Windows. Windows requires a manual launch from USB."
}
finally {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
}