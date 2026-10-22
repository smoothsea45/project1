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


def quantities(page, year=1, custom=False):
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
    expect(page.locator("#tab-profit")).to_contain_text("단위: 원")
    assert "백만원" not in page.locator("#tab-profit").inner_text()
    expect(page.locator("#sf-input-card")).to_contain_text("T")


def test_actual_quantity_drives_sales_cost_profit_and_both_real_svg_charts_in_won(page):
    setup_base(page)  # Unit manufacturing cost 30 KRW.
    page.locator("#manual-price").fill("100")
    enable(page, 1)
    quantities(page).fill("1000")
    current_id = scenario(page)["id"]
    row = profit_scenario(page)["rows"][0]
    assert Decimal(row["quantity"]) == 1000
    assert Decimal(row["sales"]) == 100000
    assert Decimal(row["manufacturing_cost"]) == 30000
    assert Decimal(row["profit"]) == 70000
    assert Decimal(row["cost_rate"]) == 30
    analysis(page)
    for kind in ["annual", "cumulative"]:
        expect(mark(page, kind, current_id, 1)).to_have_attribute("data-value", "70000")
        expect(mark(page, kind, current_id, 1)).to_be_visible()
    summary = page.locator(f'#profit-summary-body tr[data-scenario-id="{current_id}"]')
    expect(summary).to_contain_text("1,000")
    expect(summary).to_contain_text("100,000")
    expect(summary).to_contain_text("30,000")
    expect(summary).to_contain_text("70,000")
    assert_clean_analysis(page)
    page.locator("#tab-button-input").click()
    page.locator("#manual-price").fill("200")
    expect(quantities(page)).to_have_value("1,000")
    updated = profit_scenario(page)["rows"][0]
    assert updated["quantity"] == "1000"
    assert updated["sales"] == "200000"
    assert updated["manufacturing_cost"] == "30000"
    assert updated["profit"] == "170000"
    analysis(page)
    for kind in ["annual", "cumulative"]:
        expect(mark(page, kind, current_id, 1)).to_have_attribute("data-value", "170000")


def test_profit_uses_unrounded_unit_cost_and_does_not_modify_existing_price_selection(page):
    setup_base(page)
    add_material(page, amount="20.123456789", price="1000000")
    # Unit cost50.123456789 must be multiplied before display rounding.
    enable(page, 1)
    quantities(page).fill("100")
    before = copy.deepcopy(scenario(page))
    row = profit_scenario(page)["rows"][0]
    assert Decimal(row["manufacturing_cost"]) == Decimal("5012.3456789")
    assert Decimal(row["profit"]) == Decimal("24987.6543211")
    assert Decimal(row["profit"]) != Decimal("24988")
    analysis(page)
    summary = page.locator(f'#profit-summary-body tr[data-scenario-id="{before["id"]}"]')
    expect(summary.locator('[data-profit-field="total_sales"]')).to_have_text("30,000")
    expect(summary.locator('[data-profit-field="total_cost"]')).to_have_text("5,012")
    expect(summary.locator('[data-profit-field="total_profit"]')).to_have_text("24,988")
    expect(mark(page, "annual", before["id"], 1)).to_have_attribute("data-value", "24987.6543211")
    expect(mark(page, "cumulative", before["id"], 1)).to_have_attribute("data-value", "24987.6543211")
    tooltip = mark(page, "annual", before["id"], 1).get_attribute("aria-label")
    assert "5,012 원" in tooltip
    assert "24,988 원" in tooltip
    assert "16.7%" in tooltip
    assert not re.search(r"\d\.\d+ 원", tooltip)
    page.locator(".profit-details-card summary").click()
    row = page.locator('#profit-details-body tr[data-year="1"]')
    expect(row.locator('[data-profit-field="sales"]')).to_have_text("30,000")
    expect(row.locator('[data-profit-field="manufacturing_cost"]')).to_have_text("5,012")
    expect(row.locator('[data-profit-field="profit"]')).to_have_text("24,988")
    assert scenario(page) == before
    assert_clean_analysis(page)


@pytest.mark.parametrize("years", [1, 8, 10])
def test_selected_analysis_period_controls_real_input_and_graph_years(page, years):
    setup_base(page)
    enable(page, years)
    for year in range(1, years + 1):
        quantities(page, year).fill(str(year * 100))
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
    assert Decimal(result["total_quantity"]) == sum(year * 100 for year in expected)
    assert Decimal(result["total_sales"]) == sum(year * 100 * 300 for year in expected)


