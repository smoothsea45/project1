"""Exercise optional, offline SF/profit analysis against the real desktop UI."""

import copy
from decimal import Decimal
import json
import re

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    add_material,
    open_file,
    project,
    save_file,
    scenario,
    select_scenario,
    setup_base,
)
from web.tests.test_pricing import condition, setup_automatic
from web.tests.test_scenario_reorder import native_drag
from web.tests.test_tabs_print import clone


def sales(page, year=1, custom=False):
    scope = "custom" if custom else "common"
    return page.locator(f'.sf-sales-input[data-sf-scope="{scope}"][data-sf-year="{year}"]')


def enable(page, years=8):
    page.locator("#profit-enabled").check()
    page.locator("#profit-years").select_option(str(years))


def analysis(page):
    page.locator("#tab-button-profit").click()
    expect(page.locator("#tab-profit")).to_be_visible()


def profit_result(page):
    return page.evaluate("JSON.parse(JSON.stringify(PharmaProfit.calculate(PharmaCostApp.getProject())))")


def profit_scenario(page, scenario_id=None):
    scenario_id = scenario_id or project(page)["active_scenario_id"]
    return next(item for item in profit_result(page)["scenarios"] if item["id"] == scenario_id)


def mark(page, kind, scenario_id, year):
    host = "annual" if kind == "annual" else "cumulative"
    return page.locator(
        f'#profit-{host}-chart svg [data-kind="{kind}"]'
        f'[data-scenario-id="{scenario_id}"][data-year="{year}"]'
    )


def assert_clean_analysis(page):
    text = page.locator("#tab-profit").inner_text()
    assert not re.search(r"NaN|Infinity|undefined", text)
    assert page.locator('#tab-profit [d*="NaN"], #tab-profit [height*="NaN"], #tab-profit [cy*="NaN"]').count() == 0


def test_feature_starts_off_and_checkbox_adds_only_the_optional_fourth_tab(page):
    setup_base(page)
    expect(page.locator("#profit-enabled")).not_to_be_checked()
    expect(page.locator("#sf-input-card")).to_be_hidden()
    expect(page.locator("#tab-button-profit")).to_be_hidden()
    assert page.locator('.page-tabs [role="tab"]:visible').count() == 3
    before = copy.deepcopy(scenario(page))
    page.locator("#profit-enabled").focus()
    page.keyboard.press("Space")
    expect(page.locator("#sf-input-card")).to_be_visible()
    expect(page.locator("#profit-years")).to_have_value("8")
    assert page.locator('.page-tabs [role="tab"]:visible').evaluate_all(
        "nodes => nodes.map(node => node.id)"
    ) == ["tab-button-input", "tab-button-results", "tab-button-comparison", "tab-button-profit"]
    expect(page.locator('.sf-sales-input[data-sf-scope="common"]')).to_have_count(8)
    assert scenario(page) == before
    analysis(page)
    expect(page.locator("#tab-profit")).to_contain_text("제조원가")
    expect(page.locator("#tab-profit")).to_contain_text("백만원")


def test_actual_sales_drives_cost_profit_and_both_real_svg_charts(page):
    setup_base(page)  # Unit manufacturing cost 30 KRW.
    page.locator("#manual-price").fill("100")
    enable(page, 1)
    sales(page).fill("1000")
    current_id = scenario(page)["id"]
    row = profit_scenario(page)["rows"][0]
    assert Decimal(row["sales"]) == 1000
    assert Decimal(row["manufacturing_cost"]) == 300
    assert Decimal(row["profit"]) == 700
    assert Decimal(row["cost_rate"]) == 30
    analysis(page)
    for kind in ["annual", "cumulative"]:
        expect(mark(page, kind, current_id, 1)).to_have_attribute("data-value", "700")
        expect(mark(page, kind, current_id, 1)).to_be_visible()
    summary = page.locator(f'#profit-summary-body tr[data-scenario-id="{current_id}"]')
    expect(summary).to_contain_text("1,000")
    expect(summary).to_contain_text("300")
    expect(summary).to_contain_text("700")
    assert_clean_analysis(page)


def test_profit_uses_unrounded_cost_rate_and_does_not_modify_existing_price_selection(page):
    setup_base(page)
    add_material(page)  # Unit cost 50, price300: exact ratio1/6, not displayed16.7%.
    enable(page, 1)
    sales(page).fill("100")
    before = copy.deepcopy(scenario(page))
    row = profit_scenario(page)["rows"][0]
    assert abs(Decimal(row["profit"]) - Decimal(250) / Decimal(3)) < Decimal("1e-20")
    assert Decimal(row["profit"]) != Decimal("83.3")
    analysis(page)
    assert scenario(page) == before
    assert_clean_analysis(page)


