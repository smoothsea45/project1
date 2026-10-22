'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const E = require('../engine.js');
const F = require('../forecast.js');

function scenario(options = {}) {
  return E.makeScenario({ batch_size: '100000', yield_percent: '100', manual_price: '100', batch_labor: '3000000', ...options });
}
function project(sales = ['1000'], scenarios = [scenario()], options = {}) {
  return E.makeProject({ scenarios, profit_analysis: { enabled: true, years: sales.length, common_quantities: sales.concat(Array(10 - sales.length).fill(null)), ...options } });
}
function equal(value, expected) {
  assert.ok(value !== null && value instanceof E.Decimal, 'Expected an unrounded E.Decimal');
  assert.ok(value.eq(expected), value.toString() + ' differs from ' + expected);
}
function legacy(version) {
  const value = E.createExampleProject();
  value.product = structuredClone(value.scenarios[0].product);
  value.scenarios.forEach(item => { delete item.product; });
  value.schema_version = version;
  delete value.profit_analysis;
  value.scenarios.forEach(item => {
    delete item.sales_forecast;
    if (version === 1) delete item.pricing_conditions;
  });
  return value;
}
function amountProject() {
  const value = E.createExampleProject();
  value.product = structuredClone(value.scenarios[0].product);
  value.scenarios.forEach(item => { delete item.product; });
  value.schema_version = 3;
  value.profit_analysis = { enabled: true, years: 6, common_sales: ['1,000.1234567890123456789', ...Array(9).fill(null)] };
  value.scenarios.forEach((scenario, index) => {
    scenario.sales_forecast = { use_custom: index === 1, sales: [index === 1 ? '0' : null, ...Array(8).fill(null), '1234.56789'] };
  });
  return value;
}

test('1000T SF at price100 and cost30 gives revenue100000 cost30000 profit70000', () => {
  const p = project();
  const before = JSON.stringify(p);
  const r = F.calculate(p);
  assert.equal(r.enabled, true);
  assert.equal(r.years, 1);
  assert.equal(r.baseline_id, p.scenarios[0].id);
  const s = r.scenarios[0];
  equal(s.rows[0].quantity, 1000);
  equal(s.rows[0].sales, 100000);
  equal(s.rows[0].cost_per_unit, 30);
  equal(s.rows[0].price, 100);
  equal(s.rows[0].cost_rate, 30);
  equal(s.rows[0].manufacturing_cost, 30000);
  equal(s.rows[0].profit, 70000);
  equal(s.total_quantity, 1000);
  equal(s.total_sales, 100000);
  equal(s.total_cost, 30000);
  equal(s.total_profit, 70000);
  equal(s.difference_from_baseline, 0);
  assert.equal(s.complete, true);
  assert.deepEqual(r.issues, []);
  assert.equal(JSON.stringify(p), before);
});

test('100000T at price300 and raw cost90 yields exactly 30m revenue, 9m cost and 21m profit KRW', () => {
  const p = project(['100000'], [scenario({ manual_price: '300', batch_labor: '9000000' })]);
  const r = F.calculate(p).scenarios[0];
  equal(r.rows[0].quantity, 100000);
  equal(r.rows[0].sales, 30000000);
  equal(r.rows[0].manufacturing_cost, 9000000);
  equal(r.rows[0].profit, 21000000);
  equal(r.rows[0].cost_rate, 30);
  equal(r.rows[0].cumulative_quantity, 100000);
  equal(r.total_quantity, 100000);
  equal(r.total_profit, 21000000);
});

test('valid zero price produces zero revenue and a loss while only its cost rate stays unavailable', () => {
  const r = F.calculate(project(['1000', '0'], [scenario({ manual_price: '0' })])).scenarios[0];
  equal(r.rows[0].sales, 0);
  equal(r.rows[0].manufacturing_cost, 30000);
  equal(r.rows[0].profit, -30000);
  assert.equal(r.rows[0].cost_rate, null);
  equal(r.rows[1].sales, 0);
  equal(r.rows[1].manufacturing_cost, 0);
  equal(r.rows[1].profit, 0);
  equal(r.total_profit, -30000);
  assert.equal(r.complete, true);
});

test('quantity parser requires a nonnegative integer while preserving exact large integer precision', () => {
  assert.equal(E.parseQuantity(null), null);
  assert.equal(E.parseQuantity(''), null);
  equal(E.parseQuantity('0'), 0);
  equal(E.parseQuantity('1,000'), 1000);
  equal(E.parseQuantity('123456789012345678901234567890'), '123456789012345678901234567890');
  equal(E.parseQuantity('100.0'), 100);
  for (const value of ['1.1', '0.5', '-1', 'NaN', '1,2', 100, '1e-1']) assert.throws(() => E.parseQuantity(value));
});

