'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const E = require('../engine.js');

function material(overrides = {}) {
  return E.makeMaterial({ amount: '20', price: '1000000', ...overrides });
}
function scenario(overrides = {}) {
  return E.makeScenario({ batch_size: '100000', yield_percent: '100', manual_price: '300', materials: [material()], ...overrides });
}
function equal(value, expected) {
  assert.ok(value !== null, 'Expected a calculated Decimal value');
  assert.ok(value.eq(expected), `${value.toString()} differs from ${expected}`);
}
function errors(result, field) { return result.issues.filter(issue => issue.path === field && issue.severity === 'error'); }

test('API 20mg at 1,000,000 KRW/kg is 20 KRW/T', () => {
  const result = E.calculate(scenario());
  equal(result.rows[0].unit_cost, '20');
  equal(result.api_unit, '20');
  equal(result.api_batch, '2000000');
  equal(result.total_cost, '20');
});

test('100 KRW theoretical raw at 80% yield becomes 125 KRW/T', () => {
  const result = E.calculate(scenario({ materials: [material({ amount: '100' })], yield_percent: '80' }));
  equal(result.raw_batch, '10000000');
  equal(result.raw_unit, '125');
  // Cost actually used in a batch is unchanged; loss changes the unit denominator.
  equal(result.rows[0].batch_cost, '10000000');
});

test('packaging 300 KRW for 30T equals 10 KRW/T', () => {
  equal(E.calculate(scenario({ batch_size: '30', batch_packaging: '300', materials: [] })).packaging_unit, '10');
});

test('labor 2,000,000 KRW for a 100,000T batch equals 20 KRW/T', () => {
  equal(E.calculate(scenario({ batch_labor: '2000000' })).labor_unit, '20');
});

test('fixed costs also divide by batch multiplied by yield', () => {
  const result = E.calculate(scenario({ yield_percent: '80', batch_packaging: '1000000', batch_labor: '2000000' }));
  equal(result.packaging_unit, '12.5');
  equal(result.labor_unit, '25');
  equal(result.batch_total, '5000000');
  equal(result.total_cost, '62.5');
});

test('60 KRW cost and 300 KRW price is 20 percent', () => {
  const result = E.calculate(scenario({ batch_packaging: '2000000', batch_labor: '2000000' }));
  equal(result.total_cost, '60');
  equal(result.cost_rate, '20');
  equal(result.target_gap, '0');
  equal(result.required_saving, '0');
});

test('75 cost with 300 price and 20 percent target requires 15 savings', () => {
  const result = E.calculate(scenario({ materials: [material({ amount: '75' })] }));
  equal(result.total_cost, '75');
  equal(result.allowed_cost, '60');
  equal(result.required_saving, '15');
  equal(result.target_gap, '5');
});

test('multiple APIs add independently of excipients', () => {
  const result = E.calculate(scenario({ materials: [material(), material({ amount: '10', price: '2000000' }), material({ kind: 'excipient', amount: '100', price: '100000' })] }));
  equal(result.api_unit, '40');
  equal(result.excipient_unit, '10');
  equal(result.raw_unit, '50');
});

for (const [unit, price, exchange] of [['krw_g', '1000', null], ['krw_kg', '1000000', null], ['usd_g', '1', '1000'], ['usd_kg', '1000', '1000']]) {
  test(`unit conversion ${unit} is correct`, () => {
    const result = E.calculate(scenario({ exchange_rate: exchange, materials: [material({ price_unit: unit, price })] }));
    equal(result.rows[0].unit_cost, '20');
  });
}

test('foreign prices use shared exchange rate and quantity', () => {
  const result = E.calculate(scenario({ exchange_rate: '1350', materials: [material({ amount: '7.25', price: '123.45', price_unit: 'usd_kg' })] }));
  equal(result.api_unit, '1.208266875');
});

test('100 percent yield produces the unadjusted costs', () => {
  const result = E.calculate(scenario({ yield_percent: '100' }));
  equal(result.api_unit, '20');
});

test('zero valid money and zero raw amount stay valid zero costs', () => {
  const result = E.calculate(scenario({ materials: [material({ amount: '0', price: '0' })] }));
  equal(result.total_cost, '0');
  equal(result.cost_rate, '0');
  assert.equal(result.issues.filter(issue => issue.severity === 'error').length, 0);
});

