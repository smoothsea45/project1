"""Cost-chart regression checks using the real offline app and calculation data."""

import re
import json

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    project,
    results,
    scenario,
    setup_base,
    open_file,
    select_scenario,
)


ITEMS = ("api", "excipient", "packaging", "labor")


def chart_row(page, item):
    return page.locator(f'#composition-body [data-item="{item}"]')


def donut_share(page, item):
    path = page.locator(f'#composition-donut [data-item="{item}"]')
    return float(path.get_attribute("data-share"))


def stack_share(page, item):
    segment = page.locator(f'#composition-stack [data-item="{item}"]')
    return float(segment.get_attribute("data-share"))


def input_tab(page):
    page.locator("#tab-button-input").click()


def assert_finite_chart(page):
    text = page.locator(".composition-card").inner_text()
    attributes = page.locator(".composition-card").evaluate(
        "node => [...node.querySelectorAll('*')].map(el => "
        "[el.getAttribute('d'), el.getAttribute('style'), "
        "el.getAttribute('data-share')].join(' ')).join(' ')"
    )
    assert not re.search(r"NaN|Infinity|undefined", text + " " + attributes)


def assert_row(page, item, label, percentage, amount):
    row = chart_row(page, item)
    expect(row).to_contain_text(label)
    expect(row.locator(".composition-share")).to_have_text(percentage)
    expect(row.locator(".composition-amount")).to_have_text(f"{float(amount):,.2f} 원/T")


def test_real_example_uses_insurance_basis_for_donut_and_cost_basis_for_stack(page):
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("26.7%")
    expect(page.locator("#donut-total")).to_contain_text("80")
    expect(page.locator("#donut-total")).to_contain_text("원/T")
    for item, insurance_share, cost_share, amount, name in [
        ("api", 40 / 300 * 100, 50, "40", "API"),
        ("excipient", 10 / 300 * 100, 12.5, "10", "부형제"),
        ("packaging", 10 / 300 * 100, 12.5, "10", "포장재비"),
        ("labor", 20 / 300 * 100, 25, "20", "공수비"),
    ]:
        assert donut_share(page, item) == pytest.approx(insurance_share)
        assert stack_share(page, item) == pytest.approx(cost_share)
        assert_row(page, item, name, f"{cost_share:.1f}%", amount)
    assert donut_share(page, "remainder") == pytest.approx(220 / 300 * 100)
    remainder_color = page.locator('#composition-donut [data-item="remainder"]').evaluate(
        "node => getComputedStyle(node).fill"
    )
    channels = [int(value) for value in re.findall(r"\d+", remainder_color)[:3]]
    assert len(channels) == 3 and min(channels) >= 200 and max(channels) - min(channels) <= 20
    expect(page.locator("#raw-material-total")).to_contain_text("50")
    expect(page.locator("#raw-material-share")).to_contain_text("62.5%")
    expect(page.locator("#tab-results .composition-denominator")).to_contain_text("총 제조원가")
    assert_finite_chart(page)


def test_shared_palette_and_vertical_stack_order(page):
    results(page)
    values = page.evaluate("""() => {
      const stack = document.querySelector('#composition-stack');
      return [...stack.querySelectorAll('[data-item]')].map(node => {
        const svg = document.querySelector('#composition-donut [data-item="' + node.dataset.item + '"]');
        return {item: node.dataset.item, background: getComputedStyle(node).backgroundColor,
          fill: getComputedStyle(svg).fill, height: node.getBoundingClientRect().height,
          y: node.getBoundingClientRect().y};
      });
    }""")
    assert [value["item"] for value in values] == list(ITEMS)
    for value in values:
        assert value["background"] == value["fill"]
    assert len({value["background"] for value in values}) == 4
    height = sum(value["height"] for value in values)
    assert height > 0
    assert [value["height"] / height for value in values] == pytest.approx([.5, .125, .125, .25], abs=.001)
    assert [value["y"] for value in values] == sorted(value["y"] for value in values)
    expect(page.locator(".metric-card")).to_have_count(3)


def test_material_edit_updates_both_charts_without_static_data(page):
    page.locator('[data-material-field="amount"]').nth(0).fill("0")
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("20.0%")
    expect(page.locator("#donut-total")).to_contain_text("60")
    assert donut_share(page, "api") == pytest.approx(20 / 300 * 100)
    assert stack_share(page, "api") == pytest.approx(20 / 60 * 100)
    assert_row(page, "api", "API", "33.3%", "20")
    expect(page.locator("#raw-material-total")).to_contain_text("30")
    expect(page.locator("#raw-material-share")).to_contain_text("50.0%")