test('manual pricing is constant through ten years without a listing date', () => {
  const s = scenario({ manual_price: '123.456789', pricing_conditions: { selected_year: 8, listing_date: '' } });
  const r = F.calculate(project(Array(10).fill('1000'), [s]));
  assert.equal(r.scenarios[0].rows.length, 10);
  r.scenarios[0].rows.forEach(row => equal(row.price, '123.456789'));
  assert.equal(s.pricing_conditions.selected_year, 8);
  assert.equal(s.pricing_conditions.listing_date, '');
});

test('official forecasts use each actual yearly price and preserve the selected pricing year', () => {
  const s = scenario({ pricing_mode: 'official', original_price: '1000', pricing_conditions: { listing_date: '2027-01-01', general_category: 'improved', own_data: true, dmf: true, selected_year: 8 } });
  const before = JSON.stringify(s);
  const r = F.calculate(project(Array(8).fill('1000'), [s])).scenarios[0];
  equal(r.rows[0].price, 700);
  equal(r.rows[3].price, 700);
  equal(r.rows[4].price, 450);
  equal(r.rows[7].price, 450);
  equal(r.rows[0].manufacturing_cost, 30000);
  equal(r.rows[0].sales, 700000);
  equal(r.rows[4].manufacturing_cost, 30000);
  equal(r.rows[4].sales, 450000);
  assert.ok(r.rows[4].profit.lt(r.rows[3].profit));
  assert.equal(JSON.stringify(s), before);
});

test('cost above price produces a negative profit and cumulative loss without clamping', () => {
  const r = F.calculate(project(['1000', '2000'], [scenario({ manual_price: '20' })])).scenarios[0];
  equal(r.rows[0].cost_rate, 150);
  equal(r.rows[0].manufacturing_cost, 30000);
  equal(r.rows[0].profit, -10000);
  equal(r.rows[1].profit, -20000);
  equal(r.rows[1].cumulative_profit, -30000);
  equal(r.total_profit, -30000);
});

test('explicit zero SF calculates zero while blank SF remains incomplete', () => {
  const r = F.calculate(project(['0', '', '200'])).scenarios[0];
  equal(r.rows[0].sales, 0);
  equal(r.rows[0].manufacturing_cost, 0);
  equal(r.rows[0].profit, 0);
  assert.equal(r.rows[1].sales, null);
  assert.equal(r.rows[1].profit, null);
  assert.equal(r.rows[1].cumulative_profit, null);
  equal(r.rows[2].profit, 14000);
  assert.equal(r.rows[2].cumulative_profit, null);
  assert.equal(r.total_sales, null);
  assert.equal(r.total_cost, null);
  assert.equal(r.total_profit, null);
  assert.equal(r.complete, false);
});

for (const value of [null, '', '-1', 'abc']) {
  test('missing or invalid price ' + JSON.stringify(value) + ' cannot create a profit, including zero SF', () => {
    const r = F.calculate(project(['1000', '0'], [scenario({ manual_price: value })])).scenarios[0];
    r.rows.forEach(row => {
      assert.equal(row.price, null);
      assert.equal(row.profit, null);
      equal(row.manufacturing_cost, row.year === 1 ? 30000 : 0);
      assert.equal(row.cost_rate, null);
      assert.ok(row.issues.some(issue => issue.path === 'price'));
    });
    assert.equal(r.total_sales, null);
  });
}

test('a genuinely zero manufacturing cost produces full SF as profit', () => {
  const r = F.calculate(project(['500'], [scenario({ batch_labor: '0' })])).scenarios[0];
  equal(r.rows[0].cost_per_unit, 0);
  equal(r.rows[0].manufacturing_cost, 0);
  equal(r.rows[0].profit, 50000);
  equal(r.rows[0].cost_rate, 0);
});

test('incomplete manufacturing cost remains unavailable rather than zero', () => {
  const r = F.calculate(project(['500'], [scenario({ batch_size: null })])).scenarios[0];
  equal(r.rows[0].price, 100);
  assert.equal(r.rows[0].cost_per_unit, null);
  assert.equal(r.rows[0].manufacturing_cost, null);
  assert.equal(r.rows[0].profit, null);
  assert.equal(r.complete, false);
  assert.ok(r.rows[0].issues.some(issue => issue.path === 'cost_per_unit'));
});

