'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../engine.js');

function scenario(overrides = {}, conditions = {}) {
  return E.makeScenario({
    batch_size: '100000', yield_percent: '100', manual_price: '300',
    original_price: '1000', pricing_mode: 'official', company_type: 'general',
    identical_count_band: 'lt14',
    materials: [E.makeMaterial({ amount: '20', price: '1000000', price_unit: 'krw_kg' })],
    ...overrides,
    pricing_conditions: E.makePricingConditions({
      own_data: true, dmf: true, listing_date: '2027-09-01',
      ...conditions, ...(overrides.pricing_conditions || {})
    })
  });
}

function equal(actual, expected) {
  assert.ok(actual !== null && actual !== undefined, 'Expected a calculated amount');
  assert.ok(actual.eq(expected), `${actual.toString()} differs from ${expected}`);
}

function amounts(data) {
  const pricing = E.assessPricing(data);
  assert.equal(pricing.status, 'ready');
  assert.equal(pricing.years.length, 10);
  return pricing.years.map(year => year.amount.toString());
}

function repeated(amount, length = 10) { return Array(length).fill(String(amount)); }

// The requested examples all use an original basis of 1,000 KRW and listing on
// 2027-09-01; eligibility is explicit rather than inferred from company labels.
const examples = [
  ['two criteria, no addition, fewer than 14', {}, {}, repeated(450)],
  ['one criterion, no addition, fewer than 14', {}, { own_data: false }, repeated(360)],
  ['no criteria, no addition, fewer than 14', {}, { own_data: false, dmf: false }, repeated(290)],
  ['two criteria, 14 or more triggers reduction after year one', { identical_count_band: 'ge14' }, {}, ['450', ...repeated(383, 9)]],
  ['innovative addition without domestic extension lasts one year', { company_type: 'innovative' }, { company_eligible: true }, ['600', ...repeated(450, 9)]],
  ['innovative domestic extension lasts four years', { company_type: 'innovative' }, { company_eligible: true, domestic_extension: true }, [...repeated(600, 4), ...repeated(450, 6)]],
  ['innovative four-year extension defers 14-item reduction', { company_type: 'innovative', identical_count_band: 'ge14' }, { company_eligible: true, domestic_extension: true }, [...repeated(600, 4), ...repeated(383, 6)]],
  ['near innovative domestic extension lasts four years', { company_type: 'near' }, { company_eligible: true, domestic_extension: true }, [...repeated(500, 4), ...repeated(450, 6)]],
  ['supply addition lasts five years without extension', {}, { supply_category: 'api_self', supply_eligible: true }, [...repeated(680, 5), ...repeated(450, 5)]],
  ['supply addition defers 14-item reduction until year six', { identical_count_band: 'ge14' }, { supply_category: 'api_self', supply_eligible: true }, [...repeated(680, 5), ...repeated(383, 5)]],
  ['supply extension retains addition throughout ten years', {}, { supply_category: 'api_self', supply_eligible: true, supply_extension: true }, repeated(680)]
];

for (const [label, fields, conditions, expected] of examples) {
  test(`official pricing: ${label}`, () => {
    assert.deepEqual(amounts(scenario(fields, conditions)), expected);
  });
}

test('manual 300 KRW is the sole cost denominator regardless of inactive conditions', () => {
  const data = scenario({ pricing_mode: 'manual', original_price: null, post_price: '-10', company_type: '' }, {
    own_data: false, dmf: false, listing_date: 'not-a-date', selected_year: 10,
    general_category: 'biologic', supply_category: 'api_self', supply_eligible: false
  });
  const result = E.calculate(data);
  equal(result.pricing.amount, 300);
  equal(result.cost_rate, new E.Decimal(20).div(300).times(100));
  equal(result.total_cost, 20);
  assert.equal(result.pricing.source, '사용자 입력값');
  assert.equal(result.post_rate, null);
  assert.ok(!result.issues.some(issue => issue.path === 'original_price' || issue.path === 'post_price' || issue.path.startsWith('pricing_conditions')));
});

test('manual pricing ignores malformed inactive numeric and conditional values', () => {
  const data = scenario({ pricing_mode: 'manual', original_price: 'not a price', post_price: 'Infinity' });
  data.pricing_conditions = { own_data: 'false', selected_year: -10, listing_date: 'bad' };
  const result = E.calculate(data);
  equal(result.pricing.amount, 300);
  equal(result.total_cost, 20);
  assert.ok(!result.issues.some(issue => issue.path === 'original_price' || issue.path === 'post_price' || issue.path.startsWith('pricing_conditions')));
});

