param(
    # Python 런처가 없는 경우 -PythonCommand C:\Path\To\python.exe 사용
    [string]$PythonCommand = "py",
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "Windows 실행파일은 Windows에서 빌드해야 합니다. Windows PowerShell에서 실행하세요."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildVenv = Join-Path $ProjectRoot ".venv-build"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

Push-Location $ProjectRoot
try {
    if (Test-Path $BuildVenv) {
        if (-not (Test-Path (Join-Path $BuildVenv "pyvenv.cfg")) -or -not (Test-Path $BuildPython)) {
            throw ".venv-build 경로가 유효한 가상환경이 아닙니다. 기존 파일을 확인한 뒤 다른 곳으로 이동하고 다시 실행하세요."
        }
        Write-Host "기존 .venv-build 가상환경을 사용합니다."
    }
    else {
        if ($PythonCommand -eq "py") {
            & $PythonCommand "-$PythonVersion" -m venv $BuildVenv
        }
        else {
            & $PythonCommand -m venv $BuildVenv
        }
        if ($LASTEXITCODE -ne 0) { throw "빌드 가상환경 생성 실패" }
    }

    & $BuildPython -c "import struct, sys; assert sys.version_info >= (3, 10), 'Python 3.10 이상 필요'; assert struct.calcsize('P') == 8, '64비트 Python 필요'"
    if ($LASTEXITCODE -ne 0) { throw "Python 버전 또는 아키텍처 확인 실패" }

    & $BuildPython -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "의존성 설치 실패" }
    & $BuildPython -m pip install --editable .
    if ($LASTEXITCODE -ne 0) { throw "프로젝트 설치 실패" }

    $PreviousQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        & $BuildPython -m pytest
        if ($LASTEXITCODE -ne 0) { throw "자동 테스트 실패: 배포 빌드를 중단합니다." }
    }
    finally {
        if ($null -eq $PreviousQtPlatform) {
            Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        }
        else {
            $env:QT_QPA_PLATFORM = $PreviousQtPlatform
        }
    }

    & $BuildPython -m PyInstaller --clean --noconfirm pharma_cost.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드 실패" }

    $OutputExe = Join-Path $ProjectRoot "dist\PharmaCostSimulator\PharmaCostSimulator.exe"
    if (-not (Test-Path $OutputExe)) { throw "빌드 후 실행파일을 찾을 수 없습니다." }
    Write-Host "빌드 완료: $OutputExe"
    Write-Host "배포할 때 dist\PharmaCostSimulator 폴더 전체를 전달하세요."
}
finally {
    Pop-Location
}