def test_hiding_feature_or_shortening_period_preserves_hidden_values_and_returns_to_input(page):
    setup_base(page)
    enable(page)
    quantities(page, 1).fill("123456789")
    quantities(page, 8).fill("8888")
    page.locator("#profit-years").select_option("3")
    expect(quantities(page, 8)).to_have_count(0)
    assert project(page)["profit_analysis"]["common_quantities"][7] == "8888"
    page.locator("#profit-years").select_option("8")
    expect(quantities(page, 8)).to_have_value("8,888")
    analysis(page)
    page.locator("#profit-enabled").uncheck()
    expect(page.locator("#tab-input")).to_be_visible()
    expect(page.locator("#sf-input-card")).to_be_hidden()
    expect(page.locator("#tab-button-profit")).to_be_hidden()
    enable(page)
    expect(quantities(page, 1)).to_have_value("123,456,789")
    expect(quantities(page, 8)).to_have_value("8,888")


def test_common_quantities_are_shared_and_custom_blank_falls_back_while_zero_overrides(page):
    setup_base(page)
    first_id = scenario(page)["id"]
    second_id = clone(page, "개별 SF 검토")
    enable(page, 3)
    for year, amount in [(1, "1000"), (2, "2000"), (3, "3000")]:
        quantities(page, year).fill(amount)
    assert [row["quantity"] for row in profit_scenario(page, first_id)["rows"]] == ["1000", "2000", "3000"]
    page.locator("#sf-custom").check()
    quantities(page, 1, custom=True).fill("1500")
    quantities(page, 3, custom=True).fill("0")
    rows = profit_scenario(page, second_id)["rows"]
    assert [row["quantity"] for row in rows] == ["1500", "2000", "0"]
    assert [row["sales_source"] for row in rows] == ["custom", "common", "custom"]
    assert [row["quantity"] for row in profit_scenario(page, first_id)["rows"]] == ["1000", "2000", "3000"]
    select_scenario(page, first_id)
    expect(page.locator("#sf-custom")).not_to_be_checked()
    select_scenario(page, second_id)
    expect(page.locator("#sf-custom")).to_be_checked()
    page.locator("#sf-custom").uncheck()
    assert [row["quantity"] for row in profit_scenario(page)["rows"]] == ["1000", "2000", "3000"]
    page.locator("#sf-custom").check()
    expect(quantities(page, 1, custom=True)).to_have_value("1,500")
    expect(quantities(page, 3, custom=True)).to_have_value("0")


def test_excel_quantity_rows_and_columns_paste_as_real_forecasts_and_reject_overflow_or_matrix(page):
    setup_base(page)
    enable(page, 3)

    def paste(text):
        page.evaluate("text => navigator.clipboard.writeText(text)", text)
        quantities(page).focus()
        page.keyboard.press("Control+V")

    paste("1000\t2000\t3000")
    expect(quantities(page, 1)).to_have_value("1,000")
    expect(quantities(page, 3)).to_have_value("3,000")
    assert [row["profit"] for row in profit_scenario(page)["rows"]] == ["270000", "540000", "810000"]
    paste("4000\n5000\n6000")
    expect(quantities(page, 1)).to_have_value("4,000")
    expect(quantities(page, 3)).to_have_value("6,000")
    before = project(page)
    paste("1\t2\t3\t4")
    assert project(page) == before
    paste("1\t2\n3\t4")
    assert project(page) == before
    analysis(page)
    current_id = scenario(page)["id"]
    expect(mark(page, "annual", current_id, 3)).to_have_attribute("data-value", "1620000")