test('mode switches preserve manual 300 independently from automatic 450', () => {
  const data = scenario({ pricing_mode: 'manual' });
  equal(E.calculate(data).pricing.amount, 300);
  data.pricing_mode = 'official';
  equal(E.calculate(data).pricing.amount, 450);
  assert.equal(data.manual_price, '300');
  data.pricing_conditions.selected_year = 8;
  data.pricing_mode = 'manual';
  equal(E.calculate(data).pricing.amount, 300);
  assert.equal(data.manual_price, '300');
  assert.equal(data.pricing_conditions.selected_year, 8);
});

test('rounding occurs separately at basic, addition and reduction stages', () => {
  const data = scenario({ original_price: '1003', company_type: 'innovative', identical_count_band: 'ge14' }, { company_eligible: true });
  // 1003 × .45 = 451.35 -> 451; 451 × 60/45 -> 601;
  // 451 × .85 = 383.35 -> 383, rather than a one-step result of 384.
  assert.deepEqual(amounts(data), ['601', ...repeated(383, 9)]);
});

test('half-won reductions round upward rather than using binary or banker rounding', () => {
  assert.deepEqual(amounts(scenario({ identical_count_band: 'ge14' })), ['450', ...repeated(383, 9)]);
});

test('company qualification alone does not imply eligibility or a four-year period', () => {
  assert.deepEqual(amounts(scenario({ company_type: 'innovative' }, { company_eligible: false, domestic_extension: true })), repeated(450));
  assert.deepEqual(amounts(scenario({ company_type: 'innovative' }, { company_eligible: true, domestic_extension: false })), ['600', ...repeated(450, 9)]);
});

test('company addition requires both effective basic criteria', () => {
  assert.deepEqual(amounts(scenario({ company_type: 'innovative' }, { company_eligible: true, own_data: false, domestic_extension: true })), repeated(360));
});

test('multiple API rows cannot silently receive the single-ingredient company addition', () => {
  const data = scenario({
    company_type: 'innovative', materials: [
      E.makeMaterial({ name: '성분 A', amount: '20', price: '1000000', price_unit: 'krw_kg' }),
      E.makeMaterial({ name: '성분 B', amount: '10', price: '1000000', price_unit: 'krw_kg' })
    ]
  }, { company_eligible: true, domestic_extension: true });
  const pricing = E.assessPricing(data);
  assert.deepEqual(amounts(data), repeated(450));
  assert.match(pricing.notes.join(' '), /기업가산 미적용.*복합제/);
});

test('near-innovative and supply-leading company identities remain distinct despite the same price', () => {
  const near = scenario({ company_type: 'near' }, { company_eligible: true, domestic_extension: true });
  const leader = scenario({ company_type: 'supply_leader' }, { company_eligible: true, domestic_extension: true });
  assert.deepEqual(amounts(near), [...repeated(500, 4), ...repeated(450, 6)]);
  assert.deepEqual(amounts(leader), amounts(near));
  const project = E.makeProject({ scenarios: [near, leader] });
  const loaded = E.parseProject(E.serializeProject(project));
  assert.equal(loaded.scenarios[0].company_type, 'near');
  assert.equal(loaded.scenarios[1].company_type, 'supply_leader');
});

test('string false is never treated as a qualifying boolean', () => {
  const data = scenario({ company_type: 'innovative' }, { company_eligible: 'false', domestic_extension: 'false' });
  const result = E.assessPricing(data);
  assert.notEqual(result.amount && result.amount.toString(), '600');
  assert.ok(result.issues.length > 0);
});

test('supply addition has precedence without adding or concatenating company periods', () => {
  const data = scenario({ company_type: 'innovative', identical_count_band: 'ge14' }, {
    company_eligible: true, domestic_extension: true,
    supply_category: 'api_self', supply_eligible: true, supply_extension: false
  });
  assert.deepEqual(amounts(data), [...repeated(680, 5), ...repeated(383, 5)]);
});

test('inactive supply extension values do not extend a company addition', () => {
  const data = scenario({ company_type: 'innovative' }, {
    company_eligible: true, domestic_extension: false,
    supply_category: 'none', supply_eligible: true, supply_extension: true
  });
  assert.deepEqual(amounts(data), ['600', ...repeated(450, 9)]);
});

