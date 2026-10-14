"""Versioned, lossless JSON project files; independent of the desktop UI."""

from __future__ import annotations

import json
import os
import re
import tempfile
import types
from dataclasses import fields, is_dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from .models import Project


FORMAT_VERSION = 1
FORMAT_MARKER = "pharma-cost-project"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SCENARIOS = 200
MAX_MATERIALS = 5000
MAX_TEXT_LENGTH = 100_000


class ProjectFileError(ValueError):
    """A project file cannot be read or written safely."""


_LABELS = {
    "product": "제품정보", "project_name": "프로젝트명", "product_name": "제품명",
    "dosage_form": "제형", "label_strength": "표시 함량", "memo": "메모",
    "scenarios": "시나리오", "active_scenario_id": "선택 시나리오 ID",
    "is_example": "가상 예제 여부", "id": "ID", "name": "이름",
    "pricing": "약가", "insurance_price": "예상 보험약가",
    "post_addition_price": "가산 종료 후 약가", "target_rate": "목표 제조원가율",
    "metadata": "약가 산정 참고정보", "product_type": "제품 유형",
    "development_method": "개발·자료 확보 방식", "participation_form": "1+3 참여 형태",
    "reference_product": "기준 제품", "original_current_price": "오리지널 현재 약가",
    "reference_amount": "약가 산정 기준금액",
    "bioequivalence_requirement": "자체 생동 관련 요건",
    "registered_api_requirement": "등록 원료의약품 사용 요건",
    "listed_product_count": "기등재 동일제제 품목 수",
    "concurrent_application_count": "동시 신청 예상 품목 수",
    "addition_conditions": "가산 조건", "expected_application_date": "예상 신청 시점",
    "expected_listing_date": "예상 등재 시점", "materials": "원료",
    "kind": "원료 구분", "specification": "등급·규격", "supplier": "제조원·공급처",
    "basis": "비용 기준", "amount": "금액·사용량", "price_source": "단가 입력 방식",
    "krw_price": "원화 구매단가", "foreign_price": "외화단가", "currency": "통화",
    "exchange_rate": "환율", "quotation_date": "견적일",
    "yield_percent": "제조수율", "apply_yield": "수율 보정 여부",
    "packaging": "포장재비", "labor": "공수비", "quantity": "환산 수량",
}
_DECIMAL_PATTERN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z", re.ASCII)


def _label(path: str) -> str:
    return ".".join(_LABELS.get(part, part) for part in path.split(".")) or "프로젝트"


def _error(path: str, message: str) -> ProjectFileError:
    return ProjectFileError(f"{_label(path)}: {message}")


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ProjectFileError("유한한 숫자만 저장할 수 있습니다.")
        return str(value)
    if is_dataclass(value):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    return value


def _decode(annotation: Any, value: Any, path: str) -> Any:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in (Union, types.UnionType):
        if value is None and type(None) in arguments:
            return None
        non_null = [argument for argument in arguments if argument is not type(None)]
        if len(non_null) == 1:
            return _decode(non_null[0], value, path)
        raise _error(path, "지원하지 않는 데이터 형식입니다.")
    if is_dataclass(annotation):
        if type(value) is not dict:
            raise _error(path, "객체 형식이어야 합니다.")
        model_fields = fields(annotation)
        expected = {field.name for field in model_fields}
        unknown = set(value) - expected
        if unknown:
            raise _error(path, f"알 수 없는 항목이 있습니다: {', '.join(sorted(unknown))}")
        missing = expected - set(value)
        if missing:
            missing_labels = [_LABELS.get(key, key) for key in sorted(missing)]
            raise _error(path, f"필수 저장 항목이 없습니다: {', '.join(missing_labels)}")
        hints = get_type_hints(annotation)
        kwargs = {
            field.name: _decode(hints[field.name], value[field.name], f"{path}.{field.name}".strip("."))
            for field in model_fields
        }
        return annotation(**kwargs)
    if origin is list:
        if type(value) is not list:
            raise _error(path, "목록 형식이어야 합니다.")
        limit = MAX_SCENARIOS if path == "scenarios" else MAX_MATERIALS
        if len(value) > limit:
            raise _error(path, f"항목 수가 최대 {limit:,}개를 초과했습니다.")
        return [_decode(arguments[0], item, f"{path}.{index + 1}") for index, item in enumerate(value)]
    if annotation is Decimal:
        if type(value) is not str:
            raise _error(path, "숫자는 문자열 형식으로 저장되어야 합니다.")
        if len(value) > 128 or not _DECIMAL_PATTERN.fullmatch(value):
            raise _error(path, "올바른 유한 숫자가 아닙니다.")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise _error(path, "올바른 숫자가 아닙니다.") from exc
        if not number.is_finite() or abs(number.adjusted()) > 1000:
            raise _error(path, "숫자가 지원 범위를 벗어났습니다.")
        if number < 0:
            raise _error(path, "음수는 사용할 수 없습니다.")
        if path.endswith(".exchange_rate") or path.endswith(".quantity"):
            if number <= 0:
                raise _error(path, "0보다 커야 합니다.")
        if path.endswith(".yield_percent") and not Decimal("0") < number <= Decimal("100"):
            raise _error(path, "0% 초과, 100% 이하이어야 합니다.")
        return number
    if annotation is int:
        if type(value) is not int or value < 0:
            raise _error(path, "0 이상의 정수이어야 합니다.")
        return value
    if annotation is bool:
        if type(value) is not bool:
            raise _error(path, "참 또는 거짓 형식이어야 합니다.")
        return value
    if annotation is str:
        if type(value) is not str:
            raise _error(path, "문자열 형식이어야 합니다.")
        if len(value) > MAX_TEXT_LENGTH:
            raise _error(path, "문자열이 너무 깁니다.")
        return value
    raise _error(path, "지원하지 않는 데이터 형식입니다.")


