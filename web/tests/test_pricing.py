"""Real browser regressions for manual and ten-year forecast pricing."""

import json

import pytest
from playwright.sync_api import TimeoutError, expect

from web.tests.test_browser import (
    add_material,
    comparison,
    new_project,
    open_file,
    project,
    results,
    save_file,
    scenario,
    select_scenario,
    setup_base,
)


def mode(page, value):
    page.locator(f'[data-field="pricing_mode"][value="{value}"]').check()


def condition(page, field, value=None):
    selector = f'[data-pricing-field="{field}"]'
    if value is not None:
        selector += f'[value="{value}"]'
    return page.locator(selector)


def setup_automatic(page, company="general", count="lt14"):
    setup_base(page)
    add_material(page)
    mode(page, "official")
    page.locator('[data-field="company_type"][value="' + company + '"]').check()
    page.locator('[data-field="identical_count_band"][value="' + count + '"]').check()
    condition(page, "own_data").check()
    condition(page, "dmf").check()
    page.locator("#original-price").fill("1000")
    condition(page, "listing_date").fill("2027-09-01")
    expect(page.locator('[data-pricing-year]')).to_have_count(10)


def amounts(page):
    return page.locator('[data-pricing-year]').evaluate_all(
        'nodes => nodes.map(node => node.dataset.amount)'
    )


def test_manual_mode_blocks_actual_pricing_edits_but_keeps_cost_inputs_enabled(page):
    setup_base(page)
    add_material(page)
    original = scenario(page)
    automatic_controls = page.locator('[data-pricing-automatic]')
    assert automatic_controls.count() > 20
    for control in automatic_controls.all():
        expect(control).to_be_disabled()
    expect(page.locator('#manual-price')).to_be_enabled()
    expect(page.locator('[data-field="pricing_mode"][value="official"]')).to_be_enabled()
    expect(page.locator('#pricing-forecast')).to_be_hidden()
    # A forced mouse click still cannot change a genuinely disabled native control.
    condition(page, 'own_data').click(force=True)
    expect(condition(page, 'own_data')).not_to_be_checked()
    # Disabled elements cannot take focus or accept keyboard input.
    page.locator('#manual-price').focus()
    condition(page, 'dmf').evaluate('node => node.focus()')
    expect(page.locator('#manual-price')).to_be_focused()
    expect(condition(page, 'dmf')).not_to_be_focused()
    page.keyboard.press('Tab')
    assert not page.evaluate('document.activeElement.matches("[data-pricing-automatic]")')
    with pytest.raises(TimeoutError):
        page.locator('#original-price').fill('9999', timeout=250)
    assert scenario(page) == original
    for selector in ['#batch-size', '#yield-percent', '#exchange-rate', '#batch-packaging', '#batch-labor', '[data-material-field="price"]']:
        expect(page.locator(selector)).to_be_enabled()
    page.locator('[data-material-field="price"]').fill('500000')
    results(page)
    expect(page.locator('#result-cost')).to_have_text('40.00')
    expect(page.locator('#result-price')).to_have_text('300.00')
    expect(page.locator('#result-rate')).to_have_text('13.3')


def test_manual_and_automatic_prices_do_not_overwrite_each_other(page):
    setup_automatic(page)
    expect(page.locator('#manual-price')).to_be_hidden()
    expect(page.locator('#manual-price')).to_be_disabled()
    expect(page.locator('#calculated-price')).to_have_text('450.00')
    assert scenario(page)['manual_price'] == '300'
    results(page)
    expect(page.locator('#result-price')).to_have_text('450.00')
    expect(page.locator('#result-rate')).to_have_text('11.1')
    page.locator('#tab-button-input').click()
    mode(page, 'manual')
    expect(page.locator('#manual-price')).to_have_value('300')
    expect(page.locator('#manual-price')).to_be_enabled()
    expect(page.locator('#pricing-forecast')).to_be_hidden()
    results(page)
    expect(page.locator('#result-price')).to_have_text('300.00')
    expect(page.locator('#result-rate')).to_have_text('16.7')
    page.locator('#tab-button-input').click()
    mode(page, 'official')
    expect(page.locator('#calculated-price')).to_have_text('450.00')
    expect(page.locator('[data-pricing-year="1"]')).to_have_attribute('aria-pressed', 'true')