for (const value of [null, '', '0', '-1', '100.1', 'abc', 'NaN', 'Infinity', '1,2']) {
  test(`invalid yield ${JSON.stringify(value)} does not produce completed costs`, () => {
    const result = E.calculate(scenario({ yield_percent: value }));
    assert.equal(result.raw_unit, null);
    assert.equal(result.total_cost, null);
    assert.equal(result.cost_rate, null);
    equal(result.raw_batch, '2000000');
    assert.ok(errors(result, 'yield_percent').length);
  });
}

for (const value of [null, '', '0', '-1', '1.5', 'abc']) {
  test(`invalid batch ${JSON.stringify(value)} is rejected`, () => {
    const result = E.calculate(scenario({ batch_size: value }));
    assert.equal(result.total_cost, null);
    assert.ok(errors(result, 'batch_size').length);
  });
}

for (const field of ['amount', 'price']) {
  for (const value of [null, '', '-1', 'abc']) {
    test(`missing/invalid raw ${field} ${JSON.stringify(value)} keeps incomplete sums unknown`, () => {
      const row = material({ [field]: value });
      const result = E.calculate(scenario({ materials: [row] }));
      assert.equal(result.rows[0].unit_cost, null);
      assert.equal(result.api_unit, null);
      assert.equal(result.raw_unit, null);
      assert.equal(result.total_cost, null);
      assert.ok(errors(result, `materials.${row.id}.${field}`).length);
    });
  }
}

test('valid group subtotal is shown without presenting incomplete total as zero', () => {
  const result = E.calculate(scenario({ materials: [material(), material({ kind: 'excipient', price: null })] }));
  equal(result.api_unit, '20');
  assert.equal(result.excipient_unit, null);
  assert.equal(result.raw_unit, null);
  assert.equal(result.total_cost, null);
});

for (const value of [null, '', '0', '-5', 'abc']) {
  test(`USD missing/invalid exchange ${JSON.stringify(value)} blocks its calculation`, () => {
    const result = E.calculate(scenario({ exchange_rate: value, materials: [material({ price_unit: 'usd_kg' })] }));
    assert.equal(result.raw_unit, null);
    assert.ok(errors(result, 'exchange_rate').length);
  });
}

test('exchange rate is optional for KRW-only rows', () => {
  const result = E.calculate(scenario({ exchange_rate: null }));
  equal(result.total_cost, '20');
  assert.equal(errors(result, 'exchange_rate').length, 0);
});

test('invalid inactive exchange is highlighted but cannot change KRW costs', () => {
  const result = E.calculate(scenario({ exchange_rate: '-1' }));
  equal(result.total_cost, '20');
  assert.ok(errors(result, 'exchange_rate').length);
});

for (const value of [null, '', '0']) {
  test(`absent or zero price ${JSON.stringify(value)} keeps cost and does not give a rate`, () => {
    const result = E.calculate(scenario({ manual_price: value }));
    equal(result.total_cost, '20');
    assert.equal(result.cost_rate, null);
    assert.equal(result.allowed_cost, null);
    assert.equal(result.required_saving, null);
    assert.equal(result.pricing.source, '사용자 입력값');
  });
}

test('original price is recorded independently and never becomes the denominator', () => {
  const result = E.calculate(scenario({ original_price: '600', manual_price: '300' }));
  equal(result.cost_rate, new E.Decimal('20').div('300').times(100));
});

test('cost rate above 100 is not clamped; negative target gap is allowed', () => {
  const result = E.calculate(scenario({ manual_price: '10', target_rate: '300' }));
  equal(result.cost_rate, '200');
  equal(result.target_gap, '-100');
  equal(result.required_saving, '0');
});

test('post-addition price uses the same cost and independently validated price', () => {
  const result = E.calculate(scenario({ manual_price: '100', post_price: '50' }));
  equal(result.cost_rate, '20');
  equal(result.post_rate, '40');
});

test('invalid fixed cost does not produce an apparently complete total', () => {
  const result = E.calculate(scenario({ batch_packaging: '-1' }));
  equal(result.raw_unit, '20');
  assert.equal(result.packaging_unit, null);
  assert.equal(result.total_cost, null);
  assert.ok(errors(result, 'batch_packaging').length);
});

