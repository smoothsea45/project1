"""수식·미완성 입력·시나리오 독립성을 GUI 없이 검증한다."""

from decimal import Decimal

import pytest

from pharma_cost.calculation import calculate
from pharma_cost.models import FixedCost, Material, PricingInput, Project, Scenario, clone_scenario
from pharma_cost.pricing import assess_pricing


D = Decimal


def material_cost(value: str, *, kind: str = "api") -> Material:
    return Material(kind=kind, amount=D("1"), krw_price=D(value) * D("1000000"))


def test_api_twenty_mg_costs_twenty_won():
    scenario = Scenario(materials=[Material(amount=D("20"), krw_price=D("1000000"))])
    result = calculate(scenario)
    assert result.material_results[0].cost == D("20")
    assert result.api_cost == D("20")
    assert result.total_cost == D("20")


def test_eighty_percent_yield_adjusts_hundred_to_hundred_twenty_five():
    result = calculate(Scenario(materials=[material_cost("100")], yield_percent=D("80")))
    assert result.theoretical_material_cost == D("100")
    assert result.adjusted_material_cost == D("125")


def test_packaging_three_hundred_per_thirty_is_ten():
    result = calculate(Scenario(packaging=FixedCost(basis="package", amount=D("300"), quantity=D("30"))))
    assert result.packaging_cost == D("10")


def test_batch_labor_two_million_per_hundred_thousand_is_twenty():
    result = calculate(Scenario(labor=FixedCost(basis="batch", amount=D("2000000"), quantity=D("100000"))))
    assert result.labor_cost == D("20")


def test_sixty_won_at_three_hundred_is_twenty_percent():
    result = calculate(Scenario(materials=[material_cost("60")], pricing=PricingInput(insurance_price=D("300"))))
    assert result.total_cost == D("60")
    assert result.cost_rate == D("20")


def test_target_twenty_percent_requires_fifteen_won_saving():
    result = calculate(Scenario(materials=[material_cost("75")], pricing=PricingInput(insurance_price=D("300"), target_rate=D("20"))))
    assert result.allowed_cost == D("60")
    assert result.required_saving == D("15")
    assert result.target_gap == D("5")


def test_combination_product_sums_all_apis_and_separates_excipients():
    result = calculate(Scenario(materials=[material_cost("20"), material_cost("30"), material_cost("4", kind="excipient")]))
    assert result.api_cost == D("50")
    assert result.excipient_cost == D("4")
    assert result.theoretical_material_cost == D("54")


def test_piece_material_uses_piece_amount_and_price():
    row = Material(kind="excipient", basis="piece", amount=D("1"), krw_price=D("12.5"))
    result = calculate(Scenario(materials=[row]))
    assert result.excipient_cost == D("12.5")
    assert result.material_results[0].cost == D("12.5")


def test_foreign_currency_source_uses_foreign_price_times_exchange():
    row = Material(amount=D("20"), price_source="fx", krw_price=D("999999"), foreign_price=D("100"), exchange_rate=D("1400"))
    result = calculate(Scenario(materials=[row]))
    assert result.material_results[0].unit_price == D("140000")
    assert result.api_cost == D("2.8")


def test_disabling_yield_adjustment_preserves_theoretical_cost():
    result = calculate(Scenario(materials=[material_cost("100")], yield_percent=D("80"), apply_yield=False))
    assert result.adjusted_material_cost == D("100")


def test_yield_does_not_adjust_packaging_or_labor():
    result = calculate(Scenario(
        materials=[material_cost("100")], yield_percent=D("80"),
        packaging=FixedCost(amount=D("10")), labor=FixedCost(amount=D("20")),
    ))
    assert result.api_cost == D("100")
    assert result.packaging_cost == D("10")
    assert result.labor_cost == D("20")
    assert result.total_cost == D("155")


