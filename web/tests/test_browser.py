"""Exercise the offline web UI in Chromium, with a temporary local test server.

Run: python -m pytest web/tests/test_browser.py
Install Chromium with: python -m playwright install chromium
Alternatively set CHROMIUM_EXECUTABLE to an installed Chromium executable.
All test data are fictitious; the tests do not contact outside services.
"""

import json
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect


def project(page):
    return page.evaluate("PharmaCostApp.getProject()")


def scenario(page):
    data = project(page)
    return next(s for s in data["scenarios"] if s["id"] == data["active_scenario_id"])


def select_scenario(page, scenario_id):
    page.locator(f'#scenario-tabs [data-scenario-id="{scenario_id}"]').click()


def discard_if_needed(page):
    dialog = page.locator("dialog.project-dialog")
    if dialog.count():
        dialog.locator('[data-choice="discard"]').click()


def new_project(page):
    page.locator("#new-project").click()
    discard_if_needed(page)
    expect(page.locator("#material-body tr")).to_have_count(0)


def setup_base(page):
    new_project(page)
    page.locator("#product-name").fill("검증 제품")
    page.locator("#batch-size").fill("100000")
    page.locator("#manual-price").fill("300")
    page.locator("#batch-packaging").fill("1000000")
    page.locator("#batch-labor").fill("2000000")


def add_material(page, kind="api", amount="20", price="1000000", unit="krw_kg"):
    page.locator("#add-" + kind).click()
    row = page.locator("#material-body tr").last
    row.locator('[data-material-field="name"]').fill("검증 API" if kind == "api" else "검증 부형제")
    row.locator('[data-material-field="supplier"]').fill("검증 공급처")
    row.locator('[data-material-field="amount"]').fill(amount)
    row.locator('[data-material-field="price"]').fill(price)
    row.locator('[data-material-field="price_unit"]').select_option(unit)
    return row


def results(page):
    page.locator("#tab-button-results").click()


def comparison(page):
    page.locator("#tab-button-comparison").click()


def open_file(page, payload):
    with page.expect_file_chooser() as chooser:
        page.locator("#open-project").click()
    chooser.value.set_files(payload)


def save_file(page, path):
    with page.expect_download() as download:
        page.locator("#save-project").click()
    download.value.save_as(path)
    return json.loads(path.read_text(encoding="utf-8"))


def test_first_open_fictitious_example_and_three_distinct_pages(page):
    expect(page.locator("#example-banner")).to_be_visible()
    expect(page.locator("#material-body tr")).to_have_count(3)
    expect(page.locator('#scenario-tabs [role="tab"]')).to_have_count(2)
    expect(page.locator('.page-tabs [role="tab"]')).to_have_count(3)
    expect(page.locator("#tab-results")).to_be_hidden()
    expect(page.locator("#tab-comparison")).to_be_hidden()
    results(page)
    expect(page.locator("#tab-input")).to_be_hidden()
    expect(page.locator("#result-cost")).to_have_text("80.00")
    expect(page.locator("#result-rate")).to_have_text("26.7")
    expect(page.locator("#tab-comparison")).to_be_hidden()
    comparison(page)
    expect(page.locator("#tab-results")).to_be_hidden()
    expect(page.locator("#comparison-head tr").first.locator("th")).to_have_count(3)
    assert "양품" not in page.locator("body").inner_text()