def test_insurance_price_edit_changes_donut_but_keeps_cost_composition(page):
    results(page)
    original_stack = {item: stack_share(page, item) for item in ITEMS}
    input_tab(page)
    page.locator("#manual-price").fill("200")
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("40.0%")
    assert donut_share(page, "api") == pytest.approx(20)
    assert donut_share(page, "remainder") == pytest.approx(60)
    assert {item: stack_share(page, item) for item in ITEMS} == original_stack


def test_yield_changes_actual_cost_values_not_total_cost_proportions(page):
    page.locator("#yield-percent").fill("80")
    results(page)
    expect(page.locator("#donut-total")).to_contain_text("100")
    expect(page.locator("#donut-rate")).to_have_text("33.3%")
    for item, share, amount, label in [
        ("api", 50, "50", "API"),
        ("excipient", 12.5, "12.5", "부형제"),
        ("packaging", 12.5, "12.5", "포장재비"),
        ("labor", 25, "25", "공수비"),
    ]:
        assert stack_share(page, item) == pytest.approx(share)
        assert_row(page, item, label, f"{share:.1f}%", amount)
    expect(page.locator("#raw-material-total")).to_contain_text("62.5")
    expect(page.locator("#raw-material-share")).to_contain_text("62.5%")


def test_clone_switch_restores_chart_for_original_without_mutating_original(page):
    original = scenario(page)
    page.once("dialog", lambda dialog: dialog.accept("차트 검증 시나리오"))
    page.locator("#clone-scenario").click()
    page.locator('[data-material-field="price"]').nth(0).fill("0")
    results(page)
    expect(page.locator("#donut-total")).to_contain_text("60")
    assert stack_share(page, "api") == pytest.approx(20 / 60 * 100)
    input_tab(page)
    select_scenario(page, original["id"])
    results(page)
    expect(page.locator("#donut-total")).to_contain_text("80")
    assert stack_share(page, "api") == pytest.approx(50)
    assert scenario(page) == original


@pytest.mark.parametrize("price", ["0", "", "-1"])
def test_unusable_insurance_price_has_neutral_donut_and_valid_cost_stack(page, price):
    page.locator("#manual-price").fill(price)
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("계산 불가")
    expect(page.locator("#donut-total")).to_contain_text("80")
    expect(page.locator("#composition-donut [data-item]")).to_have_count(0)
    assert stack_share(page, "api") == pytest.approx(50)
    expect(page.locator("#donut-note")).not_to_be_empty()
    assert_finite_chart(page)


def test_loaded_incomplete_automatic_mode_keeps_cost_stack_and_manual_price_for_return(page):
    payload = project(page)
    payload["scenarios"][0]["pricing_mode"] = "official"
    open_file(page, {"name": "existing-auto.json", "mimeType": "application/json", "buffer": json.dumps(payload, ensure_ascii=False).encode("utf-8")})
    assert scenario(page)["pricing_mode"] == "official"
    assert scenario(page)["manual_price"] == "300"
    results(page)
    expect(page.locator("#result-cost")).to_have_text("80.00")
    expect(page.locator("#result-rate")).to_have_text("계산 불가")
    expect(page.locator("#donut-rate")).to_have_text("계산 불가")
    expect(page.locator("#composition-donut [data-item]")).to_have_count(0)
    assert stack_share(page, "api") == pytest.approx(50)
    assert_finite_chart(page)
    input_tab(page)
    page.locator('[data-field="pricing_mode"][value="manual"]').check()
    expect(page.locator("#manual-price")).to_have_value("300")
    results(page)
    expect(page.locator("#result-price")).to_have_text("300.00")
    expect(page.locator("#donut-rate")).to_have_text("26.7%")
    assert donut_share(page, "api") == pytest.approx(40 / 300 * 100)
    assert stack_share(page, "api") == pytest.approx(50)
    expect(page.locator("#donut-note")).not_to_be_empty()
    assert_finite_chart(page)


def test_zero_manufacturing_cost_shows_zero_rate_and_remainder_without_fake_stack(page):
    setup_base(page)
    page.locator("#batch-packaging").fill("0")
    page.locator("#batch-labor").fill("0")
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("0.0%")
    expect(page.locator("#donut-total")).to_contain_text("0")
    assert donut_share(page, "remainder") == pytest.approx(100)
    expect(page.locator("#composition-stack [data-item]")).to_have_count(0)
    for item in ITEMS:
        expect(chart_row(page, item).locator(".composition-share")).to_have_text("—")
    expect(page.locator("#raw-material-share")).to_contain_text("—")
    assert_finite_chart(page)


def test_zero_cost_and_zero_price_remain_undefined_rate_without_any_chart_segments(page):
    setup_base(page)
    for selector in ("#batch-packaging", "#batch-labor", "#manual-price"):
        page.locator(selector).fill("0")
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("계산 불가")
    expect(page.locator("#donut-total")).to_contain_text("0")
    expect(page.locator("#composition-donut [data-item]")).to_have_count(0)
    expect(page.locator("#composition-stack [data-item]")).to_have_count(0)
    assert_finite_chart(page)


