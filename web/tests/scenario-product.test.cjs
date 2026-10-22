'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../engine.js');
const F = require('../forecast.js');

function legacyProject(version) {
  const project = E.createExampleProject();
  project.product = { product_name: '이전 공통 제품 <A>', notes: '20mg 정제\n검토 비고' };
  project.schema_version = version;
  for (const scenario of project.scenarios) {
    delete scenario.product;
    if (version < 3) delete scenario.sales_forecast;
    if (version === 1) delete scenario.pricing_conditions;
    if (version === 3) scenario.sales_forecast = { use_custom: false, sales: Array(10).fill(null) };
  }
  if (version < 3) delete project.profit_analysis;
  if (version === 3) project.profit_analysis = { enabled: true, years: 3, common_sales: ['1000', ...Array(9).fill(null)] };
  return project;
}

test('new scenarios own independent product information and copy constructor input', () => {
  const product = { product_name: '제품 A', notes: '정제 20mg' };
  const a = E.makeScenario({ product });
  const b = E.makeScenario();
  product.product_name = '외부 변경';
  a.product.notes = 'A의 새 비고';
  assert.deepEqual(a.product, { product_name: '제품 A', notes: 'A의 새 비고' });
  assert.deepEqual(b.product, { product_name: '', notes: '' });
  const p = E.makeProject({ scenarios: [a] });
  a.product.product_name = '원본 변경';
  assert.equal(p.scenarios[0].product.product_name, '제품 A');
  assert.equal(Object.hasOwn(p, 'product'), false);
});

test('cloning retains product information and edits never alter the original', () => {
  const project = E.createExampleProject();
  const original = structuredClone(project.scenarios[0]);
  const clone = E.cloneScenario(project, original.id, '제품 B안');
  assert.deepEqual(clone.product, original.product);
  clone.product.product_name = '제품 B';
  clone.product.notes = '캡슐 40mg';
  assert.deepEqual(project.scenarios[0], original);
  assert.notDeepEqual(clone.product, original.product);
});

test('distinct Unicode products and multiline notes survive JSON and scenario reordering', () => {
  const p = E.createExampleProject();
  p.scenarios[0].product = { product_name: '<제품 A>', notes: '정제 20mg\nA 비고' };
  p.scenarios[1].product = { product_name: '제품 B 캡슐', notes: '40mg · B 비고' };
  p.scenarios.reverse();
  assert.deepEqual(E.parseProject(E.serializeProject(p)), p);
  assert.equal(E.VERSION, 5);
});

for (const version of [1, 2, 3, 4]) {
  test('version ' + version + ' copies shared product info independently without losing other inputs', () => {
    const old = legacyProject(version);
    const before = JSON.stringify(old);
    const loaded = E.parseProject(before);
    assert.equal(JSON.stringify(old), before);
    assert.equal(loaded.schema_version, 5);
    assert.equal(Object.hasOwn(loaded, 'product'), false);
    loaded.scenarios.forEach((s, index) => {
      assert.deepEqual(s.product, old.product);
      assert.deepEqual(s.materials, old.scenarios[index].materials);
      assert.equal(s.manual_price, old.scenarios[index].manual_price);
      assert.equal(s.name, old.scenarios[index].name);
    });
    if (version === 4) assert.deepEqual(loaded.profit_analysis, old.profit_analysis);
    if (version === 3) assert.deepEqual(loaded.profit_analysis.legacy_amount_forecast.common_sales, old.profit_analysis.common_sales);
    loaded.scenarios[1].product.notes = '독립 수정';
    assert.deepEqual(loaded.scenarios[0].product, old.product);
    assert.deepEqual(E.parseProject(E.serializeProject(loaded)), loaded);
  });
}

test('changing product text leaves existing manufacturing, pricing and profit results unchanged', () => {
  const p = E.createExampleProject();
  p.profit_analysis.enabled = true; p.profit_analysis.years = 1;
  p.profit_analysis.common_quantities[0] = '100000';
  const cost = JSON.stringify(p.scenarios.map(E.calculate));
  const profit = JSON.stringify(F.calculate(p));
  p.scenarios[0].product = { product_name: '새 제품명', notes: '별도 비고' };
  assert.equal(JSON.stringify(p.scenarios.map(E.calculate)), cost);
  assert.equal(JSON.stringify(F.calculate(p)), profit);
});

for (const invalid of [null, {}, { product_name: 12, notes: '' }, { product_name: '', notes: [] }, { product_name: '', notes: '', extra: 'x' }]) {
  test('invalid scenario product info is rejected: ' + JSON.stringify(invalid), () => {
    const p = E.createExampleProject(); p.scenarios[0].product = invalid;
    assert.throws(() => E.parseProject(JSON.stringify(p)), /프로젝트 파일 오류/);
  });
}

test('legacy unknown product fields are rejected rather than silently discarded', () => {
  const p = legacyProject(4); p.product.extra = '보관해야 할 추가 정보';
  assert.throws(() => E.parseProject(JSON.stringify(p)), /지원하지 않는 항목/);
  delete p.product.extra; p.scenarios[0].product = { product_name: '덮어쓰면 안 되는 제품', notes: '' };
  assert.throws(() => E.parseProject(JSON.stringify(p)), /지원하지 않는 항목/);
});
