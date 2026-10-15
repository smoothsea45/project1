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
    expect(price_row.locator('td').first).to_have_text('600.00')


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
    expect(page.locator('#calculated-price')).to_have_text('383.00')
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


def test_general_and_supply_categories_are_independent_single_selections_without_detail_inputs(page):
    setup_automatic(page)
    condition(page, 'general_category', 'data_submission').check()
    condition(page, 'supply_category', 'api_self').check()
    condition(page, 'general_category', 'improved_combo').check()
    expect(condition(page, 'general_category', 'data_submission')).not_to_be_checked()
    expect(condition(page, 'supply_category', 'api_self')).to_be_checked()
    condition(page, 'supply_category', 'own_injectable_pediatric').check()
    expect(condition(page, 'general_category', 'improved_combo')).to_be_checked()
    expect(condition(page, 'supply_category', 'api_self')).not_to_be_checked()
    expect(page.locator('[data-pricing-field="general_category"]:checked')).to_have_count(1)
    expect(page.locator('[data-pricing-field="supply_category"]:checked')).to_have_count(1)
    for field in ['general_subtype', 'general_base', 'general_cap', 'general_trigger_date', 'general_same_reference', 'general_recognized', 'general_extension', 'general_long_extension', 'general_first_listed', 'general_dose_equivalent', 'general_reference_own', 'general_target_biologic', 'supply_eligible', 'supply_extension', 'supply_detail_eligible']:
        expect(condition(page, field)).to_have_count(0)
    page.locator('[data-field="company_type"][value="near"]').check()
    assert scenario(page)['company_type'] == 'near'
    page.locator('[data-field="company_type"][value="supply_leader"]').check()
    assert scenario(page)['company_type'] == 'supply_leader'
    condition(page, 'general_category', 'none').check()
    expect(page.locator('#calculated-price')).to_have_text('680.00')

def test_company_eligibility_is_preserved_and_supply_choice_applies_without_duplicate_bonuses(page):
    setup_automatic(page, company='innovative')
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
    assert amounts(page) == ['680'] * 10
    expect(condition(page, 'company_eligible')).to_be_hidden()
    assert '연장' in page.locator('[data-pricing-year="6"]').get_attribute('title')
    condition(page, 'supply_category', 'none').check()
    expect(condition(page, 'company_eligible')).to_be_visible()
    expect(condition(page, 'domestic_extension')).to_be_checked()
    assert amounts(page) == ['600'] * 4 + ['450'] * 6

@pytest.mark.parametrize(
    ('category', 'expected'),
    [
        ('data_submission', ['700'] + ['600'] * 3 + ['450'] * 6),
        ('improved', ['700'] + ['450'] * 9),
        ('improved_combo', ['680'] + ['450'] * 9),
        ('other', ['600'] * 4 + ['450'] * 6),
        ('biologic', ['800'] * 5 + ['700'] * 5),
    ],
)
def test_simple_general_schedules_use_original_price_and_need_no_extra_inputs(page, category, expected):
    setup_automatic(page)
    condition(page, 'general_category', category).check()
    assert amounts(page) == expected
    expect(page.locator('#calculated-price')).to_have_text(f'{int(expected[0]):,.2f}')
    # Every percentage uses the single original reference price.
    page.locator('#original-price').fill('2000')
    assert amounts(page) == [str(int(value) * 2) for value in expected]
    expect(page.locator('#pricing-forecast-context')).to_contain_text('간편')
    results(page)
    expect(page.locator('#result-price')).to_have_text(f'{int(expected[0]) * 2:,.2f}')
    assert scenario(page)['manual_price'] == '300'


@pytest.mark.parametrize('category', ['api_self', 'domestic_essential', 'own_injectable_pediatric'])
def test_supply_selection_automatically_applies_five_plus_five_years_without_extra_checks(page, category):
    setup_automatic(page)
    condition(page, 'own_data').uncheck()
    condition(page, 'dmf').uncheck()
    condition(page, 'supply_category', category).check()
    assert amounts(page) == ['680'] * 10
    for field in ['supply_eligible', 'supply_extension', 'supply_detail_eligible']:
        expect(condition(page, field)).to_have_count(0)
    assert '연장' in page.locator('[data-pricing-year="6"]').get_attribute('title')
    assert '연장' in page.locator('#pricing-forecast-summary').inner_text()
    condition(page, 'supply_category', 'none').check()
    assert amounts(page) == ['290'] * 10


