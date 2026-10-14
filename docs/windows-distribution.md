# Windows 배포 안내

최초 배포는 PyInstaller의 **한 폴더 방식(onedir)** 입니다. `.exe`와 `_internal` 등 의존 파일을 하나의 폴더로 전달합니다. 사용 PC에는 Python 설치, 로그인, 외부 서버와 인터넷 연결이 필요하지 않습니다.

## 빌드 PC 준비

- Windows 10/11 64비트 빌드 PC
- Python 3.10 이상 64비트: 검증 기준 환경으로 Python 3.12 권장
- 프로젝트 저장소와 최초 의존성 다운로드용 인터넷
- 프로그램 사용·프로젝트 저장 권한이 있는 폴더

PyInstaller는 실행 중인 운영체제용 프로그램을 만듭니다. Windows exe는 Windows에서 빌드하고 확인해야 합니다. 현재 Linux 개발 환경의 테스트 통과는 Windows exe 완성·검증을 의미하지 않습니다.

## 권장 빌드

저장소 루트에서 PowerShell을 엽니다.

```powershell
.\scripts\build_windows.ps1
```

`py -3.12`를 사용할 수 없으면 다음 중 하나를 지정합니다.

```powershell
.\scripts\build_windows.ps1 -PythonVersion "3.11"
.\scripts\build_windows.ps1 -PythonCommand "C:\Python312\python.exe"
```

스크립트는 `.venv-build`가 없을 때 생성하고, 존재할 때는 유효한 환경인지 확인한 뒤 재사용합니다. 기존 폴더를 임의로 지우지 않습니다. 유효하지 않거나 다른 아키텍처의 기존 환경이면 그 폴더를 검토·이동한 뒤 다시 실행합니다.

사내 PowerShell 정책으로 실행이 차단되면 회사에서 승인한 방식으로 스크립트를 실행하거나 아래 명령을 직접 실행하세요. 시스템 정책을 일괄 변경할 필요는 없습니다.

## 직접 빌드 명령

새 빌드 가상환경을 만들 경우:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-build\Scripts\python.exe -m pip install --editable .
.\.venv-build\Scripts\python.exe -m pytest
.\.venv-build\Scripts\python.exe -m PyInstaller --clean --noconfirm pharma_cost.spec
```

테스트가 실패하면 원인을 확인하고 수정한 뒤 빌드합니다. `.spec`는 `console=False`, `exclude_binaries=True`의 EXE와 COLLECT를 조합하여 `dist/PharmaCostSimulator/`에 실행파일과 의존 파일을 함께 만듭니다. PySide6 공식 훅으로 Qt 플랫폼 플러그인과 런타임을 수집하며 UPX 압축은 사용하지 않습니다.

## 배포 폴더 준비

최종 실행파일은 `dist\PharmaCostSimulator\PharmaCostSimulator.exe`입니다. 배포 폴더 전체를 압축합니다.

```powershell
Compress-Archive -Path .\dist\PharmaCostSimulator -DestinationPath .\dist\PharmaCostSimulator-0.1.0-windows-x64.zip
```

동일 ZIP이 이미 있으면 이름을 바꾸거나 기존 파일의 필요 여부를 확인하세요. 설치 프로그램과 코드 서명은 첫 버전에서 제공하지 않습니다. 기업 보안 정책상 실행 허용·서명이 요구된다면 배포 전에 해당 회사 절차를 따릅니다.

사용자는 ZIP을 쓰기 가능한 로컬 폴더에 풀고 `PharmaCostSimulator.exe`를 실행합니다. `_internal` 및 다른 의존 파일을 지우거나 exe만 따로 복사하지 않습니다. JSON 프로젝트 파일은 `문서` 등 별도 위치에 저장하고 배포 버전 교체 시 기존 프로젝트 파일을 유지합니다.

## 인터넷이 없는 빌드 PC가 필요한 경우

실제 사용 PC와 별개로 빌드 PC 자체도 오프라인인 경우에는 **동일한 Windows 아키텍처·Python 버전**의 인터넷 가능한 PC에서 필요한 wheel을 준비할 수 있습니다. 프로젝트와 wheel 파일을 회사에서 승인한 방법으로 전달합니다.

온라인 Windows PC:

```powershell
py -3.12 -m pip download -r requirements-dev.txt "setuptools>=68" wheel -d wheelhouse
```

오프라인 Windows 빌드 PC:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install --no-index --find-links .\wheelhouse -r requirements-dev.txt "setuptools>=68" wheel
.\.venv-build\Scripts\python.exe -m pip install --no-index --find-links .\wheelhouse --no-build-isolation --editable .
.\.venv-build\Scripts\python.exe -m pytest
.\.venv-build\Scripts\python.exe -m PyInstaller --clean --noconfirm pharma_cost.spec
```

이 경우 인터넷 다운로드가 포함된 기본 빌드 스크립트 대신 위 명령을 사용합니다. Windows용 wheel은 Linux에서 받은 wheel과 호환되지 않을 수 있으므로 운영체제·아키텍처·Python 버전을 맞춥니다.

## 출시 전 실제 PC 확인

1. Windows 빌드 PC에서 pytest가 통과하는지 확인합니다.
2. Python이 없는 별도의 Windows 10/11 64비트 PC에 배포 폴더를 복사합니다.
3. 네트워크가 연결되지 않은 상태에서 exe가 별도 창으로 실행되는지 확인합니다.
4. 시작 시 가상 예제 표시, 제품·약가/원료 입력/수율·고정 비용/계산 결과/시나리오 비교 탭, API·부형제 편집과 행 추가·삭제를 확인합니다. 표 입력 후 Enter·Tab으로 편집을 확정하면 별도 계산 버튼 없이 결과가 갱신되는지 확인합니다. 엑셀의 여러 셀을 Ctrl+C/Ctrl+V로 붙여넣는 기능도 확인합니다.
5. API 20mg × 1,000,000원/kg = 20원, 포장재비 300원/30정 = 10원 등 기준 사례를 확인합니다.
6. 복제 시나리오를 수정했을 때 원본과 비교 결과가 유지되는지 확인합니다.
7. 문서 폴더에 프로젝트 JSON을 저장하고 재실행·열기 후 정보와 결과가 보존되는지 확인합니다.
8. 저장하지 않은 변경이 있을 때 닫기·새 프로젝트·다른 파일 열기에서 저장 확인을 제공하는지 확인합니다.
9. 잘못된 JSON, 수율 0, 음수 금액, 누락된 단가 및 약가 0에 대한 안내를 확인합니다.

이 확인이 끝나기 전에는 Windows 실행파일의 동작 검증이 완료된 것으로 취급하지 않습니다.