def _check_choice(value: str, choices: set[str], path: str) -> None:
    if value not in choices:
        raise _error(path, f"지원하지 않는 값입니다: {value!r}")


def _validate_project(project: Project) -> None:
    _check_choice(project.product.dosage_form, {"tablet", "capsule"}, "product.dosage_form")
    if not project.scenarios:
        raise _error("scenarios", "하나 이상의 시나리오가 필요합니다.")
    scenario_ids: set[str] = set()
    for index, scenario in enumerate(project.scenarios, 1):
        path = f"scenarios.{index}"
        if not scenario.id.strip() or len(scenario.id) > 128:
            raise _error(f"{path}.id", "비어 있지 않은 128자 이하 ID가 필요합니다.")
        if scenario.id in scenario_ids:
            raise _error(f"{path}.id", "시나리오 ID가 중복되었습니다.")
        scenario_ids.add(scenario.id)
        for key in ("bioequivalence_requirement", "registered_api_requirement"):
            _check_choice(getattr(scenario.pricing.metadata, key), {"unknown", "yes", "no"}, f"{path}.pricing.metadata.{key}")
        for cost_name in ("packaging", "labor"):
            cost = getattr(scenario, cost_name)
            _check_choice(cost.basis, {"unit", "package", "batch"}, f"{path}.{cost_name}.basis")
        material_ids: set[str] = set()
        for row, material in enumerate(scenario.materials, 1):
            material_path = f"{path}.materials.{row}"
            if not material.id.strip() or len(material.id) > 128:
                raise _error(f"{material_path}.id", "비어 있지 않은 128자 이하 ID가 필요합니다.")
            if material.id in material_ids:
                raise _error(f"{material_path}.id", "원료 ID가 중복되었습니다.")
            material_ids.add(material.id)
            _check_choice(material.kind, {"api", "excipient"}, f"{material_path}.kind")
            _check_choice(material.basis, {"mass", "piece"}, f"{material_path}.basis")
            _check_choice(material.price_source, {"krw", "fx"}, f"{material_path}.price_source")
    if project.active_scenario_id not in scenario_ids:
        raise _error("active_scenario_id", "프로젝트에 없는 시나리오를 가리킵니다.")


def project_to_dict(project: Project) -> dict[str, Any]:
    """Convert a project to the public JSON schema without rounding Decimals."""
    if not isinstance(project, Project):
        raise ProjectFileError("저장할 데이터가 프로젝트 형식이 아닙니다.")
    payload = {"format": FORMAT_MARKER, "schema_version": FORMAT_VERSION, **_encode(project)}
    project_from_dict(payload)
    return payload


def project_from_dict(payload: Any) -> Project:
    """Read the public schema; incomplete optional numeric inputs stay None."""
    if type(payload) is not dict:
        raise ProjectFileError("프로젝트 파일의 최상위 데이터는 객체 형식이어야 합니다.")
    if payload.get("format") != FORMAT_MARKER:
        raise ProjectFileError("의약품 제조원가율 시뮬레이터 프로젝트 파일이 아닙니다.")
    version = payload.get("schema_version")
    if type(version) is not int:
        raise ProjectFileError("파일 형식 버전은 정수이어야 합니다.")
    if version != FORMAT_VERSION:
        raise ProjectFileError(f"지원하지 않는 파일 형식 버전입니다: {version}. 지원 버전은 {FORMAT_VERSION}입니다.")
    if payload.get("active_scenario_id") == "":
        raise _error("active_scenario_id", "선택 시나리오 ID가 비어 있습니다.")
    project = _decode(Project, {key: value for key, value in payload.items() if key not in {"format", "schema_version"}}, "")
    _validate_project(project)
    return project


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectFileError(f"파일에 중복된 항목 이름이 있습니다: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ProjectFileError(f"파일에 유효하지 않은 숫자가 있습니다: {value}")


def load_project(path: str | Path) -> Project:
    """Load a bounded UTF-8 JSON file and explain malformed files in Korean."""
    try:
        with Path(path).open("rb") as file:
            data = file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ProjectFileError(f"프로젝트 파일이 최대 {MAX_FILE_BYTES // 1024 // 1024}MB를 초과했습니다.")
        payload = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_json_object, parse_constant=_invalid_constant)
        return project_from_dict(payload)
    except ProjectFileError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProjectFileError("프로젝트 파일의 JSON 형식이 올바르지 않습니다. UTF-8 JSON 파일인지 확인하세요.") from exc
    except OSError as exc:
        raise ProjectFileError(f"프로젝트 파일을 열 수 없습니다: {exc.strerror or str(exc)}") from exc


def save_project(project: Project, path: str | Path) -> None:
    """Atomically replace the destination after validation and a complete write."""
    payload = project_to_dict(project)
    data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(data.encode("utf-8")) > MAX_FILE_BYTES:
        raise ProjectFileError(f"프로젝트 파일이 최대 {MAX_FILE_BYTES // 1024 // 1024}MB를 초과했습니다.")
    destination = Path(path)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as file:
            temporary = file.name
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError as exc:
        raise ProjectFileError(f"프로젝트 파일을 저장할 수 없습니다: {exc.strerror or str(exc)}") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