test('supply addition requires its own eligibility rather than the 14-item selection', () => {
  const data = scenario({}, { supply_category: 'api_self', supply_eligible: false });
  assert.deepEqual(amounts(data), repeated(450));
});

test('ordinary supply selection cannot bypass an unfulfilled basic criterion', () => {
  const data = scenario({}, { own_data: false, supply_category: 'api_self', supply_eligible: true });
  assert.deepEqual(amounts(data), repeated(360));
});

test('ineligible supply selection leaves a separately eligible company addition available', () => {
  const data = scenario({ company_type: 'innovative' }, {
    company_eligible: true, supply_category: 'api_self', supply_eligible: false,
    supply_extension: true
  });
  assert.deepEqual(amounts(data), ['600', ...repeated(450, 9)]);
});

test('directly produced injection and pediatric supply requires separate detail eligibility', () => {
  const data = scenario({}, { supply_category: 'own_injectable_pediatric', supply_eligible: true, supply_detail_eligible: false });
  assert.deepEqual(amounts(data), repeated(450));
  data.pricing_conditions.supply_detail_eligible = true;
  assert.deepEqual(amounts(data), [...repeated(680, 5), ...repeated(450, 5)]);
});

test('eligible domestic essential medicines deem basic criteria satisfied with an explanation', () => {
  const data = scenario({}, { own_data: false, dmf: false, supply_category: 'domestic_essential', supply_eligible: true });
  const pricing = E.assessPricing(data);
  assert.deepEqual(amounts(data), [...repeated(680, 5), ...repeated(450, 5)]);
  assert.equal(pricing.effective_requirements.count, 2);
  assert.equal(pricing.effective_requirements.own_data, true);
  assert.equal(pricing.effective_requirements.dmf, true);
  assert.ok(pricing.effective_requirements.deemed_reasons.length > 0);
  assert.equal(data.pricing_conditions.own_data, false);
  assert.equal(data.pricing_conditions.dmf, false);
});

test('domestic essential selection without eligibility does not deem basic criteria', () => {
  const data = scenario({}, { own_data: false, dmf: false, supply_category: 'domestic_essential', supply_eligible: false });
  const pricing = E.assessPricing(data);
  assert.deepEqual(amounts(data), repeated(290));
  assert.equal(pricing.effective_requirements.count, 0);
});

test('supply extension years are explicitly distinguished as an assumption', () => {
  const pricing = E.assessPricing(scenario({}, { supply_category: 'api_self', supply_eligible: true, supply_extension: true }));
  assert.ok(pricing.years.slice(0, 5).every(year => !year.assumption));
  assert.ok(pricing.years.slice(5).every(year => year.assumption));
});

test('year periods run between calendar anniversaries rather than calendar year ends', () => {
  const pricing = E.assessPricing(scenario());
  for (let index = 0; index < 10; index += 1) {
    const year = pricing.years[index];
    assert.equal(year.year, index + 1);
    assert.equal(year.start_date, `${2027 + index}-09-01`);
    assert.equal(year.end_date, `${2028 + index}-08-31`);
    assert.equal(year.calendar_year, 2027 + index);
  }
});

test('leap-day anniversaries clamp to February and recover the anchor day in leap years', () => {
  const pricing = E.assessPricing(scenario({}, { listing_date: '2028-02-29' }));
  assert.equal(pricing.years[0].start_date, '2028-02-29');
  assert.equal(pricing.years[0].end_date, '2029-02-27');
  assert.equal(pricing.years[1].start_date, '2029-02-28');
  assert.equal(pricing.years[3].end_date, '2032-02-28');
  assert.equal(pricing.years[4].start_date, '2032-02-29');
});

test('selecting a pricing year changes the shared cost denominator but not cost calculations', () => {
  const data = scenario({ identical_count_band: 'ge14' });
  const first = E.calculate(data);
  equal(first.pricing.amount, 450);
  equal(first.cost_rate, new E.Decimal(20).div(450).times(100));
  data.pricing_conditions.selected_year = 2;
  const second = E.calculate(data);
  equal(second.pricing.amount, 383);
  equal(second.cost_rate, new E.Decimal(20).div(383).times(100));
  equal(second.total_cost, first.total_cost);
  equal(second.api_batch, first.api_batch);
  equal(second.api_unit, first.api_unit);
  assert.equal(data.manual_price, '300');
});