@pytest.mark.parametrize("yield_percent", [D("0"), D("-1"), D("100.01"), D("NaN"), None])
@pytest.mark.parametrize("apply_yield", [True, False])
def test_invalid_yield_is_rejected_even_when_disabled(yield_percent, apply_yield):
    result = calculate(Scenario(materials=[material_cost("10")], yield_percent=yield_percent, apply_yield=apply_yield))
    assert result.theoretical_material_cost == D("10")
    assert result.adjusted_material_cost is None
    assert result.total_cost is None
    assert any(issue.path == "yield_percent" and issue.severity == "error" for issue in result.issues)


@pytest.mark.parametrize("field,value", [
    ("amount", D("-1")), ("amount", None), ("krw_price", D("-1")),
    ("krw_price", D("Infinity")), ("krw_price", None), ("amount", True),
])
def test_invalid_material_input_does_not_create_a_complete_total(field, value):
    row = material_cost("20")
    setattr(row, field, value)
    result = calculate(Scenario(materials=[row, material_cost("5", kind="excipient")]))
    assert result.api_cost is None
    assert result.excipient_cost == D("5")
    assert result.theoretical_material_cost is None
    assert result.total_cost is None
    assert any(issue.path == f"materials.{row.id}.{field}" for issue in result.issues)


@pytest.mark.parametrize("quantity", [D("0"), D("-1"), None])
def test_packaging_conversion_requires_positive_quantity(quantity):
    result = calculate(Scenario(packaging=FixedCost(basis="package", amount=D("300"), quantity=quantity)))
    assert result.packaging_cost is None
    assert result.total_cost is None
    assert any(issue.path == "packaging.quantity" for issue in result.issues)


@pytest.mark.parametrize("exchange_rate", [D("0"), D("-1"), None])
def test_fx_conversion_requires_positive_exchange_rate(exchange_rate):
    row = Material(amount=D("20"), price_source="fx", foreign_price=D("100"), exchange_rate=exchange_rate)
    result = calculate(Scenario(materials=[row]))
    assert result.api_cost is None
    assert any(issue.path == f"materials.{row.id}.exchange_rate" for issue in result.issues)


@pytest.mark.parametrize("price", [None, D("0")])
def test_missing_or_zero_insurance_price_keeps_cost_but_has_no_rate(price):
    result = calculate(Scenario(materials=[material_cost("60")], pricing=PricingInput(insurance_price=price)))
    assert result.total_cost == D("60")
    assert result.cost_rate is None
    assert result.allowed_cost is None
    assert any(issue.path == "pricing.insurance_price" and issue.severity == "warning" for issue in result.issues)


def test_negative_insurance_price_is_error_without_hiding_cost():
    result = calculate(Scenario(materials=[material_cost("60")], pricing=PricingInput(insurance_price=D("-300"))))
    assert result.total_cost == D("60")
    assert result.cost_rate is None
    assert any(issue.path == "pricing.insurance_price" and issue.severity == "error" for issue in result.issues)


def test_cost_rate_over_hundred_is_not_clamped_and_target_zero_is_supported():
    result = calculate(Scenario(materials=[material_cost("75")], pricing=PricingInput(insurance_price=D("30"), target_rate=D("0"))))
    assert result.cost_rate == D("250")
    assert result.allowed_cost == D("0")
    assert result.required_saving == D("75")
    assert result.target_gap == D("250")


def test_target_above_hundred_has_no_artificial_limit():
    result = calculate(Scenario(materials=[material_cost("75")], pricing=PricingInput(insurance_price=D("30"), target_rate=D("300"))))
    assert result.allowed_cost == D("90")
    assert result.required_saving == D("0")
    assert result.target_gap == D("-50")


@pytest.mark.parametrize("post_price,expected", [(None, None), (D("0"), None), (D("200"), D("30"))])
def test_optional_post_addition_price(post_price, expected):
    result = calculate(Scenario(materials=[material_cost("60")], pricing=PricingInput(insurance_price=D("300"), post_addition_price=post_price)))
    assert result.post_addition_cost_rate == expected


def test_no_intermediate_display_rounding():
    result = calculate(Scenario(materials=[material_cost("0.0049"), material_cost("0.0049")]))
    assert result.total_cost == D("0.0098")