for (const value of ['-1', 'NaN', 'Infinity', '1,00', 'abc', 500, '1.5']) {
  test('invalid SF ' + JSON.stringify(value) + ' is explained without calculating a profit', () => {
    const r = F.calculate(project([value])).scenarios[0];
    assert.equal(r.rows[0].sales, null);
    assert.equal(r.rows[0].profit, null);
    assert.ok(r.rows[0].issues.some(issue => issue.message.includes('SF')));
  });
}

test('custom SF falls back to common only for blank entries; explicit zero overrides', () => {
  const s = scenario({ sales_forecast: { use_custom: true, quantities: ['2000', '', '0', '-1', ...Array(6).fill(null)] } });
  const r = F.calculate(project(['1000', '1000', '1000', '1000'], [s])).scenarios[0];
  assert.deepEqual(r.rows.map(row => row.sales_source), ['custom', 'common', 'custom', 'custom']);
  equal(r.rows[0].quantity, 2000);
  equal(r.rows[0].sales, 200000);
  equal(r.rows[1].sales, 100000);
  equal(r.rows[2].sales, 0);
  equal(r.rows[2].profit, 0);
  assert.equal(r.rows[3].sales, null);
  assert.equal(r.rows[3].profit, null);
});

test('turning custom SF off retains its raw entries but uses common SF', () => {
  const s = scenario({ sales_forecast: { use_custom: false, quantities: ['2000', ...Array(9).fill(null)] } });
  const p = project(['1000'], [s]);
  const r = F.calculate(p).scenarios[0];
  equal(r.rows[0].quantity, 1000);
  equal(r.rows[0].sales, 100000);
  assert.equal(r.rows[0].sales_source, 'common');
  assert.equal(p.scenarios[0].sales_forecast.quantities[0], '2000');
});

test('shortening the period keeps hidden values and excludes them from totals', () => {
  const p = project(['100', '200', '300']);
  const before = JSON.stringify(p.profit_analysis.common_quantities);
  p.profit_analysis.years = 1;
  let r = F.calculate(p).scenarios[0];
  assert.equal(r.rows.length, 1);
  equal(r.total_quantity, 100);
  equal(r.total_sales, 10000);
  equal(r.total_profit, 7000);
  p.profit_analysis.years = 3;
  r = F.calculate(p).scenarios[0];
  equal(r.total_quantity, 600);
  equal(r.total_sales, 60000);
  equal(r.total_profit, 42000);
  assert.equal(JSON.stringify(p.profit_analysis.common_quantities), before);
});

test('baseline follows actual scenario order and differences use complete totals', () => {
  const first = scenario({ name: '기본안' });
  const second = scenario({ name: '절감안', batch_labor: '1000000' });
  const p = project(['1000', '2000'], [first, second]);
  let r = F.calculate(p);
  equal(r.scenarios[0].total_profit, 210000);
  equal(r.scenarios[1].total_profit, 270000);
  equal(r.scenarios[1].difference_from_baseline, 60000);
  p.scenarios.reverse();
  r = F.calculate(p);
  assert.equal(r.baseline_id, second.id);
  equal(r.scenarios[0].difference_from_baseline, 0);
  equal(r.scenarios[1].difference_from_baseline, -60000);
  p.scenarios[0].sales_forecast = E.makeSalesForecast({ use_custom: true, quantities: ['abc', ...Array(9).fill(null)] });
  r = F.calculate(p);
  assert.equal(r.scenarios[0].total_profit, null);
  assert.equal(r.scenarios[1].difference_from_baseline, null);
});

test('profit uses full internal precision, without price, rate or money display rounding', () => {
  const p = project(['12345678901234567890123456789'], [scenario({ manual_price: '891', batch_size: '3', yield_percent: '98', batch_labor: '100' })]);
  const cost = E.calculate(p.scenarios[0]).total_cost;
  const r = F.calculate(p).scenarios[0].rows[0];
  const expected = new E.Decimal('12345678901234567890123456789').times(cost);
  equal(r.manufacturing_cost, expected);
  equal(r.profit, new E.Decimal('12345678901234567890123456789').times(891).minus(expected));
  assert.ok(r.manufacturing_cost.toString().length > 100);
});

test('disabled analysis returns no results and cannot affect existing manufacturing calculations', () => {
  const p = project(['-1']);
  p.profit_analysis.enabled = false;
  const before = E.calculate(p.scenarios[0]);
  const r = F.calculate(p);
  assert.equal(r.enabled, false);
  assert.deepEqual(r.scenarios, []);
  assert.deepEqual(r.issues, []);
  equal(E.calculate(p.scenarios[0]).total_cost, before.total_cost);
});

