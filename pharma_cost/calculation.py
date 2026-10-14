"""오프라인 제조원가 계산. 중간값은 Decimal로 유지하고 표시 시에만 반올림한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext

from .models import FixedCost, Material, Scenario


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class MaterialResult:
    material_id: str
    unit_price: Decimal | None
    cost: Decimal | None


@dataclass
class CalculationResult:
    api_cost: Decimal | None = None
    excipient_cost: Decimal | None = None
    theoretical_material_cost: Decimal | None = None
    adjusted_material_cost: Decimal | None = None
    packaging_cost: Decimal | None = None
    labor_cost: Decimal | None = None
    total_cost: Decimal | None = None
    cost_rate: Decimal | None = None
    post_addition_cost_rate: Decimal | None = None
    allowed_cost: Decimal | None = None
    required_saving: Decimal | None = None
    target_gap: Decimal | None = None
    material_results: list[MaterialResult] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)


def _number(
    value: Decimal | None,
    path: str,
    label: str,
    issues: list[ValidationIssue],
    *,
    required: bool = True,
    positive: bool = False,
) -> Decimal | None:
    if value is None:
        if required:
            issues.append(ValidationIssue(path, f"{label}을(를) 입력해 주세요."))
        return None
    try:
        # 정수 입력도 지원하지만 bool은 수량으로 인정하지 않는다.
        if isinstance(value, bool):
            raise InvalidOperation
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        issues.append(ValidationIssue(path, f"{label}은(는) 숫자여야 합니다."))
        return None
    if not number.is_finite():
        issues.append(ValidationIssue(path, f"{label}은(는) 유한한 숫자여야 합니다."))
        return None
    # 화면 및 JSON 형식과 같은 범위를 적용한다. Decimal 자체는 극단적인
    # 지수도 받아들이므로, 유한성 확인만으로는 후속 산술 예외를 막지 못한다.
    if abs(number.adjusted()) > 1000 or len(str(number)) > 128:
        issues.append(ValidationIssue(path, f"{label}이(가) 지원하는 숫자 범위를 벗어났습니다."))
        return None
    if number < 0 or (positive and number == 0):
        relation = "0보다 커야" if positive else "0 이상이어야"
        issues.append(ValidationIssue(path, f"{label}은(는) {relation} 합니다."))
        return None
    return number


def _material(material: Material, issues: list[ValidationIssue]) -> MaterialResult:
    path = f"materials.{material.id}"
    start = len(issues)
    amount = _number(material.amount, f"{path}.amount", "실제 투입량", issues)
    krw_price = _number(
        material.krw_price, f"{path}.krw_price", "원화 구매단가", issues,
        required=material.price_source == "krw",
    )
    foreign_price = _number(
        material.foreign_price, f"{path}.foreign_price", "외화 구매단가", issues,
        required=material.price_source == "fx",
    )
    exchange_rate = _number(
        material.exchange_rate, f"{path}.exchange_rate", "환율", issues,
        required=material.price_source == "fx", positive=True,
    )
    if material.kind not in ("api", "excipient"):
        issues.append(ValidationIssue(f"{path}.kind", "API 또는 부형제를 선택해 주세요."))
    if material.basis not in ("mass", "piece"):
        issues.append(ValidationIssue(f"{path}.basis", "질량 또는 개당 구매를 선택해 주세요."))
    if material.price_source == "krw":
        unit_price = krw_price
    elif material.price_source == "fx":
        unit_price = foreign_price * exchange_rate if foreign_price is not None and exchange_rate is not None else None
        if not material.currency.strip():
            issues.append(ValidationIssue(f"{path}.currency", "외화 통화를 입력해 주세요."))
    else:
        issues.append(ValidationIssue(f"{path}.price_source", "원화 직접 입력 또는 외화 환산을 선택해 주세요."))
        unit_price = None
    cost = None
    if len(issues) == start and amount is not None and unit_price is not None:
        cost = amount * unit_price
        if material.basis == "mass":
            cost /= Decimal("1000000")
    return MaterialResult(material.id, unit_price, cost)


def _fixed_cost(cost: FixedCost, path: str, issues: list[ValidationIssue]) -> Decimal | None:
    start = len(issues)
    amount = _number(cost.amount, f"{path}.amount", "비용", issues)
    quantity = _number(
        cost.quantity, f"{path}.quantity", "환산 수량", issues,
        required=cost.basis != "unit", positive=True,
    )
    if cost.basis not in ("unit", "package", "batch"):
        issues.append(ValidationIssue(f"{path}.basis", "단위제형·포장·배치 비용 중 하나를 선택해 주세요."))
    if len(issues) != start or amount is None:
        return None
    if cost.basis == "unit":
        return amount
    return amount / quantity if quantity is not None else None


def calculate(scenario: Scenario) -> CalculationResult:
    """입력 누락은 해당 합계를 미완성으로 반환하고 유효한 부분 합계는 유지한다."""
    result = CalculationResult()
    issues = result.issues
    with localcontext() as context:
        context.prec = 50
        result.material_results = [_material(material, issues) for material in scenario.materials]
        category_costs: dict[str, list[Decimal | None]] = {"api": [], "excipient": []}
        for material, row in zip(scenario.materials, result.material_results):
            if material.kind in category_costs:
                category_costs[material.kind].append(row.cost)
        for kind, field_name in (("api", "api_cost"), ("excipient", "excipient_cost")):
            costs = category_costs[kind]
            value = sum(costs, Decimal("0")) if all(cost is not None for cost in costs) else None
            setattr(result, field_name, value)
        # 알 수 없는 원료 종류를 빠뜨리고 총액을 확정하지 않는다.
        if result.api_cost is not None and result.excipient_cost is not None and all(
            row.cost is not None for row in result.material_results
        ):
            result.theoretical_material_cost = result.api_cost + result.excipient_cost

        yield_percent = _number(scenario.yield_percent, "yield_percent", "제조수율", issues, positive=True)
        if yield_percent is not None and yield_percent > 100:
            issues.append(ValidationIssue("yield_percent", "제조수율은 100% 이하여야 합니다."))
            yield_percent = None
        if yield_percent is not None and result.theoretical_material_cost is not None:
            result.adjusted_material_cost = (
                result.theoretical_material_cost / (yield_percent / Decimal("100"))
                if scenario.apply_yield else result.theoretical_material_cost
            )
        result.packaging_cost = _fixed_cost(scenario.packaging, "packaging", issues)
        result.labor_cost = _fixed_cost(scenario.labor, "labor", issues)
        components = (result.adjusted_material_cost, result.packaging_cost, result.labor_cost)
        if all(value is not None for value in components):
            result.total_cost = sum(components, Decimal("0"))

        insurance_price = _number(
            scenario.pricing.insurance_price, "pricing.insurance_price", "예상 보험약가", issues, required=False,
        )
        if insurance_price is None or insurance_price == 0:
            if not any(issue.path == "pricing.insurance_price" for issue in issues):
                issues.append(ValidationIssue(
                    "pricing.insurance_price", "예상 보험약가가 없거나 0이므로 원가율은 계산 불가입니다.", "warning",
                ))
        elif result.total_cost is not None:
            result.cost_rate = result.total_cost / insurance_price * Decimal("100")

        post_price = _number(
            scenario.pricing.post_addition_price, "pricing.post_addition_price", "가산 종료 후 예상 약가", issues,
            required=False,
        )
        if post_price is not None and post_price > 0 and result.total_cost is not None:
            result.post_addition_cost_rate = result.total_cost / post_price * Decimal("100")
        elif post_price == 0:
            issues.append(ValidationIssue(
                "pricing.post_addition_price", "가산 종료 후 약가가 0이므로 해당 원가율은 계산 불가입니다.", "warning",
            ))
        target_rate = _number(
            scenario.pricing.target_rate, "pricing.target_rate", "목표 제조원가율", issues,
        )
        if insurance_price is not None and insurance_price > 0 and target_rate is not None:
            result.allowed_cost = insurance_price * target_rate / Decimal("100")
            if result.total_cost is not None:
                result.required_saving = max(Decimal("0"), result.total_cost - result.allowed_cost)
        if result.cost_rate is not None and target_rate is not None:
            result.target_gap = result.cost_rate - target_rate

        metadata = scenario.pricing.metadata
        for field_name, label in (
            ("original_current_price", "오리지널 현재 약가"), ("reference_amount", "약가 산정 기준금액"),
        ):
            _number(getattr(metadata, field_name), f"pricing.metadata.{field_name}", label, issues, required=False)
        for field_name in ("listed_product_count", "concurrent_application_count"):
            value = getattr(metadata, field_name)
            checked = _number(value, f"pricing.metadata.{field_name}", "품목 수", issues, required=False)
            if checked is not None and checked != checked.to_integral_value():
                issues.append(ValidationIssue(f"pricing.metadata.{field_name}", "품목 수는 정수여야 합니다."))
    return result