def test_ten_vertical_bars_show_anniversary_periods_and_selected_price_drives_cost_rate(page):
    setup_automatic(page, company='innovative', count='ge14')
    condition(page, 'company_eligible').check()
    condition(page, 'domestic_extension').check()
    assert amounts(page) == ['600'] * 4 + ['383'] * 6
    expect(page.locator('#pricing-forecast-summary')).to_contain_text('1~4년차')
    expect(page.locator('#pricing-forecast-summary')).to_contain_text('383')
    expect(page.locator('#pricing-y-axis span').last).to_have_text('0')
    first = page.locator('[data-pricing-year="1"]')
    last = page.locator('[data-pricing-year="10"]')
    expect(first.locator('.pricing-year-label')).to_contain_text('2027')
    expect(last.locator('.pricing-year-label')).to_contain_text('2036')
    expect(first).to_have_attribute('title', '1년차 · 600.00 원/T · 2027-09-01~2028-08-31\n혁신형 기업가산 · 기본약가 × 60/45')
    assert '2036-09-01~2037-08-31' in last.get_attribute('title')
    fills = page.locator('.pricing-year-fill')
    boxes = [fill.bounding_box() for fill in fills.all()]
    assert len(boxes) == 10
    for left, right in zip(boxes, boxes[1:]):
        assert left['x'] < right['x']
        assert abs((left['y'] + left['height']) - (right['y'] + right['height'])) < 2
        assert left['height'] > left['width']
    assert boxes[0]['height'] > boxes[4]['height']
    page.locator('[data-pricing-year="5"]').click()
    expect(page.locator('#calculated-price')).to_have_text('383.00')
    expect(page.locator('#selected-pricing-year')).to_have_text('선택 연차: 5년차')
    expect(page.locator('[data-pricing-year][aria-pressed="true"]')).to_have_count(1)
    expect(page.locator('[data-pricing-year="5"]')).to_have_attribute('aria-pressed', 'true')
    results(page)
    expect(page.locator('#result-cost')).to_have_text('50.00')
    expect(page.locator('#result-price')).to_have_text('383.00')
    expect(page.locator('#result-rate')).to_have_text('13.1')
    expect(page.locator('#donut-rate')).to_have_text('13.1%')
    comparison(page)
    price_row = page.locator('#comparison-body tr[data-compare-field="price"]')
    if not price_row.count():
        price_row = page.locator('#comparison-body tr').filter(has=page.get_by_role('rowheader', name='우리 제품 약가 (원/T)', exact=True))
    expect(price_row.locator('td').first).to_have_text('383.00')


def test_conditions_recalculate_immediately_and_incomplete_inputs_remove_old_forecast(page):
    setup_automatic(page)
    assert amounts(page) == ['450'] * 10
    condition(page, 'dmf').uncheck()
    assert amounts(page) == ['360'] * 10
    condition(page, 'own_data').uncheck()
    assert amounts(page) == ['290'] * 10
    page.locator('#original-price').fill('')
    expect(page.locator('[data-pricing-year]')).to_have_count(0)
    expect(page.locator('#calculated-price')).to_have_text('계산 불가')
    expect(page.locator('#pricing-forecast-message')).to_contain_text('오리지널')
    results(page)
    expect(page.locator('#result-cost')).to_have_text('50.00')
    expect(page.locator('#result-rate')).to_have_text('계산 불가')
    page.locator('#tab-button-input').click()
    page.locator('#original-price').fill('1000')
    assert amounts(page) == ['290'] * 10
    condition(page, 'listing_date').fill('')
    expect(page.locator('[data-pricing-year]')).to_have_count(0)
    expect(page.locator('#pricing-forecast-message')).to_contain_text('등재일')
    assert 'NaN' not in page.locator('.pricing-card').inner_text()
    assert 'Infinity' not in page.locator('.pricing-card').inner_text()