test('analysis calculates costing once per scenario and not at all while disabled', () => {
  let calls = 0;
  const sandbox = { PharmaCost: Object.assign({}, E, { calculate: s => { calls += 1; return E.calculate(s); } }) };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../forecast.js'), 'utf8'), sandbox);
  const p = project(Array(10).fill('1000'), [scenario(), scenario()]);
  assert.equal(sandbox.PharmaProfit.calculate(p).scenarios.length, 2);
  assert.equal(calls, 2);
  p.profit_analysis.enabled = false;
  assert.equal(sandbox.PharmaProfit.calculate(p).scenarios.length, 0);
  assert.equal(calls, 2);
});

test('analysis and scenario constructors own their ten-year arrays', () => {
  assert.equal(E.VERSION, 5);
  const values = ['1000', ...Array(9).fill(null)];
  const a = E.makeProfitAnalysis({ common_quantities: values });
  const b = E.makeProfitAnalysis();
  const c = E.makeSalesForecast({ quantities: values });
  values[0] = '9999';
  assert.equal(a.common_quantities[0], '1000');
  assert.equal(c.quantities[0], '1000');
  a.common_quantities[1] = '20';
  assert.equal(b.common_quantities[1], null);
  assert.deepEqual(E.makeProfitAnalysis(), { enabled: false, years: 8, common_quantities: Array(10).fill(null), legacy_amount_forecast: null });
  assert.deepEqual(E.makeSalesForecast(), { use_custom: false, quantities: Array(10).fill(null) });
  const p = E.makeProject({ profit_analysis: a, scenarios: [scenario({ sales_forecast: c })] });
  a.common_quantities[0] = '2';
  c.quantities[0] = '3';
  assert.equal(p.profit_analysis.common_quantities[0], '1000');
  assert.equal(p.scenarios[0].sales_forecast.quantities[0], '1000');
});

test('scenario cloning copies independent SF values and preserves original inputs', () => {
  const p = project(['1000'], [scenario({ sales_forecast: { use_custom: true, quantities: ['2000', ...Array(9).fill(null)] } })]);
  const original = JSON.stringify(p.scenarios[0]);
  const duplicate = E.cloneScenario(p, p.scenarios[0].id, '복제안');
  assert.deepEqual(duplicate.sales_forecast, p.scenarios[0].sales_forecast);
  duplicate.sales_forecast.quantities[0] = '3000';
  duplicate.sales_forecast.use_custom = false;
  assert.equal(JSON.stringify(p.scenarios[0]), original);
  assert.equal(p.profit_analysis.common_quantities[0], '1000');
});

test('JSON roundtrip keeps disabled custom values, hidden years and exact amount strings', () => {
  const p = project(['1,000,123,456,789,012,345,678,901,234,567,890']);
  p.profit_analysis.common_quantities[9] = '2000';
  p.profit_analysis.enabled = false;
  p.scenarios[0].sales_forecast.quantities[9] = '3500';
  assert.deepEqual(E.parseProject(E.serializeProject(p)), p);
});

for (const version of [1, 2]) {
  test('schema ' + version + ' migrates SF defaults disabled and preserves original raw fields', () => {
    const old = legacy(version);
    const before = JSON.stringify(old);
    const loaded = E.parseProject(before);
    assert.equal(JSON.stringify(old), before);
    assert.equal(loaded.schema_version, E.VERSION);
    assert.deepEqual(loaded.profit_analysis, E.makeProfitAnalysis());
    loaded.scenarios.forEach((s, i) => {
      assert.deepEqual(s.sales_forecast, E.makeSalesForecast());
      assert.equal(s.materials[0].price, old.scenarios[i].materials[0].price);
      assert.equal(s.manual_price, old.scenarios[i].manual_price);
      assert.equal(s.batch_size, old.scenarios[i].batch_size);
    });
    assert.deepEqual(E.parseProject(E.serializeProject(loaded)), loaded);
    equal(E.calculate(loaded.scenarios[0]).total_cost, 80);
    assert.equal(F.calculate(loaded).enabled, false);
  });
}