@pytest.mark.parametrize("years", [1, 8, 10])
def test_selected_analysis_period_controls_real_input_and_graph_years(page, years):
    setup_base(page)
    enable(page, years)
    for year in range(1, years + 1):
        sales(page, year).fill(str(year * 100))
    current_id = scenario(page)["id"]
    analysis(page)
    expected = list(range(1, years + 1))
    for host, kind in [("annual", "annual"), ("cumulative", "cumulative")]:
        actual = page.locator(
            f'#profit-{host}-chart svg [data-kind="{kind}"][data-scenario-id="{current_id}"]'
        ).evaluate_all("nodes => nodes.map(node => Number(node.dataset.year))")
        assert actual == expected
    result = profit_scenario(page)
    assert len(result["rows"]) == years
    assert result["complete"]
    assert Decimal(result["total_sales"]) == sum(year * 100 for year in expected)


def test_hiding_feature_or_shortening_period_preserves_hidden_values_and_returns_to_input(page):
    setup_base(page)
    enable(page)
    sales(page, 1).fill("1234.56789")
    sales(page, 8).fill("8888")
    page.locator("#profit-years").select_option("3")
    expect(sales(page, 8)).to_have_count(0)
    assert project(page)["profit_analysis"]["common_sales"][7] == "8888"
    page.locator("#profit-years").select_option("8")
    expect(sales(page, 8)).to_have_value("8,888")
    analysis(page)
    page.locator("#profit-enabled").uncheck()
    expect(page.locator("#tab-input")).to_be_visible()
    expect(page.locator("#sf-input-card")).to_be_hidden()
    expect(page.locator("#tab-button-profit")).to_be_hidden()
    enable(page)
    expect(sales(page, 1)).to_have_value("1,234.56789")
    expect(sales(page, 8)).to_have_value("8,888")


def test_common_sales_are_shared_and_custom_blank_falls_back_while_zero_overrides(page):
    setup_base(page)
    first_id = scenario(page)["id"]
    second_id = clone(page, "개별 SF 검토")
    enable(page, 3)
    for year, amount in [(1, "1000"), (2, "2000"), (3, "3000")]:
        sales(page, year).fill(amount)
    assert [row["sales"] for row in profit_scenario(page, first_id)["rows"]] == ["1000", "2000", "3000"]
    page.locator("#sf-custom").check()
    sales(page, 1, custom=True).fill("1500")
    sales(page, 3, custom=True).fill("0")
    rows = profit_scenario(page, second_id)["rows"]
    assert [row["sales"] for row in rows] == ["1500", "2000", "0"]
    assert [row["sales_source"] for row in rows] == ["custom", "common", "custom"]
    assert [row["sales"] for row in profit_scenario(page, first_id)["rows"]] == ["1000", "2000", "3000"]
    select_scenario(page, first_id)
    expect(page.locator("#sf-custom")).not_to_be_checked()
    select_scenario(page, second_id)
    expect(page.locator("#sf-custom")).to_be_checked()
    page.locator("#sf-custom").uncheck()
    assert [row["sales"] for row in profit_scenario(page)["rows"]] == ["1000", "2000", "3000"]
    page.locator("#sf-custom").check()
    expect(sales(page, 1, custom=True)).to_have_value("1,500")
    expect(sales(page, 3, custom=True)).to_have_value("0")


def test_excel_sales_rows_and_columns_paste_as_real_forecasts_and_reject_overflow_or_matrix(page):
    setup_base(page)
    enable(page, 3)

    def paste(text):
        page.evaluate("text => navigator.clipboard.writeText(text)", text)
        sales(page).focus()
        page.keyboard.press("Control+V")

    paste("1000\t2000\t3000")
    expect(sales(page, 1)).to_have_value("1,000")
    expect(sales(page, 3)).to_have_value("3,000")
    assert [row["profit"] for row in profit_scenario(page)["rows"]] == ["900", "1800", "2700"]
    paste("4000\n5000\n6000")
    expect(sales(page, 1)).to_have_value("4,000")
    expect(sales(page, 3)).to_have_value("6,000")
    before = project(page)
    paste("1\t2\t3\t4")
    assert project(page) == before
    paste("1\t2\n3\t4")
    assert project(page) == before
    analysis(page)
    current_id = scenario(page)["id"]
    expect(mark(page, "annual", current_id, 3)).to_have_attribute("data-value", "5400")