def test_tabs_are_named_buttons_and_work_with_keyboard(page):
    tabs = [
        ("input", "입력"),
        ("results", "결과"),
        ("comparison", "시나리오 비교"),
    ]
    for name, label in tabs:
        expect(page.locator("#tab-button-" + name)).to_contain_text(label)
    page.locator("#tab-button-input").focus()
    expect(page.locator("#tab-button-input")).to_have_attribute("tabindex", "0")
    page.keyboard.press("ArrowRight")
    expect(page.locator("#tab-button-results")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#tab-button-results")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#tab-results")).to_be_visible()
    expect(page.locator("#tab-input")).to_be_hidden()
    expect(page.locator("#tab-comparison")).to_be_hidden()
    page.keyboard.press("ArrowRight")
    expect(page.locator("#tab-button-comparison")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#tab-button-comparison")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#tab-comparison")).to_be_visible()
    expect(page.locator("#tab-results")).to_be_hidden()
    expect(page.locator("#tab-button-results")).to_have_attribute("aria-selected", "false")
    page.keyboard.press("Home")
    expect(page.locator("#tab-button-input")).to_be_focused()
    expect(page.locator("#tab-input")).to_be_visible()
    page.keyboard.press("Tab")
    expect(page.locator("#product-name")).to_be_focused()


def test_pricing_choices_on_left_prices_on_right_and_drug_groups_are_independent(page):
    setup_base(page)
    page.locator('[data-field="pricing_mode"][value="official"]').check()
    general = page.locator('[data-pricing-field="general_category"]')
    supply = page.locator('[data-pricing-field="supply_category"]')
    expect(general).to_have_count(4)
    expect(supply).to_have_count(4)
    for choice in general.all() + supply.all():
        expect(choice).to_have_attribute("type", "radio")
    page.locator('[data-pricing-field="general_category"][value="data_submission"]').check()
    page.locator('[data-pricing-field="supply_category"][value="domestic_essential"]').check()
    expect(page.locator('[data-pricing-field="general_category"]:checked')).to_have_count(1)
    expect(page.locator('[data-pricing-field="supply_category"]:checked')).to_have_count(1)
    assert scenario(page)["pricing_conditions"]["general_category"] == "data_submission"
    assert scenario(page)["pricing_conditions"]["supply_category"] == "domestic_essential"
    page.locator('[name="company-type"][value="near"]').check()
    page.locator('[name="identical-count-band"][value="ge14"]').check()
    assert scenario(page)["company_type"] == "near"
    assert scenario(page)["identical_count_band"] == "ge14"
    expect(page.locator("#target-rate")).to_have_count(0)
    original_box = page.locator("#original-price").bounding_box()
    calculated_box = page.locator("#calculated-price").bounding_box()
    for selector in [
        '[name="company-type"][value="near"]',
        '[data-pricing-field="supply_category"][value="domestic_essential"]',
        '[name="identical-count-band"][value="ge14"]',
    ]:
        choice_box = page.locator(selector).bounding_box()
        assert choice_box["x"] < original_box["x"]
        assert choice_box["x"] < calculated_box["x"]


def test_root_entry_redirects_into_working_ui(page, site_url):
    page.goto(site_url + "/")
    page.wait_for_url(site_url + "/web/index.html")
    expect(page.locator(".app-header h1")).to_contain_text("의약품 제조원가율")
    expect(page.locator("#api-unit")).to_have_text("40.00")


def test_editing_recalculates_before_focus_moves(page):
    setup_base(page)
    row = add_material(page)
    amount = row.locator('[data-material-field="amount"]')
    amount.fill("")
    expect(page.locator("#api-unit")).to_have_text("미완성")
    amount.press_sequentially("20")
    expect(amount).to_be_focused()
    expect(page.locator("#api-unit")).to_have_text("20.00")
    expect(row.locator('[data-result-field="batch_cost"]')).to_have_text("2,000,000.00")
    expect(row.locator('[data-result-field="unit_cost"]')).to_have_text("20.00")
    assert scenario(page)["materials"][0]["amount"] == "20"


def test_shared_yield_adjusts_all_unit_costs_not_batch_totals(page):
    setup_base(page)
    row = add_material(page)
    expect(page.locator("#yield-percent")).to_have_value("100")
    page.locator("#yield-percent").fill("80")
    expect(page.locator("#api-batch")).to_have_text("2,000,000.00")
    expect(row.locator('[data-result-field="batch_cost"]')).to_have_text("2,000,000.00")
    expect(row.locator('[data-result-field="unit_cost"]')).to_have_text("25.00")
    expect(page.locator("#packaging-unit")).to_have_text("12.50")
    expect(page.locator("#labor-unit")).to_have_text("25.00")
    results(page)
    expect(page.locator("#result-cost")).to_have_text("62.50")
    expect(page.locator("#result-rate")).to_have_text("20.8")


@pytest.mark.parametrize(
    ("unit", "price", "label"),
    [
        ("krw_g", "1000", "원/g"),
        ("krw_kg", "1000000", "원/kg"),
        ("usd_g", "1", "달러/g"),
        ("usd_kg", "1000", "달러/kg"),
    ],
)
def test_price_units_and_common_foreign_exchange(page, unit, price, label):
    setup_base(page)
    page.locator("#exchange-rate").fill("1000")
    row = add_material(page, price=price, unit=unit)
    expect(row.locator('[data-material-field="price_unit"]')).to_have_value(unit)
    expect(row.locator('[data-material-field="price_unit"] option:checked')).to_have_text(label)
    expect(page.locator("#api-unit")).to_have_text("20.00")
    page.locator("#exchange-rate").fill("2000")
    expect(page.locator("#api-unit")).to_have_text("40.00" if unit.startswith("usd") else "20.00")


def test_table_columns_add_multiple_apis_excipients_and_selected_delete(page):
    setup_base(page)
    expect(page.locator(".material-table thead th")).to_have_count(9)  # Eight data columns plus selection.
    header = page.locator(".material-table thead").inner_text()
    assert "등급" not in header and "견적일" not in header
    add_material(page)
    add_material(page, amount="10", price="2000000")
    add_material(page, kind="excipient", amount="100", price="100000")
    expect(page.locator("#api-unit")).to_have_text("40.00")
    expect(page.locator("#excipient-unit")).to_have_text("10.00")
    expect(page.locator("#excipient-batch")).to_have_text("1,000,000.00")
    page.get_by_role("checkbox", name="원료 1행 선택", exact=True).check()
    page.get_by_role("checkbox", name="원료 3행 선택", exact=True).check()
    page.locator("#delete-materials").click()
    expect(page.locator("#material-body tr")).to_have_count(1)
    expect(page.locator("#api-unit")).to_have_text("20.00")
    expect(page.locator("#excipient-unit")).to_have_text("0.00")
    page.locator("#select-all-materials").check()
    page.locator("#delete-materials").click()
    expect(page.locator("#material-body tr")).to_have_count(0)


def test_clipboard_table_paste_expands_rows_and_converts_choices(page):
    setup_base(page)
    page.locator("#exchange-rate").fill("1000")
    row = add_material(page)
    clipboard = "API\t복합 A\t제조원 A\t20\t1000000\t원/kg\n부형제\t기제 B\t공급처 B\t100\t1\t달러/g"
    page.evaluate("text => navigator.clipboard.writeText(text)", clipboard)
    row.locator('[data-material-field="kind"]').focus()
    page.keyboard.press("Control+v")
    expect(page.locator("#material-body tr")).to_have_count(2)
    expect(page.locator("#api-unit")).to_have_text("20.00")
    expect(page.locator("#excipient-unit")).to_have_text("100.00")
    assert [m["name"] for m in scenario(page)["materials"]] == ["복합 A", "기제 B"]


def test_large_inputs_format_commas_without_changing_numeric_data(page):
    setup_base(page)
    fields = [
        ("#batch-size", "batch_size", "100000", "100,000"),
        ("#exchange-rate", "exchange_rate", "1350", "1,350"),
        ("#manual-price", "manual_price", "300000", "300,000"),
        ("#batch-packaging", "batch_packaging", "1000000", "1,000,000"),
        ("#batch-labor", "batch_labor", "2000000", "2,000,000"),
    ]
    for selector, key, value, displayed in fields:
        page.locator(selector).fill(value)
        expect(page.locator(selector)).to_have_value(displayed)
        assert scenario(page)[key] == value
    page.locator('[data-field="pricing_mode"][value="official"]').check()
    page.locator("#original-price").fill("125000")
    expect(page.locator("#original-price")).to_have_value("125,000")
    assert scenario(page)["original_price"] == "125000"
    page.locator('[data-field="pricing_mode"][value="manual"]').check()
    expect(page.locator("#post-price, .secondary-price")).to_have_count(0)
    row = add_material(page, amount="1234.5000")
    expect(row.locator('[data-material-field="amount"]')).to_have_value("1,234.5000")
    expect(row.locator('[data-material-field="price"]')).to_have_value("1,000,000")
    assert scenario(page)["materials"][0]["amount"] == "1234.5000"
    assert scenario(page)["materials"][0]["price"] == "1000000"
    expect(page.locator("#api-unit")).to_have_text("1,234.50")
    results(page)
    expect(page.locator("#result-cost")).to_have_text("1,264.50")


def test_comma_formatting_preserves_precision_through_clone_reload_and_json(page, tmp_path):
    setup_base(page)
    row = add_material(page, price="1,234.5000")
    expect(row.locator('[data-material-field="price"]')).to_have_value("1,234.5000")
    assert scenario(page)["materials"][0]["price"] == "1234.5000"
    page.locator("#batch-packaging").fill("1,000,000.0000")
    expect(page.locator("#batch-packaging")).to_have_value("1,000,000.0000")
    original = scenario(page)
    page.once("dialog", lambda dialog: dialog.accept("입력 표시 검증"))
    page.locator("#clone-scenario").click()
    expect(page.locator('[data-material-field="price"]')).to_have_value("1,234.5000")
    select_scenario(page, original["id"])
    expect(page.locator("#batch-size")).to_have_value("100,000")
    expect(page.locator('[data-material-field="price"]')).to_have_value("1,234.5000")
    path = tmp_path / "precision.json"
    saved = save_file(page, path)
    assert saved["scenarios"][0]["materials"][0]["price"] == "1234.5000"
    assert saved["scenarios"][0]["batch_packaging"] == "1000000.0000"
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    expect(page.locator('[data-material-field="price"]')).to_have_value("1,234.5000")
    expect(page.locator("#batch-packaging")).to_have_value("1,000,000.0000")
    assert project(page) == saved
    new_project(page)
    open_file(page, path)
    expect(page.locator('[data-material-field="price"]')).to_have_value("1,234.5000")
    assert project(page) == saved


def test_live_numeric_typing_preserves_decimal_entry_and_caret(page):
    setup_base(page)
    add_material(page)
    price = page.locator('[data-material-field="price"]')
    price.fill("")
    price.press_sequentially("1234.")
    expect(price).to_have_value("1,234.")
    price.press_sequentially("5000")
    expect(price).to_have_value("1,234.5000")
    assert scenario(page)["materials"][0]["price"] == "1234.5000"
    price.fill("1000000")
    price.evaluate("input => input.setSelectionRange(1, 1)")
    price.press("9")
    expect(price).to_have_value("19,000,000")
    price.press("8")
    expect(price).to_have_value("198,000,000")
    assert scenario(page)["materials"][0]["price"] == "198000000"
    expect(price).to_be_focused()


@pytest.mark.parametrize(
    ("caret", "key", "displayed", "raw"),
    [(3, "Backspace", "1,345", "1345"), (2, "Delete", "1,245", "1245")],
)
def test_numeric_deletion_across_group_separator_edits_adjacent_digit(page, caret, key, displayed, raw):
    setup_base(page)
    add_material(page, price="12345")
    price = page.locator('[data-material-field="price"]')
    price.focus()
    price.evaluate("(input, position) => input.setSelectionRange(position, position)", caret)
    price.press(key)
    expect(price).to_have_value(displayed)
    assert scenario(page)["materials"][0]["price"] == raw
    price.press("9")
    assert scenario(page)["materials"][0]["price"] != raw
    expect(price).to_be_focused()


@pytest.mark.parametrize("raw", ["1,2", "12,34", "1,,000", "1.2.3"])
def test_malformed_numeric_text_remains_visible_and_invalid(page, raw):
    setup_base(page)
    add_material(page)
    price = page.locator('[data-material-field="price"]')
    price.fill(raw)
    expect(price).to_have_value(raw)
    expect(price).to_have_attribute("aria-invalid", "true")
    assert scenario(page)["materials"][0]["price"] == raw
    results(page)
    expect(page.locator("#result-cost")).to_have_text("미완성")
    page.locator("#tab-button-input").click()
    expect(price).to_have_value(raw)
    price.fill("1000000")
    expect(price).to_have_value("1,000,000")
    expect(price).not_to_have_attribute("aria-invalid", "true")
    expect(page.locator("#api-unit")).to_have_text("20.00")


def test_comma_formatted_tsv_paste_normalizes_model_and_preserves_focus(page):
    setup_base(page)
    row = add_material(page)
    clipboard = "API\t붙여넣기 원료\t공급처\t1,234.5000\t1,000,000\t원/kg"
    page.evaluate("text => navigator.clipboard.writeText(text)", clipboard)
    row.locator('[data-material-field="kind"]').focus()
    page.keyboard.press("Control+v")
    expect(page.locator('[data-material-field="amount"]')).to_have_value("1,234.5000")
    expect(page.locator('[data-material-field="price"]')).to_have_value("1,000,000")
    assert scenario(page)["materials"][0]["amount"] == "1234.5000"
    assert scenario(page)["materials"][0]["price"] == "1000000"
    expect(page.locator('[data-material-field="kind"]')).to_be_focused()
    expect(page.locator("#api-unit")).to_have_text("1,234.50")


def test_cloned_scenario_keeps_original_and_compares_side_by_side(page):
    setup_base(page)
    add_material(page)
    original = scenario(page)
    page.once("dialog", lambda dialog: dialog.accept("API 단가 절감안"))
    page.locator("#clone-scenario").click()
    page.locator('[data-material-field="price"]').fill("400000")
    page.locator("#yield-percent").fill("80")
    data = project(page)
    assert len(data["scenarios"]) == 2
    assert data["scenarios"][0] == original
    clone = data["scenarios"][1]
    assert clone["id"] != original["id"]
    assert clone["materials"][0]["id"] != original["materials"][0]["id"]
    assert clone["materials"][0]["price"] == "400000"
    comparison(page)
    expect(page.locator("#comparison-head tr").first.locator("th")).to_have_count(3)
    expect(page.locator("#comparison-head tr").first.locator("th").nth(2)).to_have_text("API 단가 절감안")
    cost_row = page.locator("#comparison-body tr").filter(has=page.get_by_role("rowheader", name="제조원가 (원/T)", exact=True))
    expect(cost_row.locator("td").nth(0)).to_have_text("50.00")
    expect(cost_row.locator("td").nth(1)).to_have_text("47.50")
    page.locator("#tab-button-input").click()
    select_scenario(page, original["id"])
    expect(page.locator('[data-material-field="price"]')).to_have_value("1,000,000")
    expect(page.locator("#yield-percent")).to_have_value("100")


def test_pricing_mode_is_beside_title_and_loaded_automatic_mode_uses_calculated_price(page, tmp_path):
    setup_base(page)
    add_material(page)
    manual_option = page.locator('[data-field="pricing_mode"][value="manual"]')
    expect(manual_option).to_be_checked()
    expect(page.locator("#manual-price")).to_be_enabled()
    heading = page.locator("#pricing-heading").bounding_box()
    mode = manual_option.bounding_box()
    assert mode["x"] >= heading["x"] + heading["width"]
    assert abs(mode["y"] - heading["y"]) <= 24
    page.locator('[data-field="pricing_mode"][value="official"]').check()
    page.locator("#original-price").fill("1000")
    page.locator('[name="company-type"][value="general"]').check()
    page.locator('[name="identical-count-band"][value="lt14"]').check()
    page.locator('[data-pricing-field="own_data"]').check()
    page.locator('[data-pricing-field="dmf"]').check()
    page.locator('[data-pricing-field="listing_date"]').fill("2027-09-01")
    path = tmp_path / "automatic.json"
    saved = save_file(page, path)
    new_project(page)
    open_file(page, path)
    assert project(page) == saved
    assert scenario(page)["pricing_mode"] == "official"
    results(page)
    expect(page.locator("#result-cost")).to_have_text("50.00")
    expect(page.locator("#result-price")).to_have_text("450.00")
    expect(page.locator("#pricing-source")).to_contain_text("1년차")
    expect(page.locator("#result-rate")).to_have_text("11.1")
    assert scenario(page)["manual_price"] == "300"


@pytest.mark.parametrize("price", ["", "0"])
def test_missing_or_zero_price_retains_cost_without_cost_rate(page, price):
    setup_base(page)
    add_material(page)
    page.locator("#manual-price").fill(price)
    expect(page.locator("#input-errors")).to_be_visible()
    results(page)
    expect(page.locator("#result-cost")).to_have_text("50.00")
    expect(page.locator("#result-rate")).to_have_text("계산 불가")


@pytest.mark.parametrize(
    ("selector", "value"),
    [
        ("#batch-size", "0"),
        ("#yield-percent", "0"),
        ("#yield-percent", "101"),
        ("#batch-packaging", "-1"),
        ('[data-material-field="amount"]', ""),
        ('[data-material-field="price"]', "-1"),
    ],
)
def test_invalid_required_inputs_highlight_and_withhold_final_total(page, selector, value):
    setup_base(page)
    add_material(page)
    page.locator(selector).fill(value)
    expect(page.locator(selector)).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#input-errors")).to_be_visible()
    results(page)
    expect(page.locator("#result-cost")).to_have_text("미완성")
    expect(page.locator("#result-rate")).to_have_text("계산 불가")


def test_missing_exchange_highlights_for_dollar_material(page):
    setup_base(page)
    add_material(page, price="1000", unit="usd_kg")
    expect(page.locator("#exchange-rate")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#api-unit")).to_have_text("미완성")
    page.locator("#exchange-rate").fill("1000")
    expect(page.locator("#api-unit")).to_have_text("20.00")


def test_rate_over_100_retained_without_pricing_basis_or_goal_metrics(page):
    setup_base(page)
    add_material(page)
    page.locator("#manual-price").fill("25")
    expect(page.locator("#post-price, .secondary-price")).to_have_count(0)
    results(page)
    expect(page.locator("#result-rate")).to_have_text("200.0")
    expect(page.locator("#result-post-rate, #pricing-rule, #pricing-date, #pricing-steps")).to_have_count(0)
    assert scenario(page)["post_price"] is None
    expect(page.locator("#target-rate, #result-gap, #result-savings, #result-target-status")).to_have_count(0)
    comparison(page)
    assert "목표" not in page.locator("#comparison-body").inner_text()


def test_json_download_open_restores_pricing_conditions_product_and_scenarios(page, tmp_path):
    setup_base(page)
    add_material(page)
    page.locator("#product-notes").fill("캡슐·함량은 비고에 기록")
    page.locator('[data-field="pricing_mode"][value="official"]').check()
    page.locator('[name="company-type"][value="near"]').check()
    page.locator('[name="identical-count-band"][value="ge14"]').check()
    page.locator('[data-pricing-field="general_category"][value="improved"]').check()
    page.locator('[data-pricing-field="supply_category"][value="api_self"]').check()
    page.locator('[data-pricing-field="supply_eligible"]').check()
    page.locator('[data-pricing-field="own_data"]').check()
    page.once("dialog", lambda dialog: dialog.accept("비교안"))
    page.locator("#clone-scenario").click()
    page.locator("#yield-percent").fill("98")
    expected = project(page)
    path = tmp_path / "project.json"
    assert save_file(page, path) == expected
    expect(page.locator("#project-status")).to_have_text("프로젝트 파일")
    new_project(page)
    open_file(page, path)
    expect(page.locator("#product-name")).to_have_value("검증 제품")
    expect(page.locator('#scenario-tabs [role="tab"]')).to_have_count(2)
    expect(page.locator("#yield-percent")).to_have_value("98")
    expect(page.locator('[data-pricing-field="general_category"][value="improved"]')).to_be_checked()
    expect(page.locator('[data-pricing-field="supply_category"][value="api_self"]')).to_be_checked()
    expect(page.locator('[data-pricing-field="supply_eligible"]')).to_be_checked()
    assert project(page) == expected


def test_legacy_multiple_drug_additions_are_preserved_with_review_notice(page, tmp_path):
    setup_base(page)
    add_material(page)
    payload = save_file(page, tmp_path / "before.json")
    payload["schema_version"] = 1
    payload["scenarios"][0].pop("pricing_conditions")
    payload["scenarios"][0]["pricing_flags"] = ["originator_data", "api_self"]
    open_file(page, {
        "name": "legacy-additions.json",
        "mimeType": "application/json",
        "buffer": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    })
    expect(page.locator("#input-errors")).to_be_hidden()
    expect(page.locator("#pricing-migration-notice")).to_be_visible()
    expect(page.locator("#pricing-migration-message")).to_contain_text("다시 확인")
    assert scenario(page)["pricing_flags"] == ["originator_data", "api_self"]
    assert scenario(page)["pricing_conditions"]["general_category"] == "none"
    assert scenario(page)["pricing_conditions"]["supply_category"] == "api_self"
    saved = save_file(page, tmp_path / "multiple.json")
    assert saved["scenarios"][0]["pricing_flags"] == ["originator_data", "api_self"]
    page.locator('[data-field="pricing_mode"][value="official"]').check()
    expect(page.locator("#calculated-price")).to_have_text("계산 불가")
    expect(page.locator('[data-pricing-year]')).to_have_count(0)
    page.locator("#pricing-review-legacy").click()
    expect(page.locator("#pricing-migration-notice")).to_be_hidden()
    assert scenario(page)["pricing_conditions"]["migration_review"] == ""
    saved = save_file(page, tmp_path / "reviewed.json")
    assert saved["scenarios"][0]["pricing_flags"] == ["originator_data", "api_self"]


@pytest.mark.parametrize(
    "contents",
    ["{invalid", '{"schema_version":1,"product":{"name":"legacy"}}'],
)
def test_invalid_and_legacy_files_show_error_preserve_current_project(page, contents):
    setup_base(page)
    add_material(page)
    original = project(page)
    open_file(page, {"name": "broken.json", "mimeType": "application/json", "buffer": contents.encode("utf-8")})
    expect(page.locator("#toast")).to_be_visible()
    expect(page.locator("#toast")).to_contain_text("파일을 열 수 없습니다")
    expect(page.locator("#product-name")).to_have_value("검증 제품")
    assert project(page) == original


def test_new_project_cancel_and_discard_preserve_user_choice(page):
    setup_base(page)
    original = project(page)
    page.locator("#new-project").click()
    expect(page.locator("dialog.project-dialog")).to_be_visible()
    page.locator('[data-choice="cancel"]').click()
    assert project(page) == original
    page.locator("#new-project").click()
    page.locator('[data-choice="discard"]').click()
    expect(page.locator("#product-name")).to_have_value("")
    expect(page.locator("#yield-percent")).to_have_value("100")
    expect(page.locator('#scenario-tabs [role="tab"]')).to_have_count(1)
    expect(page.locator("#example-banner")).to_be_hidden()


def test_open_file_can_cancel_replacing_unsaved_changes(page, tmp_path):
    original = project(page)
    saved = tmp_path / "example.json"
    save_file(page, saved)
    setup_base(page)
    edited = project(page)
    open_file(page, saved)
    expect(page.locator("dialog.project-dialog")).to_be_visible()
    page.locator('[data-choice="cancel"]').click()
    assert project(page) == edited
    open_file(page, saved)
    expect(page.locator("dialog.project-dialog")).to_be_visible()
    page.locator('[data-choice="discard"]').click()
    expect(page.locator("#product-name")).to_have_value(original["product"]["product_name"])
    assert project(page) == original


def test_browser_draft_restores_all_edits_on_reload(page):
    setup_base(page)
    add_material(page)
    page.locator("#yield-percent").fill("98")
    original = project(page)
    page.once("dialog", lambda dialog: dialog.accept())
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    expect(page.locator("#yield-percent")).to_have_value("98")
    expect(page.locator("#app-status")).to_contain_text("초안을 복원")
    assert project(page) == original


def test_all_loaded_assets_are_local_and_operations_need_no_outside_service(page):
    # The page fixture rejects any nonlocal HTTP request in every test.
    setup_base(page)
    add_material(page)
    results(page)
    expect(page.locator("#result-cost")).to_have_text("50.00")
    resources = page.evaluate("performance.getEntriesByType('resource').map(item => item.name)")
    assert resources
    assert all(urlparse(url).hostname == "127.0.0.1" for url in resources)