def test_real_annual_pricing_changes_profit_after_four_years_without_mutating_input_year(page):
    setup_automatic(page, company="innovative", count="ge14")
    condition(page, "company_eligible").check()
    condition(page, "domestic_extension").check()
    page.locator('[data-pricing-year="10"]').click()
    enable(page, 5)
    for year in range(1, 6):
        quantities(page, year).fill("1000")
    before = copy.deepcopy(scenario(page))
    current_id = before["id"]
    rows = profit_scenario(page)["rows"]
    assert [row["price"] for row in rows] == ["600"] * 4 + ["383"]
    assert [row["quantity"] for row in rows] == ["1000"] * 5
    assert [row["manufacturing_cost"] for row in rows] == ["50000"] * 5
    assert [row["sales"] for row in rows] == ["600000"] * 4 + ["383000"]
    assert Decimal(rows[4]["profit"]) < Decimal(rows[3]["profit"])
    analysis(page)
    assert Decimal(mark(page, "annual", current_id, 5).get_attribute("data-value")) < Decimal(
        mark(page, "annual", current_id, 4).get_attribute("data-value")
    )
    assert scenario(page) == before
    page.locator("#tab-button-input").click()
    expect(page.locator('[data-pricing-year="10"]')).to_have_attribute("aria-pressed", "true")


def test_blank_quantities_are_unknown_zero_quantities_are_valid_and_cumulative_never_bridges_gap(page):
    setup_base(page)
    enable(page, 3)
    quantities(page, 1).fill("0")
    quantities(page, 3).fill("1000")
    current_id = scenario(page)["id"]
    result = profit_scenario(page)
    assert result["rows"][0]["profit"] == "0"
    assert result["rows"][1]["quantity"] is None
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
    summary = page.locator(f'#profit-summary-body tr[data-scenario-id="{current_id}"]')
    expect(summary.locator('[data-profit-field="total_profit"]')).to_have_text("—")
    expect(summary).to_contain_text("미완성")
    page.locator("#tab-button-input").click()
    quantities(page, 1).fill("1000")
    analysis(page)
    expect(mark(page, "cumulative", current_id, 1)).to_have_attribute("data-value", "270000")
    expect(mark(page, "cumulative", current_id, 3)).to_have_count(0)
    assert_clean_analysis(page)


@pytest.mark.parametrize("value", ["-1", "not-a-number", "1.5"])
def test_invalid_or_fractional_quantities_are_marked_and_never_rendered_as_real_profit(page, value):
    setup_base(page)
    enable(page, 1)
    quantities(page).fill(value)
    expect(quantities(page)).to_have_attribute("aria-invalid", "true")
    result = profit_scenario(page)
    assert result["rows"][0]["profit"] is None
    assert result["total_profit"] is None
    analysis(page)
    expect(page.locator('#profit-annual-chart svg [data-kind="annual"]')).to_have_count(0)
    expect(page.locator('#profit-cumulative-chart svg [data-kind="cumulative"]')).to_have_count(0)
    assert_clean_analysis(page)


@pytest.mark.parametrize("price,quantity", [("", "1000"), ("0", "1000"), ("0", "0")])
def test_missing_price_is_unavailable_but_valid_zero_price_retains_real_cost_and_loss(page, price, quantity):
    setup_base(page)
    page.locator("#manual-price").fill(price)
    enable(page, 1)
    quantities(page).fill(quantity)
    result = profit_scenario(page)
    row = result["rows"][0]
    if price == "":
        assert row["profit"] is None
        assert result["total_profit"] is None
    else:
        assert row["sales"] == "0"
        assert Decimal(row["manufacturing_cost"]) == Decimal(quantity) * 30
        assert Decimal(row["profit"]) == Decimal(quantity) * -30
        assert row["cost_rate"] is None
        assert result["complete"]
    analysis(page)
    marks = page.locator('#profit-annual-chart svg [data-kind="annual"]')
    if price == "":
        expect(marks).to_have_count(0)
    else:
        expected = str(Decimal(quantity) * -30) if Decimal(quantity) else "0"
        expect(marks).to_have_attribute("data-value", expected)
    assert_clean_analysis(page)


def test_losses_appear_below_zero_and_scenarios_share_a_real_scale(page):
    setup_base(page)
    page.locator("#manual-price").fill("100")
    positive_id = scenario(page)["id"]
    negative_id = clone(page, "적자 검토안")
    page.locator("#manual-price").fill("10")  # Cost30 / price10 =300%; 1000T profit-20000.
    enable(page, 1)
    quantities(page).fill("1000")
    analysis(page)
    positive = mark(page, "annual", positive_id, 1)
    negative = mark(page, "annual", negative_id, 1)
    expect(positive).to_have_attribute("data-value", "70000")
    expect(negative).to_have_attribute("data-value", "-20000")
    positive_geometry = positive.evaluate("node => ({y:+node.getAttribute('y'),height:+node.getAttribute('height')})")
    negative_geometry = negative.evaluate("node => ({y:+node.getAttribute('y'),height:+node.getAttribute('height')})")
    baseline = positive_geometry["y"] + positive_geometry["height"]
    assert abs(negative_geometry["y"] - baseline) < 0.1
    assert negative_geometry["height"] > 0
    assert abs(negative_geometry["height"] / positive_geometry["height"] - 20000 / 70000) < 0.01
    assert_clean_analysis(page)