def test_real_annual_pricing_changes_profit_after_four_years_without_mutating_input_year(page):
    setup_automatic(page, company="innovative", count="ge14")
    condition(page, "company_eligible").check()
    condition(page, "domestic_extension").check()
    page.locator('[data-pricing-year="10"]').click()
    enable(page, 5)
    for year in range(1, 6):
        sales(page, year).fill("1000")
    before = copy.deepcopy(scenario(page))
    current_id = before["id"]
    rows = profit_scenario(page)["rows"]
    assert [row["price"] for row in rows] == ["600"] * 4 + ["383"]
    assert Decimal(rows[4]["profit"]) < Decimal(rows[3]["profit"])
    analysis(page)
    assert Decimal(mark(page, "annual", current_id, 5).get_attribute("data-value")) < Decimal(
        mark(page, "annual", current_id, 4).get_attribute("data-value")
    )
    assert scenario(page) == before
    page.locator("#tab-button-input").click()
    expect(page.locator('[data-pricing-year="10"]')).to_have_attribute("aria-pressed", "true")


def test_blank_sales_are_unknown_zero_sales_are_valid_and_cumulative_never_bridges_gap(page):
    setup_base(page)
    enable(page, 3)
    sales(page, 1).fill("0")
    sales(page, 3).fill("1000")
    current_id = scenario(page)["id"]
    result = profit_scenario(page)
    assert result["rows"][0]["profit"] == "0"
    assert result["rows"][1]["sales"] is None
    assert result["rows"][1]["profit"] is None
    assert result["rows"][2]["profit"] is not None
    assert result["rows"][2]["cumulative_profit"] is None
    assert result["total_profit"] is None
    assert not result["complete"]
    analysis(page)
    expect(mark(page, "annual", current_id, 1)).to_have_attribute("data-value", "0")
    expect(mark(page, "annual", current_id, 2)).to_have_count(0)
    expect(mark(page, "annual", current_id, 3)).to_have_count(1)
    expect(mark(page, "cumulative", current_id, 1)).to_have_count(1)
    expect(mark(page, "cumulative", current_id, 2)).to_have_count(0)
    expect(mark(page, "cumulative", current_id, 3)).to_have_count(0)
    assert_clean_analysis(page)


@pytest.mark.parametrize("value", ["-1", "not-a-number"])
def test_invalid_sales_are_marked_and_never_rendered_as_real_profit(page, value):
    setup_base(page)
    enable(page, 1)
    sales(page).fill(value)
    expect(sales(page)).to_have_attribute("aria-invalid", "true")
    result = profit_scenario(page)
    assert result["rows"][0]["profit"] is None
    assert result["total_profit"] is None
    analysis(page)
    expect(page.locator('#profit-annual-chart svg [data-kind="annual"]')).to_have_count(0)
    expect(page.locator('#profit-cumulative-chart svg [data-kind="cumulative"]')).to_have_count(0)
    assert_clean_analysis(page)


@pytest.mark.parametrize("price", ["0", ""])
def test_missing_or_zero_price_is_unavailable_without_nan_or_assumed_full_profit(page, price):
    setup_base(page)
    page.locator("#manual-price").fill(price)
    enable(page, 1)
    sales(page).fill("1000")
    result = profit_scenario(page)
    assert result["rows"][0]["profit"] is None
    assert result["total_profit"] is None
    analysis(page)
    expect(page.locator('#profit-annual-chart svg [data-kind="annual"]')).to_have_count(0)
    assert_clean_analysis(page)


def test_losses_appear_below_zero_and_scenarios_share_a_real_scale(page):
    setup_base(page)
    page.locator("#manual-price").fill("100")
    positive_id = scenario(page)["id"]
    negative_id = clone(page, "적자 검토안")
    page.locator("#manual-price").fill("10")  # Cost30 / price10 =300%; profit-2000.
    enable(page, 1)
    sales(page).fill("1000")
    analysis(page)
    positive = mark(page, "annual", positive_id, 1)
    negative = mark(page, "annual", negative_id, 1)
    expect(positive).to_have_attribute("data-value", "700")
    expect(negative).to_have_attribute("data-value", "-2000")
    positive_geometry = positive.evaluate("node => ({y:+node.getAttribute('y'),height:+node.getAttribute('height')})")
    negative_geometry = negative.evaluate("node => ({y:+node.getAttribute('y'),height:+node.getAttribute('height')})")
    baseline = positive_geometry["y"] + positive_geometry["height"]
    assert abs(negative_geometry["y"] - baseline) < 0.1
    assert negative_geometry["height"] > 0
    assert abs(negative_geometry["height"] / positive_geometry["height"] - 2000 / 700) < 0.01
    assert_clean_analysis(page)


