"""Comparison-only currency conversion and display precision regressions."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    add_material,
    comparison,
    project,
    results,
    save_file,
    scenario,
    setup_base,
)
from web.tests.test_presentation import comparison_chart, comparison_row, cost_cell


def display(value, places):
    with localcontext() as context:
        context.prec = 80
        rounded = Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        return f"{rounded:,.{places}f}"


@pytest.mark.parametrize(
    ("unit", "purchase", "krw_per_kg", "usd_per_kg"),
    [
        ("krw_g", "2", "2,000 원/kg", "1 달러/kg"),
        ("krw_kg", "1234567.89", "1,234,568 원/kg", "914 달러/kg"),
        ("usd_g", "1.2345", "1,666,575 원/kg", "1,235 달러/kg"),
        ("usd_kg", "1234.56789", "1,666,667 원/kg", "1,235 달러/kg"),
    ],
)
def test_api_quotes_show_both_integer_kg_currencies_without_changing_input(
    page, unit, purchase, krw_per_kg, usd_per_kg
):
    setup_base(page)
    page.locator("#exchange-rate").fill("1350")
    add_material(page, price=purchase, unit=unit)
    before = project(page)
    comparison(page)
    quotes = comparison_row(page, "api_price").locator(".comparison-api-prices")
    expect(quotes).to_have_count(1)
    expect(quotes.locator(".comparison-api-krw")).to_have_text(krw_per_kg)
    expect(quotes.locator(".comparison-api-usd")).to_have_text(usd_per_kg)
    assert project(page) == before
    assert scenario(page)["materials"][0]["price"] == purchase
    assert scenario(page)["materials"][0]["price_unit"] == unit


@pytest.mark.parametrize("exchange", ["", "0", "-1", "환율오류"])
@pytest.mark.parametrize(
    ("unit", "known_selector", "other_selector", "known_quote"),
    [
        ("krw_g", ".comparison-api-krw", ".comparison-api-usd", "1,235 원/kg"),
        ("usd_g", ".comparison-api-usd", ".comparison-api-krw", "1,235 달러/kg"),
    ],
)
def test_missing_or_invalid_exchange_keeps_known_quote_and_marks_other_currency(
    page, exchange, unit, known_selector, other_selector, known_quote
):
    setup_base(page)
    add_material(page, price="1.2345", unit=unit)
    page.locator("#exchange-rate").fill(exchange)
    comparison(page)
    quotes = comparison_row(page, "api_price").locator(".comparison-api-prices")
    expect(quotes.locator(known_selector)).to_have_text(known_quote)
    expect(quotes.locator(other_selector)).to_contain_text("환율 필요")
    expect(quotes.locator(other_selector)).not_to_contain_text("0 원/kg")
    expect(quotes.locator(other_selector)).not_to_contain_text("0 달러/kg")
    assert not re.search(r"NaN|Infinity|undefined", quotes.inner_text())


def test_comparison_precision_applies_to_cells_charts_and_tooltips_only(page, tmp_path):
    setup_base(page)
    page.locator("#exchange-rate").fill("1350.12345")
    page.locator("#yield-percent").fill("97.7")
    page.locator("#manual-price").fill("300.12654321")
    page.locator("#batch-packaging").fill("1000000.456789")
    page.locator("#batch-labor").fill("2000000.567891")
    add_material(page, amount="20.12654321", price="1000000.123456789")
    add_material(page, kind="excipient", amount="100.7654321", price="123456.789012345")
    before = project(page)
    active_id = scenario(page)["id"]
    raw = page.evaluate("""() => {
      const p = PharmaCostApp.getProject();
      const s = p.scenarios.find(s => s.id === p.active_scenario_id);
      const r = PharmaCost.calculate(s);
      const keys = ['api_batch', 'api_unit', 'excipient_batch', 'excipient_unit',
        'packaging_unit', 'labor_unit', 'raw_unit', 'total_cost', 'cost_rate'];
      return Object.fromEntries(keys.map(key => [key, r[key].toString()]));
    }""")
    results(page)
    expect(page.locator("#result-price")).to_have_text("300")
    expect(page.locator("#result-cost")).to_have_text(display(raw["total_cost"], 2))
    expect(page.locator("#donut-total")).to_have_text(display(raw["total_cost"], 2) + " 원/T")
    expect(page.locator("#donut-note")).to_have_text("보험약가 기준 · 300 원/T")
    expect(page.locator("#composition-donut")).to_have_attribute(
        "aria-label", re.compile(r"^보험약가 300 원/T 기준")
    )
    # Display rounding must never replace the actual insurance-price denominator.
    with localcontext() as context:
        context.prec = 80
        actual_rate = Decimal(raw["cost_rate"])
        expected_rate = Decimal(raw["total_cost"]) / Decimal("300.12654321") * 100
        rounded_price_rate = Decimal(raw["total_cost"]) / Decimal("300") * 100
        assert abs(actual_rate - expected_rate) < Decimal("1e-40")
        assert abs(actual_rate - rounded_price_rate) > Decimal("0.0001")
    expect(page.locator("#result-rate")).to_have_text(display(raw["cost_rate"], 1))
    comparison(page)
    expect(comparison_row(page, "price").locator("td")).to_have_text("300")
    expect(comparison_row(page, "cost_rate").locator("td")).to_have_text(display(raw["cost_rate"], 1) + "%")
    expect(comparison_row(page, "total_cost").locator("td")).to_have_text(display(raw["total_cost"], 1))
    for field, batch, unit in [
        ("api_cost", raw["api_batch"], raw["api_unit"]),
        ("excipient_cost", raw["excipient_batch"], raw["excipient_unit"]),
        ("packaging_cost", "1000000.456789", raw["packaging_unit"]),
        ("labor_cost", "2000000.567891", raw["labor_unit"]),
    ]:
        batch_cell = cost_cell(page, field, active_id, "batch")
        unit_cell = cost_cell(page, field, active_id, "unit")
        expect(batch_cell).to_have_text(display(batch, 0))
        expect(unit_cell).to_have_text(display(unit, 1))
        expect(batch_cell).to_have_attribute("title", f"배치당: {display(batch, 0)} 원")
        expect(unit_cell).to_have_attribute("title", f"1T당: {display(unit, 1)} 원/T")
    graph = comparison_chart(page, active_id)
    expect(graph.locator('[data-chart-part="note"]')).to_have_text("보험약가 기준 · 300 원/T")
    expect(graph.locator(".donut-total")).to_have_text(display(raw["total_cost"], 1) + " 원/T")
    expect(graph.locator('[data-chart-part="raw-total"]')).to_have_text(display(raw["raw_unit"], 1) + " 원/T")
    for item, key in [("api", "api_unit"), ("excipient", "excipient_unit"), ("packaging", "packaging_unit"), ("labor", "labor_unit")]:
        expect(graph.locator(f'.composition-row[data-item="{item}"] .composition-amount')).to_have_text(display(raw[key], 1) + " 원/T")
    # Cost labels, segment tooltips and the common scale retain one place per T.
    cost_texts = graph.locator(
        '.donut-total, .composition-amount, [data-chart-part="raw-total"], [data-chart-part="remainder"]'
    ).all_text_contents()
    cost_texts.extend(graph.locator("title").all_text_contents())
    cost_texts.extend(graph.locator(".composition-segment").evaluate_all("nodes => nodes.map(node => node.title)"))
    cost_texts.extend(page.locator(".comparison-price-scale, .comparison-cost-key").all_text_contents())
    for text in cost_texts:
        for amount in re.findall(r"([\d,]+(?:\.\d+)?)\s*원/T", text):
            assert re.fullmatch(r"[\d,]+\.\d", amount), text
    # Each bar separately distinguishes its integer drug price from its cost.
    expect(page.locator(".comparison-year-price")).to_have_text(["300원"] * 8)
    for title in page.locator(".comparison-price-year").evaluate_all("nodes => nodes.map(node => node.title)"):
        price = re.search(r"약가 ([\d,]+(?:\.\d+)?) 원/T", title)
        cost = re.search(r"제조원가 ([\d,]+(?:\.\d+)?) 원/T", title)
        assert price and price.group(1) == "300", title
        assert cost and cost.group(1) == display(raw["total_cost"], 1), title
        assert re.fullmatch(r"[\d,]+", price.group(1)), title
        assert re.fullmatch(r"[\d,]+\.\d", cost.group(1)), title
    assert project(page) == before
    saved = save_file(page, tmp_path / "comparison-display-precision.json")
    assert saved == before
    assert saved["scenarios"][0]["manual_price"] == "300.12654321"
    assert saved["scenarios"][0]["materials"][0]["price"] == "1000000.123456789"


def test_zero_api_purchase_quotes_remain_zero_with_valid_exchange(page):
    setup_base(page)
    page.locator("#exchange-rate").fill("1350")
    add_material(page, price="0", unit="usd_kg")
    comparison(page)
    quotes = comparison_row(page, "api_price").locator(".comparison-api-prices")
    expect(quotes.locator(".comparison-api-krw")).to_have_text("0 원/kg")
    expect(quotes.locator(".comparison-api-usd")).to_have_text("0 달러/kg")