def test_auto_conditions_and_selected_year_survive_reload_save_open_and_clone(page, tmp_path):
    setup_automatic(page, company='innovative', count='ge14')
    condition(page, 'company_eligible').check()
    condition(page, 'domestic_extension').check()
    page.locator('[data-pricing-year="5"]').click()
    expected = project(page)
    path = tmp_path / 'forecast.json'
    assert save_file(page, path) == expected
    page.reload()
    page.wait_for_function('Boolean(window.PharmaCostApp)')
    assert project(page) == expected
    expect(page.locator('#calculated-price')).to_have_text('383.00')
    expect(page.locator('[data-pricing-year="5"]')).to_have_attribute('aria-pressed', 'true')
    new_project(page)
    open_file(page, path)
    assert project(page) == expected
    expect(page.locator('[data-field="pricing_mode"][value="official"]')).to_be_checked()
    expect(condition(page, 'domestic_extension')).to_be_checked()
    expect(page.locator('#calculated-price')).to_have_text('383.00')
    original = scenario(page)
    page.once('dialog', lambda dialog: dialog.accept('연장 제외안'))
    page.locator('#clone-scenario').click()
    condition(page, 'domestic_extension').uncheck()
    expect(page.locator('#calculated-price')).to_have_text('383.00')
    condition(page, 'own_data').uncheck()
    assert scenario(page)['pricing_conditions']['own_data'] is False
    select_scenario(page, original['id'])
    assert scenario(page) == original
    expect(condition(page, 'own_data')).to_be_checked()
    mode(page, 'manual')
    expect(page.locator('#manual-price')).to_have_value('300')


def test_general_and_supply_categories_are_independent_single_selections_with_separate_details(page):
    setup_automatic(page)
    condition(page, 'general_category', 'data_submission').check()
    condition(page, 'supply_category', 'api_self').check()
    expect(page.locator('#pricing-general-details')).to_be_visible()
    expect(page.locator('#pricing-supply-details')).to_be_visible()
    condition(page, 'general_category', 'improved').check()
    expect(condition(page, 'general_category', 'data_submission')).not_to_be_checked()
    expect(condition(page, 'supply_category', 'api_self')).to_be_checked()
    condition(page, 'supply_category', 'own_injectable_pediatric').check()
    expect(condition(page, 'general_category', 'improved')).to_be_checked()
    expect(condition(page, 'supply_category', 'api_self')).not_to_be_checked()
    expect(page.locator('#pricing-supply-special')).to_be_visible()
    page.locator('[data-field="company_type"][value="near"]').check()
    assert scenario(page)['company_type'] == 'near'
    page.locator('[data-field="company_type"][value="supply_leader"]').check()
    assert scenario(page)['company_type'] == 'supply_leader'
    condition(page, 'general_category', 'none').check()
    expect(page.locator('#pricing-general-details')).to_be_hidden()
    expect(page.locator('#pricing-supply-details')).to_be_visible()
    condition(page, 'supply_category', 'none').check()
    expect(page.locator('#pricing-supply-details')).to_be_hidden()


def test_company_eligibility_and_supply_conditions_prevent_duplicate_bonuses(page):
    setup_automatic(page, company='innovative')
    # Corporate status alone is insufficient; both criteria and eligibility matter.
    assert amounts(page) == ['450'] * 10
    expect(condition(page, 'domestic_extension')).to_be_disabled()
    condition(page, 'company_eligible').check()
    expect(condition(page, 'domestic_extension')).to_be_enabled()
    condition(page, 'domestic_extension').check()
    assert amounts(page) == ['600'] * 4 + ['450'] * 6
    condition(page, 'dmf').uncheck()
    assert amounts(page) == ['360'] * 10
    condition(page, 'dmf').check()
    condition(page, 'supply_category', 'api_self').check()
    expect(condition(page, 'supply_extension')).to_be_disabled()
    condition(page, 'supply_eligible').check()
    expect(condition(page, 'supply_extension')).to_be_enabled()
    assert amounts(page) == ['680'] * 5 + ['450'] * 5
    condition(page, 'supply_extension').check()
    assert amounts(page) == ['680'] * 10
    assert '연장요건 충족 가정' in page.locator('[data-pricing-year="6"]').get_attribute('title')


