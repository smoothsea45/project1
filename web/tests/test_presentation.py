"""Presentation and scenario comparison checks against live app calculations."""

import json
import re

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    add_material,
    comparison,
    new_project,
    open_file,
    project,
    results,
    save_file,
    scenario,
    setup_base,
)


COMPARISON_FIELDS = [
    "name", "batch_size", "yield_percent", "packaging_form", "api_supplier",
    "api_price", "price", "total_cost", "cost_rate", "composition", "api_batch",
    "api_unit", "excipient_batch", "excipient_unit", "packaging_batch",
    "packaging_unit", "labor_batch", "labor_unit",
]


def comparison_row(page, field):
    return page.locator(f'#comparison-body tr[data-comparison-field="{field}"]')


def comparison_chart(page, scenario_id):
    return page.locator(f'.comparison-composition[data-scenario-id="{scenario_id}"]')


def test_money_and_percent_precision_are_display_only(page):
    setup_base(page)
    row = add_material(page, amount="20.12654321", price="1000000.0000")
    page.locator("#manual-price").fill("300.000001")
    expect(row.locator('[data-material-field="amount"]')).to_have_value("20.12654321")
    expect(row.locator('[data-material-field="price"]')).to_have_value("1,000,000.0000")
    expect(row.locator('[data-result-field="unit_cost"]')).to_have_text("20.13")
    expect(row.locator('[data-result-field="batch_cost"]')).to_have_text("2,012,654.32")
    for selector, expected in [
        ("#api-unit", "20.13"), ("#excipient-unit", "0.00"),
        ("#packaging-unit", "10.00"), ("#labor-unit", "20.00"),
    ]:
        expect(page.locator(selector)).to_have_text(expected)
    results(page)
    expect(page.locator("#result-price")).to_have_text("300.00")
    expect(page.locator("#result-cost")).to_have_text("50.13")
    expect(page.locator("#result-rate")).to_have_text("16.7")
    expect(page.locator("#donut-rate")).to_have_text("16.7%")
    expect(page.locator("#donut-total")).to_have_text("50.13 원/T")
    comparison(page)
    expect(comparison_row(page, "api_price").locator("td")).to_contain_text("1,000,000.00 원/kg")
    expect(comparison_row(page, "yield_percent").locator("td")).to_have_text("100.0%")
    expect(comparison_row(page, "cost_rate").locator("td")).to_have_text("16.7%")
    data = scenario(page)
    assert data["materials"][0]["amount"] == "20.12654321"
    assert data["materials"][0]["price"] == "1000000.0000"
    assert data["manual_price"] == "300.000001"
    exact = page.evaluate("""() => {
      const p = PharmaCostApp.getProject();
      const s = p.scenarios.find(s => s.id === p.active_scenario_id);
      const r = PharmaCost.calculate(s);
      return [r.api_unit.toString(), r.total_cost.toString()];
    }""")
    assert exact == ["20.12654321", "50.12654321"]


def test_packaging_form_is_independent_scenario_input_and_persists(page, tmp_path):
    setup_base(page)
    add_material(page)
    expect(page.locator("#packaging-form")).to_have_attribute("type", "text")
    page.locator("#packaging-form").fill("30T / PTP (10T × 3)")
    original = scenario(page)
    assert original["packaging_form"] == "30T / PTP (10T × 3)"
    page.once("dialog", lambda dialog: dialog.accept("병 포장안"))
    page.locator("#clone-scenario").click()
    expect(page.locator("#packaging-form")).to_have_value("30T / PTP (10T × 3)")
    page.locator("#packaging-form").fill("100T / 병")
    expected = project(page)
    assert expected["scenarios"][0] == original
    assert expected["scenarios"][1]["packaging_form"] == "100T / 병"
    comparison(page)
    cells = comparison_row(page, "packaging_form").locator("td")
    expect(cells.nth(0)).to_have_text("30T / PTP (10T × 3)")
    expect(cells.nth(1)).to_have_text("100T / 병")
    saved = tmp_path / "packaging.json"
    assert save_file(page, saved) == expected
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    expect(page.locator("#packaging-form")).to_have_value("100T / 병")
    assert project(page) == expected
    new_project(page)
    open_file(page, saved)
    expect(page.locator("#packaging-form")).to_have_value("100T / 병")
    assert project(page) == expected
    page.locator("#scenario-select").select_option(original["id"])
    expect(page.locator("#packaging-form")).to_have_value("30T / PTP (10T × 3)")