@pytest.mark.parametrize("price,profits", [("100", [70000, 140000, 210000]), ("10", [-20000, -40000, -60000])])
def test_cumulative_chart_groups_scenarios_by_year_using_signed_running_totals_and_common_scale(page, price, profits):
    setup_base(page)
    page.locator("#manual-price").fill(price)
    first_id = scenario(page)["id"]
    second_id = clone(page, "독립 누적 비교안")
    enable(page, 3)
    for year in range(1, 4):
        quantities(page, year).fill(str(year * 1000))
    analysis(page)
    cumulative = page.locator("#profit-cumulative-chart svg")
    expect(cumulative.locator("circle, polyline")).to_have_count(0)
    expect(page.locator("#profit-cumulative-chart .profit-cumulative-total")).to_have_count(0)
    baseline = float(cumulative.locator("[data-zero-y]").get_attribute("data-zero-y"))
    geometries = {}
    for scenario_id in [first_id, second_id]:
        prefix = Decimal(0)
        previous_x = None
        annual_color = mark(page, "annual", scenario_id, 1).get_attribute("fill")
        for year, contribution in enumerate(profits, start=1):
            bar = mark(page, "cumulative", scenario_id, year)
            assert bar.evaluate("node => node.tagName.toLowerCase()") == "rect"
            prefix += contribution
            expect(bar).to_have_attribute("data-value", str(prefix))
            expect(bar).to_have_attribute("fill", annual_color)
            assert bar.get_attribute("data-stack-start") is None
            assert bar.get_attribute("data-segment-value") is None
            geometry = bar.evaluate("node => Object.fromEntries(['x','y','width','height'].map(key => [key,+node.getAttribute(key)]))")
            assert geometry["height"] > 0
            if prefix > 0:
                assert abs(geometry["y"] + geometry["height"] - baseline) < 0.1
            else:
                assert abs(geometry["y"] - baseline) < 0.1
            if previous_x is not None:
                assert geometry["x"] > previous_x
            previous_x = geometry["x"]
            geometries[(scenario_id, year)] = geometry
    for year in range(1, 4):
        first = geometries[(first_id, year)]
        second = geometries[(second_id, year)]
        assert first["x"] + first["width"] < second["x"]
        assert abs(first["height"] - second["height"]) < 0.1, "Equal cumulative amounts need equal heights"
        assert abs(first["y"] - second["y"]) < 0.1
        if year < 3:
            assert second["x"] + second["width"] < geometries[(first_id, year + 1)]["x"]
    first_height = geometries[(first_id, 1)]["height"]
    assert abs(geometries[(first_id, 2)]["height"] / first_height - 3) < 0.01
    assert abs(geometries[(first_id, 3)]["height"] / first_height - 6) < 0.01
    assert_clean_analysis(page)


