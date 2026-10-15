"""Eight-year comparison graph labels retain real prices, ratios and preview state."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    add_material,
    comparison,
    project,
    save_file,
    scenario,
    setup_base,
)
from web.tests.test_pricing import comparison_cell, comparison_chart, comparison_year, condition, setup_automatic
from web.tests.test_tabs_print import clone


def price_integer(value):
    with localcontext() as context:
        context.prec = 80
        rounded = Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{rounded:,.0f}"


def overlaps(first, second):
    return (
        min(first["x"] + first["width"], second["x"] + second["width"]) > max(first["x"], second["x"]) + 0.5
        and min(first["y"] + first["height"], second["y"] + second["height"]) > max(first["y"], second["y"]) + 0.5
    )


def assert_finite_and_legible(chart):
    assert not re.search(r"NaN|Infinity|undefined", chart.inner_text())
    assert chart.locator('[style*="NaN"], [style*="Infinity"]').count() == 0
    bounds = chart.bounding_box()
    labels = chart.locator(".comparison-year-price, .comparison-year-rate, .comparison-price-label")
    boxes = []
    for label in labels.all():
        expect(label).to_be_visible()
        box = label.bounding_box()
        assert box["x"] >= bounds["x"] - 1, label.inner_text()
        assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1, label.inner_text()
        assert box["y"] >= bounds["y"] - 1, label.inner_text()
        assert box["y"] + box["height"] <= bounds["y"] + bounds["height"] + 1, label.inner_text()
        assert label.evaluate("node => node.scrollWidth <= node.clientWidth + 1"), label.inner_text()
        boxes.append((box, label.inner_text()))
    for index, (first, first_text) in enumerate(boxes):
        for second, second_text in boxes[index + 1:]:
            assert not overlaps(first, second), f"Overlapping graph labels: {first_text} / {second_text}"


@pytest.mark.parametrize("automatic", [False, True])
def test_comparison_has_eight_years_and_price_labels_while_input_forecast_remains_ten(page, tmp_path, automatic):
    if automatic:
        setup_automatic(page, company="innovative", count="ge14")
        condition(page, "company_eligible").check()
        condition(page, "domestic_extension").check()
        page.locator('[data-pricing-year="10"]').click()
        expect(page.locator("[data-pricing-year]")).to_have_count(10)
        expected_prices = ["600원"] * 4 + ["383원"] * 4
        expected_rates = ["8.3%"] * 4 + ["13.1%"] * 4
    else:
        setup_base(page)
        add_material(page)
        page.locator("#manual-price").fill("1234.56789")
        expected_prices = ["1,235원"] * 8
        expected_rates = ["4.1%"] * 8
    before = project(page)
    current_id = scenario(page)["id"]
    comparison(page)
    chart = comparison_chart(page, current_id)
    bars = chart.locator("[data-comparison-year]")
    expect(bars).to_have_count(8)
    assert bars.evaluate_all("nodes => nodes.map(node => Number(node.dataset.comparisonYear))") == list(range(1, 9))
    expect(chart.locator(".comparison-year-price")).to_have_text(expected_prices)
    expect(chart.locator(".comparison-year-rate")).to_have_text(expected_rates)
    expect(chart.locator('[data-comparison-year="9"], [data-comparison-year="10"]')).to_have_count(0)
    comparison_year(page, current_id, 8).click()
    expect(comparison_cell(page, "composition", current_id).locator(".comparison-donut-year")).to_have_text("8년차")
    expect(comparison_cell(page, "price", current_id)).to_have_text(expected_prices[-1][:-1])
    expect(comparison_year(page, current_id, 8)).to_have_attribute("aria-pressed", "true")
    assert project(page) == before
    assert save_file(page, tmp_path / "eight-year-preview.json") == before
    page.locator("#tab-button-input").click()
    if automatic:
        expect(page.locator("[data-pricing-year]")).to_have_count(10)
        expect(page.locator('[data-pricing-year="10"]')).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#selected-pricing-year")).to_have_text("선택 연차: 10년차")
    else:
        expect(page.locator("#manual-price")).to_have_value("1,234.56789")


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("count", [1, 4])
def test_taller_graph_places_prices_above_bars_and_white_text_rates_inside_cost_region(page, width, count):
    page.set_viewport_size({"width": width, "height": 1000})
    setup_base(page)
    page.locator("#batch-packaging").fill("4000000")
    page.locator("#batch-labor").fill("8000000")
    for index in range(1, count):
        clone(page, f"배치 비교 {index + 1}안")
        page.locator("#manual-price").fill(str(300 + index * 50))
    before = project(page)
    comparison(page)
    charts = page.locator(".comparison-price-chart")
    expect(charts).to_have_count(count)
    axes = charts.evaluate_all("nodes => nodes.map(node => node.dataset.scaleMaximum)")
    assert len(set(axes)) == 1
    for chart in charts.all():
        # The earlier comparison plot was only 90 px high.
        assert chart.locator(".comparison-price-plot").bounding_box()["height"] > 110
        expect(chart.locator(".comparison-year-price")).to_have_count(8)
        for button in chart.locator("[data-comparison-year]").all():
            stack = button.locator(".comparison-price-stack").bounding_box()
            price = button.locator(".comparison-year-price").bounding_box()
            badge = button.locator(".comparison-year-rate")
            rate = badge.bounding_box()
            cost = button.locator(".comparison-cost-fill").bounding_box()
            assert price["y"] + price["height"] <= stack["y"] + 1
            assert rate["y"] >= cost["y"] - 1
            assert rate["y"] + rate["height"] <= cost["y"] + cost["height"] + 1
            assert rate["y"] >= stack["y"]
            assert badge.evaluate(r"""node => {
              const parts = getComputedStyle(node).color.match(/[\d.]+/g).map(Number);
              return parts[0] === 255 && parts[1] === 255 && parts[2] === 255;
            }""")
        assert_finite_and_legible(chart)
    assert project(page) == before


@pytest.mark.parametrize("case", ["zero_cost", "zero_price", "both_zero", "missing_cost", "tiny_cost", "excess_cost"])
def test_special_cost_states_keep_distinct_legible_price_and_rate_labels(page, case):
    setup_base(page)
    page.locator("#batch-packaging").fill("0")
    page.locator("#batch-labor").fill("0")
    if case == "zero_cost":
        expected_price, expected_rate = "300원", "0.0%"
    elif case == "zero_price":
        page.locator("#manual-price").fill("0")
        page.locator("#batch-labor").fill("5000000")
        expected_price, expected_rate = "0원", "계산불가"
    elif case == "both_zero":
        page.locator("#manual-price").fill("0")
        expected_price, expected_rate = "0원", "계산불가"
    elif case == "missing_cost":
        row = add_material(page)
        row.locator('[data-material-field="amount"]').fill("")
        expected_price, expected_rate = "300원", "계산불가"
    elif case == "tiny_cost":
        page.locator("#batch-labor").fill("1000")
        expected_price, expected_rate = "300원", "<0.1%"
    else:
        page.locator("#manual-price").fill("25")
        page.locator("#batch-labor").fill("5000000")
        expected_price, expected_rate = "25원", "200.0%"
    current_id = scenario(page)["id"]
    before = project(page)
    comparison(page)
    chart = comparison_chart(page, current_id)
    expect(chart.locator(".comparison-year-price")).to_have_text([expected_price] * 8)
    expect(chart.locator(".comparison-year-rate")).to_have_text([expected_rate] * 8)
    for button in chart.locator("[data-comparison-year]").all():
        stack = button.locator(".comparison-price-stack").bounding_box()
        price = button.locator(".comparison-year-price").bounding_box()
        rate = button.locator(".comparison-year-rate").bounding_box()
        assert price["y"] + price["height"] <= stack["y"] + 1
        # A negligible or unavailable rate stays near the baseline. A zero-height
        # stack cannot contain a label, so its fallback may sit above the baseline.
        if stack["height"] > 1:
            assert rate["y"] >= stack["y"] - 1
        assert not overlaps(price, rate)
    if case == "missing_cost":
        expect(chart.locator(".comparison-unresolved-fill")).to_have_count(8)
        expect(chart.locator(".comparison-cost-fill")).to_have_count(0)
    if case == "excess_cost":
        expect(chart.locator(".comparison-excess-fill")).to_have_count(8)
    assert_finite_and_legible(chart)
    assert project(page) == before


def test_real_price_edits_update_price_labels_rates_and_preview_together_without_rounding_input(page):
    setup_base(page)
    add_material(page, amount="20.12345", price="1000000")
    page.locator("#manual-price").fill("891.23456789")
    current_id = scenario(page)["id"]
    comparison(page)
    chart = comparison_chart(page, current_id)
    expect(chart.locator(".comparison-year-price")).to_have_text(["891원"] * 8)
    expect(chart.locator(".comparison-year-rate")).to_have_text(["5.6%"] * 8)
    old_height = comparison_year(page, current_id, 1).locator(".comparison-cost-fill").bounding_box()["height"]
    page.locator("#tab-button-input").click()
    page.locator("#manual-price").fill("445.617283945")
    comparison(page)
    expect(chart.locator(".comparison-year-price")).to_have_text([price_integer("445.617283945") + "원"] * 8)
    expect(chart.locator(".comparison-year-rate")).to_have_text(["11.2%"] * 8)
    assert comparison_year(page, current_id, 1).locator(".comparison-cost-fill").bounding_box()["height"] > old_height * 1.9
    comparison_year(page, current_id, 8).click()
    expect(comparison_cell(page, "composition", current_id).locator(".comparison-donut-year")).to_have_text("8년차")
    expect(comparison_cell(page, "composition", current_id).locator('[data-chart-part="rate"]')).to_have_text("11.2%")
    assert scenario(page)["manual_price"] == "445.617283945"
    assert scenario(page)["materials"][0]["amount"] == "20.12345"