@pytest.mark.parametrize(('criteria', 'tail'), [(2, '450'), (1, '360'), (0, '290')])
def test_simple_general_post_bonus_price_uses_current_basic_criteria(page, criteria, tail):
    setup_automatic(page)
    if criteria < 2:
        condition(page, 'dmf').uncheck()
    if criteria == 0:
        condition(page, 'own_data').uncheck()
    condition(page, 'general_category', 'improved').check()
    assert amounts(page) == ['700'] + [tail] * 9


def test_old_detailed_conditions_remain_in_json_but_cannot_block_simplified_pricing(page, tmp_path):
    setup_automatic(page)
    payload = save_file(page, tmp_path / 'before-simple.json')
    old = payload['scenarios'][0]['pricing_conditions']
    old.pop('model_id', None)
    old.update({
        'general_category': 'improved', 'general_subtype': '', 'general_base': None,
        'general_cap': None, 'general_trigger_date': '', 'general_recognized': False,
        'general_first_listed': False, 'general_dose_equivalent': False,
        'general_long_extension': True, 'migration_review': '이전 상세조건 확인 필요',
    })
    open_file(page, {'name': 'old-details.json', 'mimeType': 'application/json', 'buffer': json.dumps(payload, ensure_ascii=False).encode('utf-8')})
    expect(page.locator('#calculated-price')).to_have_text('700.00')
    assert amounts(page) == ['700'] + ['450'] * 9
    assert scenario(page)['pricing_conditions']['model_id'] == 'simplified-v1'
    assert scenario(page)['pricing_conditions']['general_long_extension'] is True
    assert scenario(page)['pricing_conditions']['general_base'] is None
    path = tmp_path / 'simplified-saved.json'
    saved = save_file(page, path)
    assert saved['scenarios'][0]['manual_price'] == '300'
    assert saved['scenarios'][0]['pricing_conditions']['general_long_extension'] is True
    mode(page, 'manual')
    expect(page.locator('#manual-price')).to_have_value('300')
    results(page)
    expect(page.locator('#result-price')).to_have_text('300.00')


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


def comparison_cell(page, field, scenario_id):
    return page.locator(f'#comparison-body tr[data-comparison-field="{field}"] td[data-scenario-id="{scenario_id}"]')


def comparison_chart(page, scenario_id):
    return page.locator(f'.comparison-price-chart[data-scenario-id="{scenario_id}"]')


def comparison_year(page, scenario_id, year):
    return page.locator(f'[data-comparison-year="{year}"][data-scenario-id="{scenario_id}"]')