def test_cumulative_bars_show_running_net_when_an_annual_loss_reduces_or_crosses_zero(page):
    setup_automatic(page, company="innovative", count="ge14")
    condition(page, "company_eligible").check()
    condition(page, "domestic_extension").check()
    page.locator("#batch-labor").fill("49000000")  # Unit cost520; price600 then383.
    enable(page, 5)
    for year, quantity in enumerate([100, 200, 0, 100, 100], start=1):
        quantities(page, year).fill(str(quantity))
    current_id = scenario(page)["id"]
    assert [row["profit"] for row in profit_scenario(page)["rows"]] == ["8000", "16000", "0", "8000", "-13700"]
    analysis(page)
    values = ["8000", "24000", "24000", "32000", "18300"]
    for year, value in enumerate(values, start=1):
        expect(mark(page, "cumulative", current_id, year)).to_have_attribute("data-value", value)
    zero = float(page.locator('#profit-cumulative-chart [data-zero-y]').get_attribute("data-zero-y"))
    fourth = mark(page, "cumulative", current_id, 4)
    fifth = mark(page, "cumulative", current_id, 5)
    assert float(fifth.get_attribute("y")) < zero, "The net remains positive despite an annual loss"
    assert float(fifth.get_attribute("height")) < float(fourth.get_attribute("height"))
    assert float(mark(page, "cumulative", current_id, 2).get_attribute("height")) == float(
        mark(page, "cumulative", current_id, 3).get_attribute("height")
    )
    expect(mark(page, "annual", current_id, 5)).to_have_attribute("data-value", "-13700")
    page.locator("#tab-button-input").click()
    quantities(page, 5).fill("1000")
    analysis(page)
    expect(mark(page, "annual", current_id, 5)).to_have_attribute("data-value", "-137000")
    expect(mark(page, "cumulative", current_id, 5)).to_have_attribute("data-value", "-105000")
    zero = float(page.locator('#profit-cumulative-chart [data-zero-y]').get_attribute("data-zero-y"))
    assert abs(float(mark(page, "cumulative", current_id, 5).get_attribute("y")) - zero) < 0.1
    assert_clean_analysis(page)


def test_small_negative_cash_rounds_for_display_without_negative_zero_or_changing_true_loss(page):
    setup_base(page)
    page.locator("#batch-packaging").fill("0")
    page.locator("#batch-labor").fill("40000")
    page.locator("#manual-price").fill("0")
    enable(page, 1)
    quantities(page).fill("1")
    current_id = scenario(page)["id"]
    assert profit_scenario(page)["rows"][0]["profit"] == "-0.4"
    analysis(page)
    expect(mark(page, "annual", current_id, 1)).to_have_attribute("data-value", "-0.4")
    expect(mark(page, "cumulative", current_id, 1)).to_have_attribute("data-value", "-0.4")
    summary = page.locator(f'#profit-summary-body tr[data-scenario-id="{current_id}"]')
    expect(summary.locator('[data-profit-field="total_profit"]')).to_have_text("0")
    assert "-0 원" not in mark(page, "annual", current_id, 1).get_attribute("aria-label")
    assert "-0 원" not in mark(page, "cumulative", current_id, 1).get_attribute("aria-label")
    assert_clean_analysis(page)


def test_cloning_custom_sales_is_independent_and_tab_drag_updates_summary_and_graph_order(page):
    setup_base(page)
    enable(page, 1)
    quantities(page).fill("1000")
    page.locator("#sf-custom").check()
    quantities(page, custom=True).fill("1200")
    first_id = scenario(page)["id"]
    second_id = clone(page, "복제 SF 검토안")
    expect(quantities(page, custom=True)).to_have_value("1,200")
    quantities(page, custom=True).fill("2000")
    assert profit_scenario(page, first_id)["rows"][0]["quantity"] == "1200"
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
    quantities(page).fill("1000")
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
    quantities(page, 10).fill("1234567890123456789")
    page.locator("#sf-custom").check()
    quantities(page, 2, custom=True).fill("0")
    page.locator("#profit-enabled").uncheck()
    original = project(page)
    filename = tmp_path / "sf-project.json"
    assert save_file(page, filename) == original
    assert original["schema_version"] == 5
    assert original["profit_analysis"]["common_quantities"][9] == "1234567890123456789"
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    assert project(page) == original
    expect(page.locator("#profit-enabled")).not_to_be_checked()
    open_file(page, filename)
    assert project(page) == original
    enable(page, 10)
    expect(quantities(page, 10)).to_have_value("1,234,567,890,123,456,789")
    expect(page.locator("#sf-custom")).to_be_checked()
    expect(quantities(page, 2, custom=True)).to_have_value("0")