for (const selectedYear of [0, -1, 11, 1.5, null, '2', 'bad']) {
  test(`invalid selected year ${JSON.stringify(selectedYear)} cannot silently select another denominator`, () => {
    const data = scenario({}, { selected_year: selectedYear });
    const result = E.calculate(data);
    equal(result.total_cost, 20);
    assert.equal(result.pricing.amount, null);
    assert.equal(result.cost_rate, null);
  });
}

for (const originalPrice of [null, '', '0', '-1', 'NaN', 'Infinity', '1,2']) {
  test(`invalid original basis ${JSON.stringify(originalPrice)} cannot leave a stale or fallback automatic price`, () => {
    const result = E.calculate(scenario({ original_price: originalPrice }));
    equal(result.total_cost, 20);
    assert.equal(result.pricing.amount, null);
    assert.equal(result.cost_rate, null);
    assert.equal(result.pricing.years.length, 0);
    assert.ok(result.issues.length > 0);
  });
}

for (const listingDate of ['', '2027-02-29', '2027-13-01', '2027-00-01', '2027-09-31', '2027-9-1', 'not-a-date']) {
  test(`invalid listing date ${JSON.stringify(listingDate)} does not produce a timeline or zero price`, () => {
    const result = E.calculate(scenario({}, { listing_date: listingDate }));
    equal(result.total_cost, 20);
    assert.equal(result.pricing.amount, null);
    assert.equal(result.cost_rate, null);
    assert.equal(result.pricing.years.length, 0);
    assert.ok(result.issues.length > 0);
  });
}

for (const category of ['data_submission', 'improved', 'biologic']) {
  test(`general ${category} without its separate basis cannot fall back to generic 45 percent`, () => {
    const data = scenario({}, { general_category: category });
    const result = E.calculate(data);
    equal(result.total_cost, 20);
    assert.equal(result.pricing.status, 'needs_conditions');
    assert.equal(result.pricing.amount, null);
    assert.equal(result.cost_rate, null);
    assert.equal(result.pricing.years.length, 0);
    assert.match(result.issues.map(issue => issue.message).join(' '), /추가 산정조건 필요/);
  });
}

function generalScenario(fields = {}, conditions = {}) {
  return scenario(fields, {
    general_category: 'data_submission', general_subtype: 'new_form',
    general_base: '1000', general_same_reference: true,
    general_first_listed: true, general_dose_equivalent: true,
    general_trigger_date: '2027-09-01', ...conditions
  });
}

test('verified first-listed data-submission route applies 70/45 to its own 1000 basis', () => {
  const data = generalScenario({ original_price: '2000', identical_count_band: 'ge14' });
  const result = E.assessPricing(data);
  equal(result.base_amount, 1000);
  equal(result.bonus_amount, 1556);
  assert.deepEqual(amounts(data), ['1556', ...repeated(1000, 9)]);
});

test('non-improved data-submission extension recalculates 60/45 and honors the prior ceiling', () => {
  const data = generalScenario({}, { general_extension: true, general_cap: '1300' });
  // Year one: round(1000 × 70/45) = 1556.
  // Years two through four: min(round(1000 × 60/45), 1300) = 1300.
  assert.deepEqual(amounts(data), ['1556', ...repeated(1300, 3), ...repeated(1000, 6)]);
});

test('non-improved extension without the required prior ceiling asks for conditions', () => {
  const result = E.assessPricing(generalScenario({}, { general_extension: true, general_cap: null }));
  assert.equal(result.status, 'needs_conditions');
  assert.equal(result.amount, null);
  assert.equal(result.years.length, 0);
});

test('recognized improved medicine retains the 70/45 amount during its initial extension', () => {
  const data = generalScenario({}, { general_category: 'improved', general_recognized: true, general_extension: true });
  assert.deepEqual(amounts(data), [...repeated(1556, 4), ...repeated(1000, 6)]);
});

test('turning off general extension ignores the preserved hidden long-extension selection', () => {
  const data = generalScenario({}, { general_category: 'improved', general_recognized: true, general_extension: true, general_long_extension: true });
  assert.deepEqual(amounts(data), repeated(1556, 10));
  data.pricing_conditions.general_extension = false;
  assert.deepEqual(amounts(data), ['1556', ...repeated(1000, 9)]);
  assert.equal(data.pricing_conditions.general_long_extension, true);
});

test('generic 14-item reduction cannot leak into the separate general-addition route', () => {
  const below14 = generalScenario({ identical_count_band: 'lt14' });
  const atLeast14 = generalScenario({ identical_count_band: 'ge14' });
  assert.deepEqual(amounts(atLeast14), amounts(below14));
  assert.equal(E.assessPricing(atLeast14).reduced_amount.toString(), '1000');
});