def test_cost_greater_than_insurance_keeps_actual_rate_and_explicit_overflow_basis(page):
    page.locator("#manual-price").fill("40")
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("200.0%")
    expect(page.locator("#donut-total")).to_contain_text("80")
    expect(page.locator('#composition-donut [data-item="remainder"]')).to_have_count(0)
    for item, share in zip(ITEMS, [50, 12.5, 12.5, 25]):
        assert donut_share(page, item) == pytest.approx(share)
        assert stack_share(page, item) == pytest.approx(share)
    expect(page.locator("#donut-note")).to_contain_text("초과")
    expect(page.locator("#donut-note")).to_contain_text("제조원가")
    assert_finite_chart(page)


def test_cost_equal_to_insurance_shows_full_cost_ring_without_remainder(page):
    page.locator("#manual-price").fill("80")
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("100.0%")
    expect(page.locator('#composition-donut [data-item="remainder"]')).to_have_count(0)
    assert sum(donut_share(page, item) for item in ITEMS) == pytest.approx(100)
    assert_finite_chart(page)


@pytest.mark.parametrize("selector,value", [
    ("#manual-price", "1e-1000"),
    ('[data-material-field="price"]', "1e1000"),
])
def test_extreme_valid_decimal_inputs_do_not_create_infinite_chart_geometry(page, selector, value):
    page.locator(selector).first.fill(value)
    results(page)
    expect(page.locator("#donut-note")).to_contain_text("초과")
    assert sum(donut_share(page, item) for item in ITEMS if page.locator(
        f'#composition-donut [data-item="{item}"]'
    ).count()) == pytest.approx(100)
    assert_finite_chart(page)


@pytest.mark.parametrize("selector,value", [
    ('[data-material-field="price"]', ""),
    ("#batch-packaging", "-1"),
    ("#yield-percent", "0"),
])
def test_partial_or_invalid_costs_do_not_draw_complete_composition(page, selector, value):
    page.locator(selector).first.fill(value)
    results(page)
    expect(page.locator("#donut-rate")).to_have_text("미완성")
    expect(page.locator("#donut-total")).to_contain_text("미완성")
    expect(page.locator("#composition-donut [data-item]")).to_have_count(0)
    expect(page.locator("#composition-stack [data-item]")).to_have_count(0)
    for item in ITEMS:
        expect(chart_row(page, item).locator(".composition-share")).to_have_text("—")
    if selector == '[data-material-field="price"]':
        expect(chart_row(page, "api").locator(".composition-amount")).to_contain_text("미완성")
        expect(chart_row(page, "excipient").locator(".composition-amount")).to_contain_text("10")
        expect(chart_row(page, "packaging").locator(".composition-amount")).to_contain_text("10")
        expect(chart_row(page, "labor").locator(".composition-amount")).to_contain_text("20")
    expect(page.locator("#composition-status")).not_to_be_empty()
    assert_finite_chart(page)


def test_rendering_result_charts_does_not_mutate_saved_project_data(page):
    before = project(page)
    for _ in range(2):
        results(page)
        page.locator("#tab-button-comparison").click()
        input_tab(page)
    assert project(page) == before


@pytest.mark.parametrize("width", [390, 1024, 1440])
@pytest.mark.parametrize("large_values", [False, True])
def test_labels_amounts_and_center_fit_chart_at_supported_widths(page, width, large_values):
    page.set_viewport_size({"width": width, "height": 1000})
    if large_values:
        page.locator('[data-material-field="price"]').nth(0).fill("9999999999999999999999999999")
    results(page)
    bounds = page.locator(".composition-card").bounding_box()
    assert bounds is not None
    nodes = page.locator(
        "#composition-body .composition-share, #composition-body .composition-amount, "
        "#donut-rate, #donut-total, #raw-material-total, #raw-material-share"
    )
    for node in nodes.all():
        expect(node).to_be_visible()
        box = node.bounding_box()
        assert box is not None
        assert box["x"] >= bounds["x"] - 1
        assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1
        assert box["y"] >= bounds["y"] - 1
        assert box["y"] + box["height"] <= bounds["y"] + bounds["height"] + 1
        assert node.evaluate("el => el.scrollWidth <= el.clientWidth + 1"), node.inner_text()
    for item in ITEMS:
        row = chart_row(page, item)
        share = row.locator(".composition-share").bounding_box()
        amount = row.locator(".composition-amount").bounding_box()
        assert share["x"] + share["width"] <= amount["x"] + 1
    assert_finite_chart(page)