test('no intermediate display rounding takes place', () => {
  const result = E.calculate(scenario({ batch_size: '3', yield_percent: '50', materials: [material({ amount: '0.12345678901234567890123456789', price: '1.2345678901234567890123456789', price_unit: 'krw_g' })], batch_packaging: '1', batch_labor: '1' }));
  const expectedRaw = new E.Decimal('0.12345678901234567890123456789').times('1.2345678901234567890123456789').div('1000').div('0.5');
  equal(result.raw_unit, expectedRaw);
  equal(result.total_cost, expectedRaw.plus(new E.Decimal(1).div('1.5')).plus(new E.Decimal(1).div('1.5')));
  assert.ok(result.total_cost.toString().length > 100);
});

test('properly grouped comma numbers parse while malformed comma digits do not', () => {
  equal(E.parseNumber('1,000,000'), '1000000');
  equal(E.parseNumber(' 1,234.56 '), '1234.56');
  equal(E.parseNumber('12,345e2'), '1234500');
  assert.equal(E.parseNumber(''), null);
  for (const invalid of ['1,2', '1,0000', '1000,000', '1,234.5,6']) assert.throws(() => E.parseNumber(invalid), /천 단위/);
});

test('numeric lengths/exponents are bounded and special numeric strings are rejected', () => {
  for (const invalid of ['1'.repeat(129), '1e1001', '1e-1001', '0xFF', 'NaN', 'Infinity', '1e999999999999999999999999']) assert.throws(() => E.parseNumber(invalid));
  equal(E.parseNumber('1e1000'), '1e1000');
  equal(E.parseNumber('1e-1000'), '1e-1000');
});

test('scenario cloning changes IDs and deeply preserves the original', () => {
  const project = E.createExampleProject();
  const original = JSON.stringify(project.scenarios[0]);
  const cloned = E.cloneScenario(project, project.scenarios[0].id, '절감안');
  assert.notEqual(cloned.id, project.scenarios[0].id);
  assert.notEqual(cloned.materials[0].id, project.scenarios[0].materials[0].id);
  cloned.materials[0].price = '1';
  cloned.pricing_flags.push('improved');
  cloned.yield_percent = '80';
  assert.equal(JSON.stringify(project.scenarios[0]), original);
  assert.equal(project.active_scenario_id, cloned.id);
  assert.equal(project.scenarios.length, 3);
});

test('JSON save/load preserves all pricing conditions and independent scenarios', () => {
  const project = E.createExampleProject();
  E.cloneScenario(project, project.active_scenario_id, '수율 시나리오').yield_percent = '98.25';
  project.scenarios[0].pricing_flags = ['improved', 'api_self'];
  const text = E.serializeProject(project);
  const loaded = E.parseProject(text);
  assert.deepEqual(loaded, project);
  equal(E.calculate(loaded.scenarios[0]).total_cost, '80');
  assert.equal(loaded.format, 'pharma-cost-web-project');
  assert.equal(loaded.schema_version, 1);
});

test('example compares 80 KRW basic and 60 KRW API savings while selecting original', () => {
  const project = E.createExampleProject();
  assert.equal(project.scenarios.length, 2);
  assert.equal(project.active_scenario_id, project.scenarios[0].id);
  equal(E.calculate(project.scenarios[0]).total_cost, '80');
  equal(E.calculate(project.scenarios[1]).total_cost, '60');
  equal(E.calculate(project.scenarios[1]).required_saving, '0');
});

test('incomplete project numeric strings can be saved without inventing costs', () => {
  const project = E.makeProject();
  project.scenarios[0].batch_size = '';
  project.scenarios[0].materials.push(E.makeMaterial());
  assert.deepEqual(E.parseProject(E.serializeProject(project)), project);
  assert.equal(E.calculate(project.scenarios[0]).total_cost, null);
});

test('invalid numeric raw input is preserved and explained rather than silently saved', () => {
  const project = E.createExampleProject();
  project.scenarios[0].materials[0].amount = '아직 몰라요';
  assert.throws(() => E.serializeProject(project), /실제 투입량.*올바른 숫자/);
  assert.equal(project.scenarios[0].materials[0].amount, '아직 몰라요');
});

