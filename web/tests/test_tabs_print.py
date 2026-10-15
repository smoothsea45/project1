"""Scenario tab, paired cost-column, compact result and print regressions."""

import copy
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    add_material,
    comparison,
    open_file,
    project,
    results,
    scenario,
    select_scenario,
    setup_base,
)
from web.tests.test_presentation import COMPARISON_FIELDS, comparison_row, cost_cell


def clone(page, name):
    page.once("dialog", lambda dialog: dialog.accept(name))
    page.locator("#clone-scenario").click()
    return scenario(page)["id"]


def four_scenarios(page, detailed_api=False):
    setup_base(page)
    first = add_material(page)
    if detailed_api:
        first.locator('[data-material-field="name"]').fill("보노프라잔 푸마레이트")
        first.locator('[data-material-field="supplier"]').fill("제조원 A / 검토 공급처")
        second = add_material(page, amount="10", price="500000")
        second.locator('[data-material-field="name"]').fill("아목시실린 수화물")
        second.locator('[data-material-field="supplier"]').fill("제조원 B / 수입 공급처")
    names = ["기본 시나리오", "PTP 비교안", "병 포장 비교안", "최종 검토안"]
    ids = [scenario(page)["id"]]
    page.locator("#packaging-form").fill("30T / PTP")
    page.locator("#manual-price").fill("100")
    for index in range(1, 4):
        ids.append(clone(page, names[index]))
        page.locator("#manual-price").fill(str((index + 1) * 100))
        page.locator('[data-material-field="price"]').first.fill(str((index + 1) * 1000000))
        page.locator("#packaging-form").fill(f"{30 * (index + 1)}T / 포장")
    return ids


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_result_layout_stacks_numbers_and_emphasizes_rate_only(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    results(page)
    cards = page.locator("#tab-results .metric-card")
    expect(cards).to_have_count(3)
    assert cards.locator("strong").evaluate_all("nodes => nodes.map(node => node.id)") == [
        "result-price", "result-cost", "result-rate",
    ]
    featured = page.locator("#tab-results .metric-card.featured")
    expect(featured).to_have_count(1)
    expect(featured.locator("#result-rate")).to_have_count(1)
    boxes = [card.bounding_box() for card in cards.all()]
    assert boxes[0]["y"] + boxes[0]["height"] <= boxes[1]["y"] + 1
    assert boxes[1]["y"] + boxes[1]["height"] <= boxes[2]["y"] + 1
    graph = page.locator("#tab-results .composition-card").bounding_box()
    assert page.locator(".results-layout > div").evaluate_all(
        "nodes => nodes.map(node => node.className)"
    ) == ["results-detail-grid", "metric-grid"]
    if width >= 1024:
        assert graph["x"] + graph["width"] < boxes[0]["x"]
        assert abs(boxes[0]["y"] - graph["y"]) <= 1
        assert abs(boxes[0]["x"] - boxes[2]["x"]) <= 1
    else:
        assert graph["y"] + graph["height"] <= boxes[0]["y"] + 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def test_scenario_selection_and_work_tabs_have_distinct_colors_and_selected_state(page):
    selected_id = page.locator('#scenario-tabs [aria-selected="true"]').get_attribute("data-scenario-id")
    other_id = page.locator('#scenario-tabs [aria-selected="false"]').first.get_attribute("data-scenario-id")
    scenario_selected = page.locator(f'#scenario-tabs [data-scenario-id="{selected_id}"]')
    scenario_unselected = page.locator(f'#scenario-tabs [data-scenario-id="{other_id}"]')
    work_selected = page.locator('.page-tabs [aria-selected="true"]')
    work_unselected = page.locator('.page-tabs [aria-selected="false"]').first

    def colors(locator):
        return locator.evaluate("node => { const s = getComputedStyle(node); return [s.backgroundColor, s.color, s.borderColor]; }")

    assert colors(scenario_selected) != colors(work_selected)
    assert colors(scenario_unselected) != colors(work_unselected)
    assert colors(scenario_selected) != colors(scenario_unselected)
    assert colors(work_selected) != colors(work_unselected)
    scenario_unselected.click()
    expect(scenario_unselected).to_have_attribute("aria-selected", "true")
    expect(scenario_selected).to_have_attribute("aria-selected", "false")
    assert colors(scenario_unselected) != colors(work_selected)


def test_scenario_tabs_select_independent_values_and_support_keyboard(page):
    setup_base(page)
    add_material(page)
    original = scenario(page)
    second = clone(page, "두 번째 안")
    page.locator("#manual-price").fill("200")
    third = clone(page, "세 번째 안")
    page.locator("#manual-price").fill("100")
    expect(page.locator("#scenario-select")).to_have_count(0)
    tabs = page.locator('#scenario-tabs [role="tab"]')
    expect(tabs).to_have_count(3)
    select_scenario(page, original["id"])
    expect(page.locator("#manual-price")).to_have_value("300")
    selected = page.locator('#scenario-tabs [aria-selected="true"]')
    expect(selected).to_have_count(1)
    expect(selected).to_have_attribute("data-scenario-id", original["id"])
    expect(selected).to_have_attribute("tabindex", "0")
    expect(page.locator('#scenario-tabs [aria-selected="false"][tabindex="-1"]')).to_have_count(2)
    selected.focus()
    for key, expected_id, amount in [
        ("ArrowRight", second, "200"),
        ("End", third, "100"),
        ("Home", original["id"], "300"),
        ("ArrowLeft", third, "100"),
    ]:
        page.keyboard.press(key)
        expected = page.locator(f'#scenario-tabs [data-scenario-id="{expected_id}"]')
        expect(expected).to_be_focused()
        expect(expected).to_have_attribute("aria-selected", "true")
        expect(page.locator("#manual-price")).to_have_value(amount)
        assert project(page)["active_scenario_id"] == expected_id
    assert project(page)["scenarios"][0] == original


def test_four_scenario_limit_disables_clone_and_deleting_allows_new_clone(page):
    ids = four_scenarios(page)
    expect(page.locator('#scenario-tabs [role="tab"]')).to_have_count(4)
    expect(page.locator("#clone-scenario")).to_be_disabled()
    assert len(project(page)["scenarios"]) == 4
    original = copy.deepcopy(project(page)["scenarios"][0])
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-scenario").click()
    expect(page.locator('#scenario-tabs [role="tab"]')).to_have_count(3)
    expect(page.locator("#clone-scenario")).to_be_enabled()
    new_id = clone(page, "다시 추가한 안")
    assert new_id not in ids
    assert project(page)["scenarios"][0] == original
    assert len(project(page)["scenarios"]) == 4


def test_over_limit_json_reports_error_and_preserves_current_project_and_draft(page):
    four_scenarios(page)
    original = project(page)
    draft = page.evaluate("localStorage.getItem('pharma-cost-web-draft-v1')")
    payload = copy.deepcopy(original)
    fifth = copy.deepcopy(payload["scenarios"][0])
    fifth["id"] = "fifth-file-scenario"
    fifth["name"] = "초과한 비교안"
    payload["scenarios"].append(fifth)
    open_file(page, {"name": "five-scenarios.json", "mimeType": "application/json", "buffer": json.dumps(payload, ensure_ascii=False).encode("utf-8")})
    expect(page.locator("#toast")).to_contain_text("4개")
    expect(page.locator("#toast")).to_contain_text("파일을 열 수 없습니다")
    expect(page.locator("dialog.project-dialog")).to_have_count(0)
    assert project(page) == original
    assert page.evaluate("localStorage.getItem('pharma-cost-web-draft-v1')") == draft


def test_over_limit_browser_draft_is_not_overwritten_after_rejected_restore(page):
    four_scenarios(page)
    payload = project(page)
    fifth = copy.deepcopy(payload["scenarios"][0])
    fifth["id"] = "fifth-draft-scenario"
    fifth["name"] = "복원하지 못한 원본"
    payload["scenarios"].append(fifth)
    original_draft = json.dumps(payload, ensure_ascii=False)
    page.evaluate("text => localStorage.setItem('pharma-cost-web-draft-v1', text)", original_draft)
    page.once("dialog", lambda dialog: dialog.accept())
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    expect(page.locator("#toast")).to_contain_text("4개")
    assert len(project(page)["scenarios"]) <= 4
    assert page.evaluate("localStorage.getItem('pharma-cost-web-draft-v1')") == original_draft
    page.locator("#product-name").fill("새 화면에서 수정")
    results(page)
    assert page.evaluate("localStorage.getItem('pharma-cost-web-draft-v1')") == original_draft


def test_comparison_has_two_cost_columns_per_scenario_with_actual_independent_values(page):
    ids = four_scenarios(page)
    comparison(page)
    assert page.locator("#comparison-body tr").evaluate_all(
        "rows => rows.map(row => row.dataset.comparisonField)"
    ) == COMPARISON_FIELDS
    headers = page.locator("#comparison-head tr").first.locator("th")
    expect(page.locator("#comparison-head tr")).to_have_count(1)
    expect(page.locator("#comparison-head")).not_to_contain_text("배치당")
    expect(page.locator("#comparison-head")).not_to_contain_text("1T당")
    expect(headers).to_have_count(5)
    for heading in headers.all()[1:]:
        expect(heading).to_have_attribute("colspan", "2")
    cost_header = comparison_row(page, "cost_basis")
    expect(cost_header).to_have_class("comparison-unit-header")
    expect(cost_header.locator("th")).to_have_text(["비용 구분"] + ["배치당 (원)", "1T당 (원/T)"] * 4)
    composition_box = comparison_row(page, "composition").bounding_box()
    header_box = cost_header.bounding_box()
    api_box = comparison_row(page, "api_cost").bounding_box()
    assert composition_box["y"] + composition_box["height"] <= header_box["y"] + 1
    assert header_box["y"] + header_box["height"] <= api_box["y"] + 1
    for index, scenario_id in enumerate(ids):
        expect(cost_cell(page, "api_cost", scenario_id, "batch")).to_have_text(f"{2000000 * (index + 1):,.2f}")
        expect(cost_cell(page, "api_cost", scenario_id, "unit")).to_have_text(f"{20 * (index + 1):.2f}")
        expect(cost_cell(page, "packaging_cost", scenario_id, "batch")).to_have_text("1,000,000.00")
        expect(cost_cell(page, "packaging_cost", scenario_id, "unit")).to_have_text("10.00")
    for field in ["api_cost", "excipient_cost", "packaging_cost", "labor_cost"]:
        expect(comparison_row(page, field).locator("td")).to_have_count(8)
    for field in ["name", "packaging_form", "price", "total_cost", "composition"]:
        cells = comparison_row(page, field).locator("td")
        expect(cells).to_have_count(4)
        for cell in cells.all():
            expect(cell).to_have_attribute("colspan", "2")


def test_print_button_calls_browser_print_without_changing_project(page):
    four_scenarios(page)
    comparison(page)
    before = project(page)
    page.evaluate("() => { window.__printCalls = 0; window.print = () => { window.__printCalls += 1; }; }")
    assert page.evaluate("window.__printCalls") == 0
    page.locator("#print-comparison").click()
    assert page.evaluate("window.__printCalls") == 1
    assert project(page) == before
    expect(page.locator("#tab-comparison")).to_be_visible()


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="PDF text/bounds validation requires pdftotext")
def test_four_scenarios_and_long_api_names_print_on_one_a4_page_without_clipping(page, tmp_path):
    four_scenarios(page, detailed_api=True)
    comparison(page)
    before = project(page)
    for field in ["api_supplier", "api_price"]:
        for cell in comparison_row(page, field).locator("td").all():
            for name in cell.locator(".comparison-api-name").all():
                assert name.evaluate("node => node.clientWidth >= 120")
                assert name.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
                assert name.evaluate("node => node.getBoundingClientRect().height <= parseFloat(getComputedStyle(node).lineHeight) + 1")
    page.emulate_media(media="print")
    expect(page.locator("#tab-comparison")).to_be_visible()
    for selector in ["#tab-input", "#tab-results", ".app-header", ".scenario-toolbar", ".page-tabs", ".app-footer", "#print-comparison"]:
        expect(page.locator(selector)).to_be_hidden()
    expect(page.locator(".comparison-composition")).to_have_count(4)
    for graph in page.locator(".comparison-composition").all():
        expect(graph).to_be_visible()
        expect(graph.locator('[data-chart-part="donut"] svg')).to_be_visible()
        expect(graph.locator('[data-chart-part="stack"] [data-item="api"]')).to_be_visible()
    pdf_path = tmp_path / "four-scenarios-comparison.pdf"
    page.pdf(path=str(pdf_path), prefer_css_page_size=True, print_background=True)
    assert pdf_path.stat().st_size > 10000
    output = subprocess.run(["pdftotext", "-bbox", str(pdf_path), "-"], check=True, capture_output=True, text=True).stdout
    root = ET.fromstring(output)
    namespace = {"x": "http://www.w3.org/1999/xhtml"}
    pages = root.findall(".//x:page", namespace)
    assert len(pages) == 1, f"Expected one printed page, got {len(pages)}"
    text = " ".join(word.text or "" for word in root.findall(".//x:word", namespace))
    for name in ["PTP 비교안", "병 포장 비교안", "최종 검토안"]:
        assert name in text
    for expected in ["API", "부형제", "포자재비", "공수비", "배치당", "1T당", "55.00", "75.00", "95.00", "115.00", "8,500,000.00", "보노프라잔 푸마레이트", "아목시실린 수화물", "제조원 A", "제조원 B"]:
        assert expected in text
    assert "처방부터 배치 원가까지" not in text
    for pdf_page in pages:
        width, height = float(pdf_page.attrib["width"]), float(pdf_page.attrib["height"])
        assert sorted([width, height]) == pytest.approx([595.28, 841.89], abs=1)
        for word in pdf_page.findall(".//x:word", namespace):
            assert 0 <= float(word.attrib["xMin"]) <= float(word.attrib["xMax"]) <= width
            assert 0 <= float(word.attrib["yMin"]) <= float(word.attrib["yMax"]) <= height
    assert project(page) == before