def test_existing_json_without_packaging_form_opens_with_empty_optional_field(page):
    payload = project(page)
    for item in payload["scenarios"]:
        item.pop("packaging_form", None)
    open_file(page, {
        "name": "existing-project.json", "mimeType": "application/json",
        "buffer": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    })
    expect(page.locator("#packaging-form")).to_have_value("")
    results(page)
    expect(page.locator("#result-cost")).to_have_text("80.00")
    expect(page.locator("#result-rate")).to_have_text("26.7")
    assert all(item["packaging_form"] == "" for item in project(page)["scenarios"])


def test_result_card_order_and_pricing_basis_removal(page):
    results(page)
    assert page.locator("#tab-results .metric-card strong").evaluate_all(
        "nodes => nodes.map(node => node.id)"
    ) == ["result-price", "result-cost", "result-rate"]
    expect(page.locator("#tab-results .metric-card")).to_have_count(3)
    expect(page.locator("#tab-results")).not_to_contain_text("약가 계산 근거")
    expect(page.locator("#pricing-rule, #pricing-date, #pricing-steps, #result-post-rate")).to_have_count(0)
    expect(page.locator("#pricing-source")).to_have_text("사용자 입력값")


def test_tiny_positive_cost_share_does_not_look_like_zero_percent(page):
    setup_base(page)
    add_material(page, price="1")
    results(page)
    expect(page.locator('#composition-body [data-item="api"] .composition-share')).to_have_text("<0.1%")
    assert float(page.locator('#composition-stack [data-item="api"]').get_attribute("data-share")) > 0
    active_id = scenario(page)["id"]
    comparison(page)
    chart = comparison_chart(page, active_id)
    expect(chart.locator('.composition-row[data-item="api"] .composition-share')).to_have_text("<0.1%")


def test_requested_comparison_order_values_and_cost_graphs(page):
    setup_base(page)
    add_material(page)
    page.locator("#packaging-form").fill("30T / PTP")
    page.once("dialog", lambda dialog: dialog.accept("절감 비교안"))
    page.locator("#clone-scenario").click()
    page.locator('[data-material-field="price"]').fill("400000")
    page.locator('[data-material-field="supplier"]').fill("대체 제조원")
    page.locator("#yield-percent").fill("80")
    page.locator("#packaging-form").fill("100T / 병")
    comparison(page)
    assert page.locator("#comparison-body tr").evaluate_all(
        "rows => rows.map(row => row.dataset.comparisonField)"
    ) == COMPARISON_FIELDS
    expect(comparison_row(page, "name").locator("td").nth(1)).to_have_text("절감 비교안")
    expect(comparison_row(page, "batch_size").locator("td").nth(0)).to_have_text("100,000")
    expect(comparison_row(page, "yield_percent").locator("td").nth(1)).to_have_text("80.0%")
    expect(comparison_row(page, "api_supplier").locator("td").nth(1)).to_contain_text("대체 제조원")
    expect(comparison_row(page, "api_price").locator("td").nth(1)).to_contain_text("400,000.00 원/kg")
    expect(comparison_row(page, "price").locator("td").nth(1)).to_have_text("300.00")
    for field, expected in [
        ("total_cost", "47.50"), ("cost_rate", "15.8%"),
        ("api_batch", "800,000.00"), ("api_unit", "10.00"),
        ("excipient_batch", "0.00"), ("excipient_unit", "0.00"),
        ("packaging_batch", "1,000,000.00"), ("packaging_unit", "12.50"),
        ("labor_batch", "2,000,000.00"), ("labor_unit", "25.00"),
    ]:
        expect(comparison_row(page, field).locator("td").nth(1)).to_have_text(expected)
    expect(page.locator(".comparison-composition")).to_have_count(2)
    for item in project(page)["scenarios"]:
        graph = comparison_chart(page, item["id"])
        expect(graph.locator('[data-chart-part="donut"]')).to_have_count(1)
        expect(graph.locator('[data-chart-part="stack"]')).to_have_count(1)
    assert page.evaluate("""() => {
      const ids = [...document.querySelectorAll('[id]')].map(node => node.id);
      return new Set(ids).size === ids.length;
    }""")


