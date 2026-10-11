<#
.SYNOPSIS
    Builds LegalContractACG.dotm from the VBA sources and (optionally) installs
    it into Word's STARTUP folder so the "Legal Contract ACG" ribbon tab loads
    every time Word starts.

.DESCRIPTION
    Steps:
      1. Starts Word (COM), creates a blank document, imports every src\*.bas
         and src\*.cls module into its VBA project, saves it as a macro-enabled
         template (.dotm) in installer\out\.
      2. Injects ribbon\customUI14.xml into the .dotm package and registers it
         in _rels\.rels (this is what makes the ribbon tab appear).
      3. With -Install: copies the .dotm into %APPDATA%\Microsoft\Word\STARTUP
         and the Formats folder next to it under STARTUP\LegalContractACG\Formats.

    Requirements (one time, for the BUILD step only):
      Word > File > Options > Trust Center > Trust Center Settings >
      Macro Settings > tick "Trust access to the VBA project object model".
      You can untick it again after building.

.PARAMETER Install
    Copy the built template and formats into Word's STARTUP folder.

.PARAMETER NoBuild
    Skip building; just install installer\out\LegalContractACG.dotm.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Build-AddIn.ps1 -Install
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot          # ...\LegalContractACG
$srcDir  = Join-Path $root 'src'
$ribbon  = Join-Path $root 'ribbon\customUI14.xml'
$formats = Join-Path $root 'Formats'
$outDir  = Join-Path $PSScriptRoot 'out'
$outFile = Join-Path $outDir 'LegalContractACG.dotm'
$wdFormatXMLTemplateMacroEnabled = 15

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Assert-WordClosed {
    $procs = Get-Process -Name WINWORD -ErrorAction SilentlyContinue
    if ($procs) {
        throw "Word is running. Close every Word window (check the system tray too) and run this script again."
    }
}

function Build-Template {
    Write-Step "Building $outFile"
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    if (Test-Path $outFile) { Remove-Item $outFile -Force }

    $word = $null
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0
        $doc = $word.Documents.Add()

        try {
            $vbp = $doc.VBProject
            $null = $vbp.Name
        } catch {
            throw "Cannot access the VBA project. Enable 'Trust access to the VBA project object model' " +
                  "(File > Options > Trust Center > Trust Center Settings > Macro Settings) and retry."
        }
        $vbp.Name = 'LegalContractACG'

        $modules = Get-ChildItem -Path $srcDir -Include *.bas, *.cls -Recurse | Sort-Object Name
        if (-not $modules) { throw "No VBA sources found in $srcDir" }
        foreach ($m in $modules) {
            Write-Host "    import $($m.Name)"
            $null = $vbp.VBComponents.Import($m.FullName)
        }

        $doc.SaveAs2($outFile, $wdFormatXMLTemplateMacroEnabled)
        $doc.Close($false)
    }
    finally {
        if ($word) { $word.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word) }
    }

    Inject-Ribbon -Package $outFile -RibbonXml $ribbon
    Write-Host "    built OK" -ForegroundColor Green
}

function Inject-Ribbon {
    param([string]$Package, [string]$RibbonXml)
    Write-Step "Injecting ribbon XML"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::Open($Package, [System.IO.Compression.ZipArchiveMode]::Update)
    try {
        # 1. customUI/customUI14.xml
        $existing = $zip.GetEntry('customUI/customUI14.xml')
        if ($existing) { $existing.Delete() }
        $entry = $zip.CreateEntry('customUI/customUI14.xml')
        $w = New-Object System.IO.StreamWriter($entry.Open(), (New-Object System.Text.UTF8Encoding($false)))
        $w.Write((Get-Content -Raw -Path $RibbonXml))
        $w.Dispose()

        # 2. _rels/.rels relationship
        $relsEntry = $zip.GetEntry('_rels/.rels')
        $r = New-Object System.IO.StreamReader($relsEntry.Open())
        $rels = $r.ReadToEnd(); $r.Dispose()
        if ($rels -notmatch 'customUI14\.xml') {
            $relNode = '<Relationship Id="rIdCustomUI14" Type="http://schemas.microsoft.com/office/2007/relationships/ui/extensibility" Target="customUI/customUI14.xml"/>'
            $rels = $rels -replace '</Relationships>', "$relNode</Relationships>"
            $relsEntry.Delete()
            $relsEntry = $zip.CreateEntry('_rels/.rels')
            $w = New-Object System.IO.StreamWriter($relsEntry.Open(), (New-Object System.Text.UTF8Encoding($false)))
            $w.Write($rels); $w.Dispose()
        }
    }
    finally { $zip.Dispose() }
}

function Install-Template {
    Assert-WordClosed
    $startup = Join-Path $env:APPDATA 'Microsoft\Word\STARTUP'
    Write-Step "Installing into $startup"
    New-Item -ItemType Directory -Force -Path $startup | Out-Null
    Copy-Item -Path $outFile -Destination (Join-Path $startup 'LegalContractACG.dotm') -Force

    $fmtDest = Join-Path $startup 'LegalContractACG\Formats'
    New-Item -ItemType Directory -Force -Path $fmtDest | Out-Null
    Copy-Item -Path (Join-Path $formats '*.ini') -Destination $fmtDest -Force

    # per-user folder for formats added later (never overwritten by re-install)
    $userFmt = Join-Path $env:APPDATA 'LegalContractACG\Formats'
    if (-not (Test-Path $userFmt)) { New-Item -ItemType Directory -Force -Path $userFmt | Out-Null }

    Write-Host "    installed:" -ForegroundColor Green
    Write-Host "      $startup\LegalContractACG.dotm"
    Write-Host "      $fmtDest\*.ini"
    Write-Host "      your own formats go in: $userFmt"
    Write-Host ""
    Write-Host "Start Word. The 'Legal Contract ACG' tab appears after Home." -ForegroundColor Green
    Write-Host "If macros are blocked, add the STARTUP folder as a Trusted Location (see README)." -ForegroundColor Yellow
}

if (-not $NoBuild) { Assert-WordClosed; Build-Template }
if ($Install) { Install-Template }
if (-not $Install -and -not $NoBuild) {
    Write-Host ""
    Write-Host "Built only. Re-run with -Install to copy into Word's STARTUP folder, or copy by hand:" -ForegroundColor Yellow
    Write-Host "  $outFile  ->  $env:APPDATA\Microsoft\Word\STARTUP\"
    Write-Host "  $formats\*.ini  ->  $env:APPDATA\Microsoft\Word\STARTUP\LegalContractACG\Formats\"
}