test('schema 2 detailed pricing migrates its old combination category without dropping fields', () => {
  const old = legacy(2);
  const conditions = old.scenarios[0].pricing_conditions;
  conditions.general_category = 'improved';
  conditions.general_subtype = 'combination';
  delete conditions.model_id;
  const loaded = E.parseProject(JSON.stringify(old));
  assert.equal(loaded.scenarios[0].pricing_conditions.general_category, 'improved_combo');
  assert.equal(loaded.scenarios[0].pricing_conditions.general_subtype, 'combination');
  assert.equal(loaded.scenarios[0].pricing_conditions.model_id, 'simplified-v1');
});

test('schema3 amount SF is archived losslessly instead of being interpreted as quantity', () => {
  const old = amountProject();
  const before = JSON.stringify(old);
  const loaded = E.parseProject(before);
  assert.equal(JSON.stringify(old), before);
  assert.equal(loaded.schema_version, E.VERSION);
  assert.equal(loaded.profit_analysis.enabled, true);
  assert.equal(loaded.profit_analysis.years, 6);
  assert.deepEqual(loaded.profit_analysis.common_quantities, Array(10).fill(null));
  assert.deepEqual(loaded.profit_analysis.legacy_amount_forecast, {
    unit: 'million_krw', common_sales: old.profit_analysis.common_sales,
    scenarios: old.scenarios.map(s => ({ scenario_id: s.id, use_custom: s.sales_forecast.use_custom, sales: s.sales_forecast.sales }))
  });
  loaded.scenarios.forEach((s, i) => {
    assert.equal(s.sales_forecast.use_custom, old.scenarios[i].sales_forecast.use_custom);
    assert.deepEqual(s.sales_forecast.quantities, Array(10).fill(null));
    assert.deepEqual(s.materials, old.scenarios[i].materials);
  });
  assert.equal(F.calculate(loaded).scenarios[0].rows[0].quantity, null);
  assert.equal(F.calculate(loaded).scenarios[0].total_profit, null);
  assert.deepEqual(E.parseProject(E.serializeProject(loaded)), loaded);
});

test('schema3 entirely blank amount SF creates no archive and preserves individual mode', () => {
  const old = amountProject();
  old.profit_analysis.common_sales.fill(null);
  old.scenarios.forEach(s => s.sales_forecast.sales.fill(''));
  const loaded = E.parseProject(JSON.stringify(old));
  assert.equal(loaded.profit_analysis.legacy_amount_forecast, null);
  assert.equal(loaded.profit_analysis.enabled, true);
  assert.equal(loaded.scenarios[1].sales_forecast.use_custom, true);
  assert.deepEqual(loaded.profit_analysis.common_quantities, Array(10).fill(null));
});

test('schema3 an explicit zero amount is retained as an archived amount', () => {
  const old = amountProject();
  old.profit_analysis.common_sales.fill(null);
  old.scenarios.forEach(s => s.sales_forecast.sales.fill(null));
  old.profit_analysis.common_sales[0] = '0';
  const loaded = E.parseProject(JSON.stringify(old));
  assert.equal(loaded.profit_analysis.legacy_amount_forecast.common_sales[0], '0');
  assert.equal(loaded.profit_analysis.common_quantities[0], null);
});

test('schema3 migration rejects unknown or invalid amount fields instead of dropping them', () => {
  const mutations = [
    p => { p.profit_analysis.future_value = '123'; },
    p => { p.profit_analysis.common_sales[9] = '-1'; },
    p => { p.profit_analysis.enabled = 'true'; },
    p => { p.scenarios[0].sales_forecast.future_value = '123'; },
    p => { p.scenarios[0].sales_forecast.sales[9] = 'abc'; },
    p => { delete p.scenarios[0].sales_forecast; },
    p => { p.scenarios[0].extra = '123'; },
    p => { p.extra = '123'; }
  ];
  mutations.forEach(mutate => {
    const old = amountProject();
    mutate(old);
    assert.throws(() => E.parseProject(JSON.stringify(old)), /프로젝트 파일 오류/);
  });
});

test('archived amount SF is deeply copied by project construction and never affects profits', () => {
  const migrated = E.parseProject(JSON.stringify(amountProject()));
  const p = E.makeProject(migrated);
  migrated.profit_analysis.legacy_amount_forecast.common_sales[0] = '9999';
  migrated.profit_analysis.legacy_amount_forecast.scenarios[0].sales[0] = '9999';
  assert.equal(p.profit_analysis.legacy_amount_forecast.common_sales[0], '1,000.1234567890123456789');
  assert.equal(p.profit_analysis.legacy_amount_forecast.scenarios[0].sales[0], null);
  p.profit_analysis.years = 1;
  p.profit_analysis.common_quantities[0] = '1000';
  const result = F.calculate(p).scenarios[0];
  equal(result.rows[0].quantity, 1000);
  equal(result.rows[0].sales, 300000);
  equal(result.rows[0].profit, 220000);
});