@pytest.mark.parametrize('category', ['data_submission', 'improved', 'biologic'])
def test_general_category_requires_its_own_conditions_without_generic_fallback(page, category):
    setup_automatic(page)
    condition(page, 'general_category', category).check()
    expect(page.locator('#pricing-general-details')).to_be_visible()
    expect(page.locator('#pricing-status')).to_have_text('추가 산정조건 필요')
    expect(page.locator('#pricing-forecast-message')).to_contain_text('추가 산정조건 필요')
    expect(page.locator('#calculated-price')).to_have_text('계산 불가')
    expect(page.locator('[data-pricing-year]')).to_have_count(0)
    results(page)
    expect(page.locator('#result-cost')).to_have_text('50.00')
    expect(page.locator('#result-rate')).to_have_text('계산 불가')


def test_supported_data_submission_branch_uses_its_comparison_amount_not_original_price(page):
    setup_automatic(page)
    condition(page, 'general_category', 'data_submission').check()
    condition(page, 'general_subtype').select_option('salt_isomer')
    condition(page, 'general_base').fill('200')
    condition(page, 'general_first_listed').check()
    condition(page, 'general_dose_equivalent').check()
    expect(page.locator('#calculated-price')).to_have_text('180.00')
    assert amounts(page) == ['180'] * 10
    page.locator('#original-price').fill('9000')
    expect(page.locator('#calculated-price')).to_have_text('180.00')
    results(page)
    expect(page.locator('#result-price')).to_have_text('180.00')
    expect(page.locator('#result-rate')).to_have_text('27.8')


def test_turning_off_general_extension_preserves_hidden_choice_without_blocking_price(page):
    setup_automatic(page)
    condition(page, 'general_category', 'improved').check()
    condition(page, 'general_subtype').select_option('new_form')
    condition(page, 'general_base').fill('1000')
    for field in ['general_first_listed', 'general_dose_equivalent', 'general_same_reference', 'general_recognized']:
        condition(page, field).check()
    condition(page, 'general_trigger_date').fill('2027-09-01')
    condition(page, 'general_extension').check()
    condition(page, 'general_long_extension').check()
    assert amounts(page) == ['1556'] * 10
    condition(page, 'general_extension').uncheck()
    expect(condition(page, 'general_long_extension')).to_be_hidden()
    expect(condition(page, 'general_long_extension')).to_be_disabled()
    assert scenario(page)['pricing_conditions']['general_long_extension'] is True
    assert amounts(page) == ['1556'] + ['1000'] * 9
    expect(page.locator('#calculated-price')).to_have_text('1,556.00')


@pytest.mark.parametrize('value', ['-1', '0', ''])
def test_invalid_automatic_price_removes_bars_without_false_zero_or_nonfinite_results(page, value):
    setup_automatic(page)
    page.locator('#original-price').fill(value)
    expect(page.locator('[data-pricing-year]')).to_have_count(0)
    expect(page.locator('#calculated-price')).to_have_text('계산 불가')
    results(page)
    expect(page.locator('#result-cost')).to_have_text('50.00')
    expect(page.locator('#result-rate')).to_have_text('계산 불가')
    assert 'NaN' not in page.locator('#tab-results').inner_text()
    assert 'Infinity' not in page.locator('#tab-results').inner_text()


def test_invalid_calendar_date_file_is_rejected_without_replacing_current_project(page, tmp_path):
    setup_automatic(page)
    before = project(page)
    payload = save_file(page, tmp_path / 'valid.json')
    payload['scenarios'][0]['pricing_conditions']['listing_date'] = '2027-02-30'
    open_file(page, {'name': 'bad-date.json', 'mimeType': 'application/json', 'buffer': json.dumps(payload, ensure_ascii=False).encode('utf-8')})
    expect(page.locator('#toast')).to_contain_text('파일을 열 수 없습니다')
    expect(page.locator('#toast')).to_contain_text('날짜')
    assert project(page) == before
    expect(page.locator('[data-pricing-year]')).to_have_count(10)