def test_comparison_charts_recalculate_independently_without_changing_original(page):
    setup_base(page)
    add_material(page)
    original = scenario(page)
    page.once("dialog", lambda dialog: dialog.accept("원료 단가 변경"))
    page.locator("#clone-scenario").click()
    clone_id = scenario(page)["id"]
    page.locator('[data-material-field="price"]').fill("500000")
    page.locator("#manual-price").fill("100")
    comparison(page)
    original_graph = comparison_chart(page, original["id"])
    clone_graph = comparison_chart(page, clone_id)
    expect(original_graph.locator('[data-chart-part="rate"]')).to_have_text("16.7%")
    expect(clone_graph.locator('[data-chart-part="rate"]')).to_have_text("40.0%")
    for graph, share, amount in [(original_graph, 40, "20.00 원/T"), (clone_graph, 25, "10.00 원/T")]:
        segment = graph.locator('[data-chart-part="stack"] [data-item="api"]')
        assert float(segment.get_attribute("data-share")) == pytest.approx(share)
        expect(graph.locator('.composition-row[data-item="api"] .composition-amount')).to_have_text(amount)
    page.locator("#tab-button-input").click()
    page.locator("#yield-percent").fill("80")
    results(page)
    expect(page.locator("#donut-total")).to_have_text("50.00 원/T")
    expect(page.locator("#donut-rate")).to_have_text("50.0%")
    comparison(page)
    expect(clone_graph.locator(".donut-total")).to_have_text("50.00 원/T")
    expect(original_graph.locator(".donut-total")).to_have_text("50.00 원/T")
    assert project(page)["scenarios"][0] == original


def test_combination_api_suppliers_and_price_units_remain_readable_in_comparison(page):
    setup_base(page)
    page.locator("#exchange-rate").fill("1400")
    first = add_material(page)
    first.locator('[data-material-field="name"]').fill("복합 API A")
    first.locator('[data-material-field="supplier"]').fill("제조원 A")
    second = add_material(page, amount="10", price="1.2345", unit="usd_g")
    second.locator('[data-material-field="name"]').fill("복합 API B")
    second.locator('[data-material-field="supplier"]').fill("제조원 B · 수입")
    comparison(page)
    suppliers = comparison_row(page, "api_supplier").locator("td")
    prices = comparison_row(page, "api_price").locator("td")
    expect(suppliers).to_contain_text("제조원 A")
    expect(suppliers).to_contain_text("제조원 B · 수입")
    expect(prices).to_contain_text("1,000,000.00 원/kg")
    expect(prices).to_contain_text("1.23 달러/g")
    expect(comparison_row(page, "api_unit").locator("td")).to_have_text("37.28")
    expect(comparison_row(page, "total_cost").locator("td")).to_have_text("67.28")
    for cell in [suppliers, prices]:
        entries = cell.locator(".comparison-api-list > div")
        expect(entries).to_have_count(2)
        for entry in entries.all():
            name = entry.locator("span").nth(0).bounding_box()
            value = entry.locator("span").nth(1).bounding_box()
            assert name["x"] + name["width"] <= value["x"] + 1
            for span in entry.locator("span").all():
                assert span.evaluate("node => node.scrollWidth <= node.clientWidth + 1")