test('JSON malformed, version, unknown fields and legacy formats are clearly rejected', () => {
  assert.throws(() => E.parseProject('{broken'), /JSON 문법/);
  assert.throws(() => E.parseProject('null'), /프로젝트 객체/);
  assert.throws(() => E.parseProject(JSON.stringify({ schema_version: 1 })), /기존 데스크톱 JSON/);
  const project = E.createExampleProject();
  project.schema_version = 2;
  assert.throws(() => E.parseProject(JSON.stringify(project)), /지원하지 않는 파일 버전/);
  project.schema_version = 1;
  project.product.project_name = 'Legacy field';
  assert.throws(() => E.parseProject(JSON.stringify(project)), /지원하지 않는 항목/);
});

test('UTF-8 BOM JSON is supported', () => {
  const project = E.createExampleProject();
  assert.deepEqual(E.parseProject('\uFEFF' + E.serializeProject(project)), project);
});

test('duplicate IDs and inactive missing references are rejected', () => {
  const project = E.createExampleProject();
  const clone = E.cloneScenario(project, project.active_scenario_id);
  clone.id = project.scenarios[0].id;
  assert.throws(() => E.serializeProject(project), /ID가 중복/);
  clone.id = 'new-id';
  project.active_scenario_id = 'missing';
  assert.throws(() => E.serializeProject(project), /현재 시나리오를 찾을 수/);
});

test('unsupported material units cannot silently use another conversion', () => {
  const row = material({ price_unit: 'krw_each' });
  const result = E.calculate(scenario({ materials: [row] }));
  assert.equal(result.total_cost, null);
  assert.ok(errors(result, `materials.${row.id}.price_unit`).length);
  const project = E.makeProject({ scenarios: [scenario({ materials: [row] })] });
  assert.throws(() => E.serializeProject(project), /단가 단위의 선택값/);
});

test('unverified official pricing never falls back to original or manual price', () => {
  const result = E.calculate(scenario({ pricing_mode: 'official', original_price: '600', manual_price: '300', company_type: 'innovative', pricing_flags: ['improved'] }));
  equal(result.total_cost, '20');
  assert.equal(result.pricing.amount, null);
  assert.equal(result.pricing.status, 'unverified');
  assert.equal(result.cost_rate, null);
  assert.equal(result.required_saving, null);
});

test('rule extension must be explicitly verified with regulation and basis date', () => {
  const data = scenario({ pricing_mode: 'official' });
  for (const rules of [{}, { verified: false, calculate: () => ({ amount: '100' }) }, { verified: true, calculate: () => ({ amount: '100' }) }]) assert.equal(E.assessPricing(data, rules).status, 'unverified');
  // This is a synthetic test rule; it is never shipped as an official price rule.
  const rules = { verified: true, regulation: '시험 규칙', basis_date: '2026-01-01', links: ['https://example.test/rule'], calculate: () => ({ amount: '100', steps: ['시험 계산'] }) };
  const result = E.calculate(data, rules);
  equal(result.cost_rate, '20');
  assert.equal(result.pricing.regulation, '시험 규칙');
  assert.equal(result.pricing.basis_date, '2026-01-01');
  assert.deepEqual(result.pricing.steps, ['시험 계산']);
});

test('failed external official rule cannot fall back or mutate the scenario', () => {
  const data = scenario({ pricing_mode: 'official' });
  const before = JSON.stringify(data);
  const rules = { verified: true, regulation: '시험 규칙', basis_date: '2026-01-01', calculate: value => { value.materials[0].amount = '999'; throw new Error('조건 오류'); } };
  const result = E.calculate(data, rules);
  assert.equal(result.pricing.amount, null);
  assert.equal(result.cost_rate, null);
  assert.equal(JSON.stringify(data), before);
  assert.match(result.issues.find(issue => issue.path === 'pricing_mode').message, /조건 오류/);
});

test('browser UMD runs with bundled decimal and has no CommonJS requirement', () => {
  const sandbox = { console, Date, Math, crypto: { randomUUID: () => 'test-id' } };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../vendor/decimal.js'), 'utf8'), sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../engine.js'), 'utf8'), sandbox);
  assert.ok(sandbox.PharmaCost);
  assert.equal(sandbox.PharmaCost.calculate(sandbox.PharmaCost.createExampleProject().scenarios[0]).total_cost.toString(), '80');
});