def test_cloning_custom_sales_is_independent_and_tab_drag_updates_summary_and_graph_order(page):
    setup_base(page)
    enable(page, 1)
    sales(page).fill("1000")
    page.locator("#sf-custom").check()
    sales(page, custom=True).fill("1200")
    first_id = scenario(page)["id"]
    second_id = clone(page, "복제 SF 검토안")
    expect(sales(page, custom=True)).to_have_value("1,200")
    sales(page, custom=True).fill("2000")
    assert profit_scenario(page, first_id)["rows"][0]["sales"] == "1200"
    analysis(page)
    colors = {
        key: mark(page, "annual", key, 1).get_attribute("fill")
        for key in [first_id, second_id]
    }
    native_drag(page, second_id, first_id)
    assert page.locator('#profit-summary-body tr[data-scenario-id]').evaluate_all(
        "nodes => nodes.map(node => node.dataset.scenarioId)"
    ) == [second_id, first_id]
    assert page.locator('#profit-annual-chart svg [data-kind="annual"][data-year="1"]').evaluate_all(
        "nodes => nodes.map(node => node.dataset.scenarioId)"
    ) == [second_id, first_id]
    assert {key: mark(page, "annual", key, 1).get_attribute("fill") for key in colors} == colors
    assert profit_result(page)["baseline_id"] == second_id


def test_deleting_and_replacing_a_scenario_keeps_four_distinct_colors_and_reorder_preserves_them(page):
    setup_base(page)
    enable(page, 1)
    sales(page).fill("1000")
    ids = [scenario(page)["id"]]
    for number in range(2, 5):
        ids.append(clone(page, f"색상 비교 {number}안"))
    analysis(page)

    def colors(keys):
        return {key: mark(page, "annual", key, 1).get_attribute("fill") for key in keys}

    original = colors(ids)
    assert len(set(original.values())) == 4
    select_scenario(page, ids[1])
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-scenario").click()
    replacement_id = clone(page, "삭제 후 추가한 검토안")
    analysis(page)
    active_ids = [ids[0], ids[2], ids[3], replacement_id]
    updated = colors(active_ids)
    assert len(set(updated.values())) == 4
    for remaining_id in [ids[0], ids[2], ids[3]]:
        assert updated[remaining_id] == original[remaining_id]
    native_drag(page, replacement_id, ids[0])
    assert colors(active_ids) == updated
    assert page.locator('#profit-summary-body tr[data-scenario-id]').evaluate_all(
        "nodes => nodes.map(node => node.dataset.scenarioId)"
    ) == [replacement_id, ids[0], ids[2], ids[3]]


def test_json_save_open_and_browser_draft_retain_disabled_sf_settings_and_exact_input(page, tmp_path):
    setup_base(page)
    enable(page, 10)
    sales(page, 10).fill("1234567.890123456789")
    page.locator("#sf-custom").check()
    sales(page, 2, custom=True).fill("0")
    page.locator("#profit-enabled").uncheck()
    original = project(page)
    filename = tmp_path / "sf-project.json"
    assert save_file(page, filename) == original
    assert original["schema_version"] == 3
    assert original["profit_analysis"]["common_sales"][9] == "1234567.890123456789"
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    assert project(page) == original
    expect(page.locator("#profit-enabled")).not_to_be_checked()
    open_file(page, filename)
    assert project(page) == original
    enable(page, 10)
    expect(sales(page, 10)).to_have_value("1,234,567.890123456789")
    expect(page.locator("#sf-custom")).to_be_checked()
    expect(sales(page, 2, custom=True)).to_have_value("0")


def test_schema_two_project_opens_with_sf_off_without_changing_original_inputs(page, tmp_path):
    setup_base(page)
    add_material(page, amount="20.123456", price="987654.321")
    legacy = save_file(page, tmp_path / "before-migration.json")
    legacy["schema_version"] = 2
    legacy.pop("profit_analysis")
    for item in legacy["scenarios"]:
        item.pop("sales_forecast")
    filename = tmp_path / "old-v2.json"
    filename.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    open_file(page, filename)
    migrated = project(page)
    assert migrated["schema_version"] == 3
    assert migrated["profit_analysis"] == {"enabled": False, "years": 8, "common_sales": [None] * 10}
    for old, new in zip(legacy["scenarios"], migrated["scenarios"]):
        assert {key: value for key, value in new.items() if key != "sales_forecast"} == old
    expect(page.locator("#profit-enabled")).not_to_be_checked()
    expect(page.locator("#tab-button-profit")).to_be_hidden()
    expect(page.locator('[data-material-field="amount"]')).to_have_value("20.123456")


@pytest.mark.parametrize("width", [390, 1440])
def test_optional_inputs_and_profit_charts_remain_within_mobile_and_desktop_page(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    setup_base(page)
    for index in range(3):
        clone(page, f"판매 예측 비교 시나리오 {index + 2}")
    enable(page, 10)
    for year in range(1, 11):
        sales(page, year).fill(str(year * 1000))
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    analysis(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    for host in ["annual", "cumulative"]:
        chart = page.locator(f"#profit-{host}-chart")
        expect(chart.locator("svg")).to_be_visible()
        expect(chart.locator("svg")).to_have_attribute("role", "img")
        assert chart.locator("svg").get_attribute("aria-label")
    assert_clean_analysis(page)