@pytest.mark.parametrize("case", ["zero_price", "zero_cost", "incomplete"])
def test_comparison_chart_handles_unavailable_values_like_result_chart(page, case):
    setup_base(page)
    add_material(page)
    if case == "zero_price":
        page.locator("#manual-price").fill("0")
        expected_rate, expected_cost = "계산 불가", "50.00 원/T"
    elif case == "zero_cost":
        page.locator('[data-material-field="amount"]').fill("0")
        page.locator("#batch-packaging").fill("0")
        page.locator("#batch-labor").fill("0")
        expected_rate, expected_cost = "0.0%", "0.00 원/T"
    else:
        page.locator('[data-material-field="price"]').fill("")
        expected_rate, expected_cost = "미완성", "제조원가 미완성"
    active_id = scenario(page)["id"]
    results(page)
    expect(page.locator("#donut-rate")).to_have_text(expected_rate)
    expect(page.locator("#donut-total")).to_have_text(expected_cost)
    comparison(page)
    chart = comparison_chart(page, active_id)
    expect(chart.locator('[data-chart-part="rate"]')).to_have_text(expected_rate)
    expect(chart.locator(".donut-total")).to_have_text(expected_cost)
    assert not re.search(r"NaN|Infinity|undefined", chart.inner_text())
    if case == "zero_cost":
        expect(chart.locator('[data-chart-part="stack"] [data-item]')).to_have_count(0)
        assert float(chart.locator('[data-chart-part="donut"] [data-item="remainder"]').get_attribute("data-share")) == pytest.approx(100)
    elif case == "zero_price":
        expect(chart.locator('[data-chart-part="donut"] [data-item]')).to_have_count(0)
        expect(chart.locator('[data-chart-part="stack"] [data-item]')).to_have_count(4)
    else:
        expect(chart.locator('[data-chart-part="donut"] [data-item]')).to_have_count(0)
        expect(chart.locator('[data-chart-part="stack"] [data-item]')).to_have_count(0)


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_result_chart_is_larger_and_amounts_stay_close_to_labels(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    results(page)
    card = page.locator("#tab-results .composition-card").bounding_box()
    donut = page.locator("#composition-donut").bounding_box()
    stack = page.locator("#composition-stack").bounding_box()
    if width >= 1024:
        assert donut["width"] >= 220 and donut["height"] >= 220
        assert stack["height"] >= 220
    for row in page.locator("#composition-body .composition-row").all():
        label = row.locator(".composition-label").bounding_box()
        amount = row.locator(".composition-amount").bounding_box()
        assert label["x"] + label["width"] <= amount["x"] + 1
        if width >= 1024:
            # Use the actual text bounds: a narrow CSS gap can still leave text far apart.
            text_gap = row.evaluate("""row => {
              const label = document.createRange();
              label.selectNodeContents(row.querySelector('.composition-label > span:not(.legend-dot)'));
              const amount = document.createRange();
              amount.selectNodeContents(row.querySelector('.composition-amount'));
              return amount.getBoundingClientRect().left - label.getBoundingClientRect().right;
            }""")
            assert 0 <= text_gap <= 72
        for node in [row.locator(".composition-label"), row.locator(".composition-amount")]:
            box = node.bounding_box()
            assert box["x"] >= card["x"] - 1
            assert box["x"] + box["width"] <= card["x"] + card["width"] + 1
            assert node.evaluate("node => node.scrollWidth <= node.clientWidth + 1")


def test_pricing_choice_rows_align_within_each_group(page):
    # Long labels should wrap inside equally sized controls, without shifting radio buttons.
    for group in [".company-group", ".drug-subgroup", ".supply-group", ".count-group"]:
        choices = page.locator(group).first.locator(".choice")
        boxes = [choice.bounding_box() for choice in choices.all()]
        assert len(boxes) >= 2
        assert max(box["x"] for box in boxes) - min(box["x"] for box in boxes) <= 1
        assert max(box["width"] for box in boxes) - min(box["width"] for box in boxes) <= 1
        assert max(box["height"] for box in boxes) - min(box["height"] for box in boxes) <= 1
        radio_boxes = [choice.locator('input[type="radio"]').bounding_box() for choice in choices.all()]
        assert max(box["x"] for box in radio_boxes) - min(box["x"] for box in radio_boxes) <= 1
        for choice in choices.all():
            assert choice.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