test('strict archive validation rejects wrong units, malformed amounts and unsupported structures', () => {
  const mutations = [
    a => { a.unit = 'krw'; },
    a => { a.extra = true; },
    a => { a.common_sales = Array(9).fill(null); },
    a => { a.common_sales[0] = '-1'; },
    a => { a.scenarios = []; },
    a => { a.scenarios[0].extra = true; },
    a => { a.scenarios[0].use_custom = 1; },
    a => { a.scenarios[0].sales[0] = 'abc'; },
    a => { a.scenarios[1].scenario_id = a.scenarios[0].scenario_id; }
  ];
  mutations.forEach(mutate => {
    const p = E.parseProject(JSON.stringify(amountProject()));
    mutate(p.profit_analysis.legacy_amount_forecast);
    assert.throws(() => E.serializeProject(p), /프로젝트 파일 오류/);
  });
});

test('fractional SF quantities are rejected in common and hidden custom entries', () => {
  const p = E.makeProject();
  p.profit_analysis.common_quantities[9] = '1.5';
  assert.throws(() => E.serializeProject(p), /정수/);
  p.profit_analysis.common_quantities[9] = null;
  p.scenarios[0].sales_forecast.quantities[9] = '0.1';
  assert.throws(() => E.serializeProject(p), /정수/);
});

for (const version of [1, 2]) {
  test('schema ' + version + ' rejects unexpected SF fields rather than dropping them', () => {
    const old = legacy(version);
    old.profit_analysis = E.makeProfitAnalysis();
    assert.throws(() => E.parseProject(JSON.stringify(old)), /이전 버전.*이익 분석/);
    delete old.profit_analysis;
    old.scenarios[0].sales_forecast = E.makeSalesForecast();
    assert.throws(() => E.parseProject(JSON.stringify(old)), /이전 버전.*판매 예측/);
  });
}

for (const years of [0, 11, 1.5, '8', null]) {
  test('invalid analysis period ' + JSON.stringify(years) + ' is rejected and explained', () => {
    const p = project();
    p.profit_analysis.years = years;
    assert.throws(() => E.serializeProject(p), /분석 기간/);
    assert.deepEqual(F.calculate(p).scenarios, []);
    assert.ok(F.calculate(p).issues.some(issue => issue.path === 'profit_analysis.years'));
  });
}

test('strict v4 requires both SF objects and rejects unknown keys and malformed types', () => {
  const mutations = [
    p => { delete p.profit_analysis; },
    p => { delete p.scenarios[0].sales_forecast; },
    p => { p.profit_analysis.extra = 1; },
    p => { p.scenarios[0].sales_forecast.extra = 1; },
    p => { p.profit_analysis.enabled = 1; },
    p => { p.scenarios[0].sales_forecast.use_custom = 'false'; },
    p => { p.profit_analysis.common_quantities = Array(9).fill(null); },
    p => { p.scenarios[0].sales_forecast.quantities = Array(11).fill(null); },
    p => { p.profit_analysis.common_quantities = null; }
  ];
  mutations.forEach(mutate => {
    const p = project();
    mutate(p);
    assert.throws(() => E.parseProject(JSON.stringify(p)), /프로젝트 파일 오류/);
  });
});

test('negative and malformed hidden SF values are rejected even when analysis is disabled', () => {
  for (const invalid of ['-1', 'abc', '1,2', 'NaN', 100]) {
    const p = E.makeProject();
    p.profit_analysis.common_quantities[9] = invalid;
    assert.throws(() => E.serializeProject(p), /SF/);
    p.profit_analysis.common_quantities[9] = null;
    p.scenarios[0].sales_forecast.quantities[9] = invalid;
    assert.throws(() => E.serializeProject(p), /SF/);
  }
});

test('browser UMD forecast uses only the bundled modules and does not require a server', () => {
  const sandbox = { console, Date, Math };
  vm.createContext(sandbox);
  for (const file of ['vendor/decimal.js', 'pricing.js', 'engine.js', 'forecast.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), sandbox);
  assert.ok(sandbox.PharmaProfit);
  const p = JSON.parse(JSON.stringify(project()));
  const r = sandbox.PharmaProfit.calculate(p);
  assert.equal(r.scenarios[0].total_profit.toString(), '70000');
});