def test_comparison_year_previews_start_at_one_and_update_only_their_own_scenario(page, tmp_path):
    setup_automatic(page, company='innovative', count='ge14')
    condition(page, 'company_eligible').check()
    condition(page, 'domestic_extension').check()
    page.locator('[data-pricing-year="5"]').click()
    first_id = scenario(page)['id']
    page.once('dialog', lambda dialog: dialog.accept('두 번째 비교안'))
    page.locator('#clone-scenario').click()
    page.locator('#original-price').fill('2000')
    page.locator('#batch-labor').fill('3000000')
    second_id = scenario(page)['id']
    before = project(page)
    assert [item['pricing_conditions']['selected_year'] for item in before['scenarios']] == [5, 5]
    comparison(page)
    expect(comparison_cell(page, 'price', first_id)).to_have_text('600.00')
    expect(comparison_cell(page, 'price', second_id)).to_have_text('1,200.00')
    expect(comparison_cell(page, 'cost_rate', first_id)).to_have_text('8.3%')
    expect(comparison_cell(page, 'cost_rate', second_id)).to_have_text('5.0%')
    for scenario_id, cost in [(first_id, '50'), (second_id, '60')]:
        expect(comparison_chart(page, scenario_id).locator('[data-comparison-year]')).to_have_count(10)
        expect(comparison_year(page, scenario_id, 1)).to_have_attribute('aria-pressed', 'true')
        expect(comparison_chart(page, scenario_id).locator('.comparison-cost-line')).to_have_attribute('data-cost', cost)
    comparison_year(page, first_id, 5).click()
    expect(comparison_cell(page, 'price', first_id)).to_have_text('383.00')
    expect(comparison_cell(page, 'cost_rate', first_id)).to_have_text('13.1%')
    expect(comparison_cell(page, 'composition', first_id).locator('[data-chart-part="rate"]')).to_have_text('13.1%')
    expect(comparison_cell(page, 'price', second_id)).to_have_text('1,200.00')
    expect(comparison_cell(page, 'cost_rate', second_id)).to_have_text('5.0%')
    comparison_year(page, second_id, 6).click()
    expect(comparison_cell(page, 'price', second_id)).to_have_text('765.00')
    expect(comparison_cell(page, 'cost_rate', second_id)).to_have_text('7.8%')
    expect(comparison_cell(page, 'price', first_id)).to_have_text('383.00')
    expect(comparison_year(page, first_id, 5)).to_have_attribute('aria-pressed', 'true')
    assert project(page) == before
    assert save_file(page, tmp_path / 'comparison-preview.json') == before
    page.locator('#tab-button-input').click()
    expect(page.locator('#selected-pricing-year')).to_have_text('선택 연차: 5년차')
    expect(page.locator('#calculated-price')).to_have_text('765.00')
    select_scenario(page, first_id)
    expect(page.locator('#selected-pricing-year')).to_have_text('선택 연차: 5년차')
    expect(page.locator('#calculated-price')).to_have_text('383.00')


@pytest.mark.parametrize('manual_price', ['300', '0', '25'])
def test_manual_comparison_forecast_has_ten_flat_prices_and_visible_cost_reference_without_dates(page, manual_price):
    setup_base(page)
    add_material(page)
    page.locator('#manual-price').fill(manual_price)
    current = scenario(page)
    assert current['pricing_conditions']['listing_date'] == ''
    comparison(page)
    chart = comparison_chart(page, current['id'])
    bars = chart.locator('[data-comparison-year]')
    expect(bars).to_have_count(10)
    assert bars.evaluate_all('nodes => nodes.map(node => node.dataset.amount)') == [manual_price] * 10
    line = chart.locator('.comparison-cost-line')
    expect(line).to_have_attribute('data-cost', '50')
    chart_box = chart.bounding_box()
    line_box = line.bounding_box()
    assert chart_box['y'] <= line_box['y'] <= chart_box['y'] + chart_box['height']
    comparison_year(page, current['id'], 7).click()
    expect(comparison_cell(page, 'price', current['id'])).to_have_text(f'{int(manual_price):,.2f}')
    expect(comparison_cell(page, 'cost_rate', current['id'])).to_have_text('계산 불가' if manual_price == '0' else '200.0%' if manual_price == '25' else '16.7%')
    assert scenario(page) == current
    assert 'NaN' not in chart.inner_text()
    assert 'Infinity' not in chart.inner_text()
    assert 'NaN' not in (chart.get_attribute('style') or '')


def test_comparison_incomplete_automatic_forecast_shows_guidance_and_no_false_zero_bars(page):
    setup_automatic(page)
    page.locator('#original-price').fill('')
    current = scenario(page)
    comparison(page)
    chart = comparison_chart(page, current['id'])
    expect(chart.locator('[data-comparison-year]')).to_have_count(0)
    expect(chart).to_contain_text('입력')
    expect(comparison_cell(page, 'price', current['id'])).to_have_text('계산 불가')
    expect(comparison_cell(page, 'total_cost', current['id'])).to_have_text('50.00')
    expect(comparison_cell(page, 'cost_rate', current['id'])).to_have_text('계산 불가')
    assert 'NaN' not in chart.inner_text()
    assert 'Infinity' not in chart.inner_text()
