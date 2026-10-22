"""Scenario-owned product information, legacy files, comparison and printing."""
import copy
import json
import subprocess
import xml.etree.ElementTree as ET

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    add_material, comparison, new_project, open_file, project, save_file,
    scenario, select_scenario, setup_base,
)
from web.tests.test_scenario_reorder import native_drag
from web.tests.test_tabs_print import clone, four_scenarios


def fill_product(page, name, notes):
    page.locator('#product-name').fill(name)
    page.locator('#product-notes').fill(notes)


def product_header(page, scenario_id):
    return page.locator(f'#comparison-head th[data-scenario-id="{scenario_id}"]')


def test_product_edits_are_independent_after_clone_and_switching(page):
    setup_base(page)
    add_material(page)
    fill_product(page, '제품 A', '정제 20mg · A 비고')
    original = copy.deepcopy(scenario(page))
    second = clone(page, '제품 B 검토안')
    expect(page.locator('#product-name')).to_have_value('제품 A')
    expect(page.locator('#product-notes')).to_have_value(original['product']['notes'])
    fill_product(page, '제품 B', '캡슐 40mg · B 비고')
    assert next(s for s in project(page)['scenarios'] if s['id'] == original['id']) == original
    select_scenario(page, original['id'])
    expect(page.locator('#product-name')).to_have_value('제품 A')
    expect(page.locator('#product-notes')).to_have_value('정제 20mg · A 비고')
    assert '제품 A' in page.title()
    select_scenario(page, second)
    expect(page.locator('#product-name')).to_have_value('제품 B')
    expect(page.locator('#product-notes')).to_have_value('캡슐 40mg · B 비고')
    assert '제품 B' in page.title()


def test_blank_product_values_do_not_fall_back_to_another_scenario_and_survive_reload(page):
    setup_base(page)
    fill_product(page, 'A 이름 유지', 'A 비고 유지')
    first = scenario(page)['id']
    second = clone(page, '빈 제품명 검토')
    fill_product(page, '', '')
    expected = project(page)
    page.reload()
    page.wait_for_function('Boolean(window.PharmaCostApp)')
    assert project(page) == expected
    expect(page.locator('#product-name')).to_have_value('')
    expect(page.locator('#product-notes')).to_have_value('')
    select_scenario(page, first)
    expect(page.locator('#product-name')).to_have_value('A 이름 유지')
    select_scenario(page, second)
    expect(page.locator('#product-name')).to_have_value('')
    assert 'product' not in project(page)


def test_distinct_product_text_survives_json_and_uses_active_product_filename(page, tmp_path):
    setup_base(page)
    fill_product(page, 'A 제품', 'A 비고')
    first = scenario(page)['id']
    second = clone(page, '다른 제품 검토')
    fill_product(page, 'B 제품', 'B 비고')
    expected = project(page)
    with page.expect_download() as download:
        page.locator('#save-project').click()
    assert download.value.suggested_filename == 'B 제품.json'
    filename = tmp_path / 'distinct-products.json'
    download.value.save_as(filename)
    assert json.loads(filename.read_text()) == expected
    new_project(page)
    open_file(page, filename)
    expect(page.locator('#product-name')).to_have_value('B 제품')
    assert project(page) == expected
    select_scenario(page, first)
    expect(page.locator('#product-notes')).to_have_value('A 비고')
    select_scenario(page, second)
    expect(page.locator('#product-notes')).to_have_value('B 비고')


@pytest.mark.parametrize('transport', ['file', 'draft'])
def test_version_four_shared_product_is_preserved_then_becomes_independent(page, tmp_path, transport):
    old = project(page)
    old['schema_version'] = 4
    old['product'] = {'product_name': '기존 공통 제품', 'notes': '기존 비고 20mg'}
    for item in old['scenarios']:
        item.pop('product')
    if transport == 'draft':
        page.evaluate('(value) => localStorage.setItem("pharma-cost-web-draft-v1", value)', json.dumps(old, ensure_ascii=False))
        page.reload()
        page.wait_for_function('Boolean(window.PharmaCostApp)')
    else:
        filename = tmp_path / 'v4.json'
        filename.write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
        open_file(page, filename)
    expect(page.locator('#product-name')).to_have_value('기존 공통 제품')
    loaded = project(page)
    assert loaded['schema_version'] == 5
    assert loaded['profit_analysis'] == old['profit_analysis']
    for original, migrated in zip(old['scenarios'], loaded['scenarios']):
        assert migrated['product'] == old['product']
        assert {key: value for key, value in migrated.items() if key != 'product'} == original
    fill_product(page, '활성 시나리오만 변경', '활성 비고')
    other = next(s for s in loaded['scenarios'] if s['id'] != loaded['active_scenario_id'])
    select_scenario(page, other['id'])
    expect(page.locator('#product-name')).to_have_value('기존 공통 제품')
    expect(page.locator('#product-notes')).to_have_value('기존 비고 20mg')
    saved = save_file(page, tmp_path / 'migrated-products.json')
    assert len({s['product']['product_name'] for s in saved['scenarios']}) == 2


@pytest.mark.parametrize('width', [390, 1440])
def test_comparison_headers_show_each_product_as_text_and_reorder_with_scenarios(page, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    setup_base(page)
    fill_product(page, '<제품 A>', 'A 비고 <img src=x onerror=alert(1)>')
    first = scenario(page)['id']
    second = clone(page, '제품 B 검토안')
    fill_product(page, '제품 B', 'B 비고')
    comparison(page)
    expect(product_header(page, first).locator('.comparison-product-name')).to_have_text('<제품 A>')
    expect(product_header(page, first).locator('.comparison-product-notes')).to_contain_text('<img')
    expect(product_header(page, first).locator('img')).to_have_count(0)
    expect(product_header(page, second).locator('.comparison-product-name')).to_have_text('제품 B')
    heading = product_header(page, second)
    assert heading.locator('.comparison-scenario-name').evaluate('node => getComputedStyle(node).fontSize') == heading.evaluate('node => getComputedStyle(node).fontSize')
    before = {s['id']: s['product'] for s in project(page)['scenarios']}
    native_drag(page, second, first)
    expect(page.locator('#comparison-head .comparison-product-name')).to_have_text(['제품 B', '<제품 A>'])
    assert {s['id']: s['product'] for s in project(page)['scenarios']} == before
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    if width == 1440:
        page.screenshot(path='/tmp/scenario-product-comparison.png', full_page=True)


def test_four_distinct_products_and_notes_print_on_one_page(page, tmp_path):
    ids = four_scenarios(page, detailed_api=True)
    for index, scenario_id in enumerate(ids, start=1):
        select_scenario(page, scenario_id)
        fill_product(page, f'검토제품 {index}', f'개별비고 {index} · 20mg')
    comparison(page)
    before = project(page)
    page.emulate_media(media='print')
    filename = tmp_path / 'individual-products.pdf'
    page.pdf(path=str(filename), prefer_css_page_size=True, print_background=True)
    output = subprocess.run(['pdftotext', '-bbox', str(filename), '-'], check=True, capture_output=True, text=True).stdout
    root = ET.fromstring(output)
    ns = {'x': 'http://www.w3.org/1999/xhtml'}
    assert len(root.findall('.//x:page', ns)) == 1
    text = ' '.join(node.text or '' for node in root.findall('.//x:word', ns))
    for index in range(1, 5):
        assert f'검토제품 {index}' in text
        assert f'개별비고 {index}' in text
    assert '공수비' in text
    assert project(page) == before
