$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$priorCache = $env:PYINSTALLER_CONFIG_DIR
$priorTmp = $env:TMP
$priorTemp = $env:TEMP
$priorTcl = $env:TCL_LIBRARY
$priorTk = $env:TK_LIBRARY
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'build\cache'
    $env:TMP = $env:TEMP = Join-Path $PSScriptRoot 'build\temp'
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
    $tclRoot = & .\.venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)"
    if ($LASTEXITCODE -ne 0) { throw 'Could not locate the Python Tcl/Tk libraries' }
    if (Test-Path -LiteralPath (Join-Path $tclRoot 'tcl\tcl8.6\init.tcl')) {
        $env:TCL_LIBRARY = '\\?\' + (Join-Path $tclRoot 'tcl\tcl8.6')
        $env:TK_LIBRARY = '\\?\' + (Join-Path $tclRoot 'tcl\tk8.6')
    }
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm OcuField.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller exited with code $LASTEXITCODE" }
}
finally {
    $env:PYINSTALLER_CONFIG_DIR = $priorCache
    $env:TMP = $priorTmp
    $env:TEMP = $priorTemp
    $env:TCL_LIBRARY = $priorTcl
    $env:TK_LIBRARY = $priorTk
    Pop-Location
}