def test_scenario_clone_is_independent_of_all_original_nested_inputs():
    original = Scenario(materials=[material_cost("20")])
    original.pricing.metadata.reference_product = "기준 제품"
    project = Project(scenarios=[original])
    clone = clone_scenario(project, original.id, "API 변경")
    assert clone.id != original.id
    assert clone.materials[0].id != original.materials[0].id
    assert project.active_scenario is clone
    clone.materials[0].krw_price = D("100")
    clone.pricing.insurance_price = D("300")
    clone.pricing.metadata.reference_product = "수정 제품"
    clone.packaging.amount = D("10")
    assert original.materials[0].krw_price == D("20000000")
    assert original.pricing.insurance_price is None
    assert original.pricing.metadata.reference_product == "기준 제품"
    assert original.packaging.amount == D("0")
    assert len(project.scenarios) == 2


def test_clone_missing_scenario_does_not_mutate_project():
    project = Project()
    with pytest.raises(ValueError, match="복제할 시나리오"):
        clone_scenario(project, "missing", "복제")
    assert len(project.scenarios) == 1


def test_pricing_assessment_preserves_manual_source_without_calculating_rules():
    pricing = PricingInput(insurance_price=D("300"))
    pricing.metadata.product_type = "제네릭"
    pricing.metadata.participation_form = "1+3 참여"
    pricing.metadata.reference_amount = D("1000")
    assessment = assess_pricing(pricing)
    assert assessment.amount == D("300")
    assert assessment.source == "사용자 입력값"
    assert assessment.regulation is None
    assert assessment.basis_date is None
    assert assessment.steps


@pytest.mark.parametrize("field", ["original_current_price", "reference_amount", "listed_product_count", "concurrent_application_count"])
def test_negative_future_pricing_metadata_is_reported(field):
    scenario = Scenario()
    setattr(scenario.pricing.metadata, field, D("-1"))
    result = calculate(scenario)
    assert any(issue.path == f"pricing.metadata.{field}" for issue in result.issues)


def test_unknown_material_kind_is_not_silently_omitted_from_total():
    row = material_cost("20")
    row.kind = "unknown"
    result = calculate(Scenario(materials=[row]))
    assert result.total_cost is None
    assert any(issue.path == f"materials.{row.id}.kind" for issue in result.issues)


@pytest.mark.parametrize("value", [D("1e1001"), D("1e-1001"), D("1e1000000"), D("9" * 129)])
def test_material_numeric_range_is_rejected_without_arithmetic_exception(value):
    row = Material(amount=D("20"), krw_price=value)
    result = calculate(Scenario(materials=[row]))
    assert result.total_cost is None
    assert any(
        issue.path == f"materials.{row.id}.krw_price" and "범위" in issue.message
        for issue in result.issues
    )


@pytest.mark.parametrize("value", [D("1e1000000"), D("1e-1000000"), D("1." + "0" * 127)])
def test_out_of_range_pricing_does_not_hide_valid_manufacturing_cost(value):
    result = calculate(Scenario(
        materials=[material_cost("60")], pricing=PricingInput(insurance_price=value),
    ))
    assert result.total_cost == D("60")
    assert result.cost_rate is None
    assert any(issue.path == "pricing.insurance_price" and issue.severity == "error" for issue in result.issues)


@pytest.mark.parametrize("apply_yield", [True, False])
def test_extreme_small_yield_reports_range_error_without_division_exception(apply_yield):
    result = calculate(Scenario(
        materials=[material_cost("20")], yield_percent=D("1e-1000000"), apply_yield=apply_yield,
    ))
    assert result.theoretical_material_cost == D("20")
    assert result.adjusted_material_cost is None
    assert any(issue.path == "yield_percent" and "범위" in issue.message for issue in result.issues)


@pytest.mark.parametrize("value", [D("1e1000"), D("1e-1000"), D("9" * 128)])
def test_supported_numeric_range_boundary_is_accepted(value):
    row = Material(amount=D("1"), krw_price=value)
    result = calculate(Scenario(materials=[row]))
    assert result.total_cost is not None
    assert not any(issue.path == f"materials.{row.id}.krw_price" for issue in result.issues)