test('company identity cannot replace or sum with the general route amount', () => {
  const data = generalScenario({ company_type: 'innovative' }, { company_eligible: true, domestic_extension: true });
  assert.deepEqual(amounts(data), ['1556', ...repeated(1000, 9)]);
});

test('unverified combined general and supply additions require conditions rather than choosing the largest rate', () => {
  const data = generalScenario({}, { supply_category: 'api_self', supply_eligible: true });
  const result = E.calculate(data);
  assert.equal(result.pricing.status, 'needs_conditions');
  assert.equal(result.pricing.amount, null);
  assert.equal(result.pricing.years.length, 0);
  assert.equal(result.cost_rate, null);
});

test('a distinct general-addition start date cannot silently be shifted to listing day', () => {
  const data = generalScenario({}, { general_trigger_date: '2026-09-01' });
  const result = E.assessPricing(data);
  assert.equal(result.status, 'needs_conditions');
  assert.equal(result.amount, null);
  assert.equal(result.years.length, 0);
});

test('automatic calculation is pure and retains official regulation provenance', () => {
  const data = scenario({ company_type: 'innovative', identical_count_band: 'ge14' }, { company_eligible: true, domestic_extension: true, selected_year: 8 });
  const before = JSON.stringify(data);
  const pricing = E.assessPricing(data);
  assert.equal(JSON.stringify(data), before);
  assert.ok(pricing.regulation);
  assert.equal(pricing.basis_date, '2026-08-01');
  assert.ok(pricing.links.some(link => link.includes('law.go.kr')));
  assert.ok(pricing.steps.length > 0);
});

test('JSON version 2 roundtrip retains mode, separate manual price, conditions and selected year', () => {
  const data = scenario({ company_type: 'innovative' }, {
    company_eligible: true, domestic_extension: true,
    supply_category: 'api_self', supply_eligible: true,
    supply_extension: true, selected_year: 7
  });
  const project = E.makeProject({ scenarios: [data] });
  const loaded = E.parseProject(E.serializeProject(project));
  assert.equal(loaded.schema_version, 2);
  assert.deepEqual(loaded, project);
  assert.equal(loaded.scenarios[0].manual_price, '300');
  assert.equal(loaded.scenarios[0].pricing_conditions.selected_year, 7);
  equal(E.calculate(loaded.scenarios[0]).pricing.amount, 680);
});

test('scenario clone deeply separates pricing conditions and selected year from its original', () => {
  const project = E.makeProject({ scenarios: [scenario({}, { supply_category: 'api_self', supply_eligible: true, selected_year: 2 })] });
  const before = JSON.stringify(project.scenarios[0]);
  const cloned = E.cloneScenario(project, project.active_scenario_id, '조건 변경');
  cloned.pricing_conditions.selected_year = 9;
  cloned.pricing_conditions.supply_extension = true;
  cloned.pricing_conditions.own_data = false;
  cloned.manual_price = '999';
  assert.equal(JSON.stringify(project.scenarios[0]), before);
  assert.notEqual(cloned.pricing_conditions, project.scenarios[0].pricing_conditions);
});

test('version 1 migration preserves manual pricing and ambiguous choices without guessing eligibility', () => {
  const project = E.makeProject({ scenarios: [scenario({
    pricing_mode: 'manual', company_type: 'near',
    pricing_flags: ['originator_data', 'improved', 'api_self', 'domestic_essential']
  })] });
  project.schema_version = 1;
  delete project.scenarios[0].pricing_conditions;
  const originalText = JSON.stringify(project);
  const loaded = E.parseProject(originalText);
  assert.equal(JSON.stringify(project), originalText);
  assert.equal(loaded.schema_version, 2);
  const migrated = loaded.scenarios[0];
  equal(E.calculate(migrated).pricing.amount, 300);
  assert.equal(migrated.manual_price, '300');
  assert.deepEqual(migrated.pricing_flags, project.scenarios[0].pricing_flags);
  assert.equal(migrated.company_type, '');
  assert.ok(migrated.pricing_conditions.migration_review);
  assert.equal(migrated.pricing_conditions.general_category, 'none');
  assert.equal(migrated.pricing_conditions.supply_category, 'none');
  assert.equal(migrated.pricing_conditions.company_eligible, false);
  assert.equal(migrated.pricing_conditions.supply_eligible, false);
  assert.deepEqual(E.parseProject(E.serializeProject(loaded)), loaded);
});