def test_schema_two_project_opens_with_sf_off_without_changing_original_inputs(page, tmp_path):
    setup_base(page)
    add_material(page, amount="20.123456", price="987654.321")
    legacy = save_file(page, tmp_path / "before-migration.json")
    legacy["product"] = legacy["scenarios"][0]["product"]
    for item in legacy["scenarios"]:
        item.pop("product")
    legacy["schema_version"] = 2
    legacy.pop("profit_analysis")
    for item in legacy["scenarios"]:
        item.pop("sales_forecast")
    filename = tmp_path / "old-v2.json"
    filename.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    open_file(page, filename)
    migrated = project(page)
    assert migrated["schema_version"] == 5
    assert migrated["profit_analysis"] == {
        "enabled": False,
        "years": 8,
        "common_quantities": [None] * 10,
        "legacy_amount_forecast": None,
    }
    for old, new in zip(legacy["scenarios"], migrated["scenarios"]):
        assert {key: value for key, value in new.items() if key not in {"sales_forecast", "product"}} == old
    expect(page.locator("#profit-enabled")).not_to_be_checked()
    expect(page.locator("#tab-button-profit")).to_be_hidden()
    expect(page.locator('[data-material-field="amount"]')).to_have_value("20.123456")


def test_old_amount_forecast_is_archived_without_legacy_banner_or_reinterpreting_as_quantity(page, tmp_path):
    setup_base(page)
    legacy = save_file(page, tmp_path / "before-old-sf.json")
    legacy["product"] = legacy["scenarios"][0]["product"]
    for item in legacy["scenarios"]:
        item.pop("product")
    legacy["schema_version"] = 3
    old_common = ["1000", None, "2000"] + [None] * 7
    old_custom = ["1500", None, "0"] + [None] * 7
    legacy["profit_analysis"] = {"enabled": True, "years": 3, "common_sales": old_common}
    for item in legacy["scenarios"]:
        item["sales_forecast"] = {"use_custom": True, "sales": old_custom}
    filename = tmp_path / "cash-based-v3.json"
    filename.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    open_file(page, filename)
    expect(page.locator("#profit-enabled")).to_be_checked()
    expect(page.locator("#profit-years")).to_have_value("3")
    expect(page.locator("#sf-legacy-notice")).to_have_count(0)
    for year in range(1, 4):
        expect(quantities(page, year)).to_have_value("")
        expect(quantities(page, year, custom=True)).to_have_value("")
    migrated = project(page)
    assert migrated["schema_version"] == 5
    assert migrated["profit_analysis"]["common_quantities"] == [None] * 10
    archived = migrated["profit_analysis"]["legacy_amount_forecast"]
    assert archived == {
        "unit": "million_krw",
        "common_sales": old_common,
        "scenarios": [
            {"scenario_id": item["id"], "use_custom": True, "sales": old_custom}
            for item in legacy["scenarios"]
        ],
    }
    assert profit_scenario(page)["rows"][0]["quantity"] is None
    assert profit_scenario(page)["total_profit"] is None
    saved = save_file(page, tmp_path / "archived-v4.json")
    assert saved["profit_analysis"]["legacy_amount_forecast"] == archived
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    expect(page.locator("#sf-legacy-notice")).to_have_count(0)
    assert project(page)["profit_analysis"]["legacy_amount_forecast"] == archived


@pytest.mark.parametrize("width", [390, 1440])
def test_optional_inputs_and_profit_charts_remain_within_mobile_and_desktop_page(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    setup_base(page)
    for index in range(3):
        clone(page, f"판매 예측 비교 시나리오 {index + 2}")
    enable(page, 10)
    for year in range(1, 11):
        quantities(page, year).fill(str(year * 1000000))
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    analysis(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    for host in ["annual", "cumulative"]:
        chart = page.locator(f"#profit-{host}-chart")
        expect(chart.locator("svg")).to_be_visible()
        expect(chart.locator("svg")).to_have_attribute("role", "img")
        assert "원" in chart.locator("svg").get_attribute("aria-label")
        bounds = chart.locator("svg").bounding_box()
        labels = chart.locator("svg text").all()
        boxes = []
        for label in labels:
            box = label.bounding_box()
            assert box["x"] >= bounds["x"] - 1
            assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1
            assert box["y"] >= bounds["y"] - 1
            assert box["y"] + box["height"] <= bounds["y"] + bounds["height"] + 1
            boxes.append(box)
        for index, first in enumerate(boxes):
            for second in boxes[index + 1:]:
                horizontal = min(first["x"] + first["width"], second["x"] + second["width"]) - max(first["x"], second["x"])
                vertical = min(first["y"] + first["height"], second["y"] + second["height"]) - max(first["y"], second["y"])
                assert horizontal <= 0.5 or vertical <= 0.5, "Profit axis labels overlap"
    assert_clean_analysis(page)
