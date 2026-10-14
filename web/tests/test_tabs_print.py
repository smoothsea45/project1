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


def four_scenarios(page):
    setup_base(page)
    add_material(page)
    names = ["기본 시나리오", "PTP 비교안", "병 포장 비교안", "최종 검토안"]
    ids = [scenario(page)["id"]]
    page.locator("#packaging-form").fill("30T / PTP")
    page.locator("#manual-price").fill("100")
    for index in range(1, 4):
        ids.append(clone(page, names[index]))
        page.locator("#manual-price").fill(str((index + 1) * 100))
        page.locator('[data-material-field="price"]').fill(str((index + 1) * 1000000))
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
    if width >= 1024:
        assert boxes[0]["x"] + boxes[0]["width"] < graph["x"]
        assert abs(boxes[0]["y"] - graph["y"]) <= 1
        assert abs(boxes[0]["x"] - boxes[2]["x"]) <= 1
    else:
        assert boxes[2]["y"] + boxes[2]["height"] <= graph["y"] + 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


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
    expect(headers).to_have_count(5)
    for heading in headers.all()[1:]:
        expect(heading).to_have_attribute("colspan", "2")
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
def test_four_scenarios_print_to_landscape_pdf_with_all_rows_and_visible_graphs(page, tmp_path):
    four_scenarios(page)
    comparison(page)
    before = project(page)
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
    assert pages
    text = " ".join(word.text or "" for word in root.findall(".//x:word", namespace))
    for name in ["PTP 비교안", "병 포장 비교안", "최종 검토안"]:
        assert name in text
    for expected in ["API", "부형제", "포자재비", "공수비", "배치당", "1T당", "50.00", "70.00", "90.00", "110.00", "8,000,000.00"]:
        assert expected in text
    assert "처방부터 배치 원가까지" not in text
    for pdf_page in pages:
        width, height = float(pdf_page.attrib["width"]), float(pdf_page.attrib["height"])
        assert width > height  # CSS chooses landscape paper.
        for word in pdf_page.findall(".//x:word", namespace):
            assert 0 <= float(word.attrib["xMin"]) <= float(word.attrib["xMax"]) <= width
            assert 0 <= float(word.attrib["yMin"]) <= float(word.attrib["yMax"]) <= height
    assert project(page) == before
