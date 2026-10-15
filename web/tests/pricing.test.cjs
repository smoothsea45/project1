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
// 2027-09-01. The generic branch keeps its prior company/market rules; supply
// categories now deliberately use the separately labelled simplified model.
const examples = [
  ['two criteria, no addition, fewer than 14', {}, {}, repeated(450)],
  ['one criterion, no addition, fewer than 14', {}, { own_data: false }, repeated(360)],
  ['no criteria, no addition, fewer than 14', {}, { own_data: false, dmf: false }, repeated(290)],
  ['two criteria, 14 or more triggers reduction after year one', { identical_count_band: 'ge14' }, {}, ['450', ...repeated(383, 9)]],
  ['innovative addition without domestic extension lasts one year', { company_type: 'innovative' }, { company_eligible: true }, ['600', ...repeated(450, 9)]],
  ['innovative domestic extension lasts four years', { company_type: 'innovative' }, { company_eligible: true, domestic_extension: true }, [...repeated(600, 4), ...repeated(450, 6)]],
  ['innovative four-year extension defers 14-item reduction', { company_type: 'innovative', identical_count_band: 'ge14' }, { company_eligible: true, domestic_extension: true }, [...repeated(600, 4), ...repeated(383, 6)]],
  ['near innovative domestic extension lasts four years', { company_type: 'near' }, { company_eligible: true, domestic_extension: true }, [...repeated(500, 4), ...repeated(450, 6)]],
  ['simple supply assumes the initial five years and a further five-year extension', {}, { supply_category: 'api_self', supply_eligible: false }, repeated(680)],
  ['simple supply retains 68 percent irrespective of the generic 14-item band', { identical_count_band: 'ge14' }, { supply_category: 'api_self', supply_eligible: true }, repeated(680)],
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

test('simple supply has precedence without adding or concatenating company periods', () => {
  const data = scenario({ company_type: 'innovative', identical_count_band: 'ge14' }, {
    company_eligible: true, domestic_extension: true,
    supply_category: 'api_self', supply_eligible: true, supply_extension: false
  });
  assert.deepEqual(amounts(data), repeated(680));
});

test('inactive supply extension values do not extend a company addition', () => {
  const data = scenario({ company_type: 'innovative' }, {
    company_eligible: true, domestic_extension: false,
    supply_category: 'none', supply_eligible: true, supply_extension: true
  });
  assert.deepEqual(amounts(data), ['600', ...repeated(450, 9)]);
});

test('simple supply ignores preserved old eligibility and extension controls', () => {
  const data = scenario({ company_type: 'innovative' }, {
    company_eligible: true, supply_category: 'api_self', supply_eligible: false,
    supply_extension: false, own_data: false, dmf: false
  });
  assert.deepEqual(amounts(data), repeated(680));
  assert.equal(data.pricing_conditions.supply_eligible, false);
  assert.equal(data.pricing_conditions.supply_extension, false);
});

for (const category of ['api_self', 'domestic_essential', 'own_injectable_pediatric']) {
  test(`simple supply ${category} uses 68 percent even when legacy qualification fields are false`, () => {
    const data = scenario({}, {
      own_data: false, dmf: false, supply_category: category,
      supply_eligible: false, supply_detail_eligible: false, supply_extension: false
    });
    assert.deepEqual(amounts(data), repeated(680));
    const result = E.assessPricing(data);
    assert.equal(result.model, 'simplified-v1');
    assert.match(result.source, /간편.*가정/);
    assert.equal(result.regulation, null);
    assert.equal(data.pricing_conditions.own_data, false);
    assert.equal(data.pricing_conditions.dmf, false);
  });
}

test('supply extension years are explicitly distinguished as an assumption', () => {
  const pricing = E.assessPricing(scenario({}, { supply_category: 'api_self', supply_eligible: false, supply_extension: false }));
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

const simpleGeneralCases = [
  ['data_submission', ['700', ...repeated(600, 3), ...repeated(450, 6)]],
  ['improved', [...repeated(700, 4), ...repeated(450, 6)]],
  ['improved_combo', [...repeated(680, 4), ...repeated(450, 6)]],
  ['other', [...repeated(600, 4), ...repeated(450, 6)]],
  ['biologic', [...repeated(800, 5), ...repeated(700, 5)]]
];

for (const [category, expected] of simpleGeneralCases) {
  test(`simplified general ${category} uses its explicit ten-year schedule`, () => {
    assert.deepEqual(amounts(scenario({}, { general_category: category })), expected);
  });

  test(`simplified ${category} is labelled as an assumption rather than an official calculation`, () => {
    const result = E.assessPricing(scenario({}, { general_category: category }));
    assert.equal(result.model, 'simplified-v1');
    assert.match(result.source, /간편.*가정/);
    assert.equal(result.regulation, null);
    assert.equal(result.basis_date, null);
    assert.deepEqual(result.links, []);
  });

  test(`simplified ${category} ignores preserved hidden detailed conditions`, () => {
    const data = scenario({ company_type: '', identical_count_band: '' }, {
      general_category: category, general_subtype: '', general_base: 'not a number',
      general_cap: '-100', general_recognized: false, general_extension: false,
      general_same_reference: false, general_first_listed: false,
      general_dose_equivalent: false, general_trigger_date: 'invalid date',
      general_target_biologic: true, general_reference_own: true,
      general_long_extension: true, company_eligible: false
    });
    const before = JSON.stringify(data);
    assert.deepEqual(amounts(data), expected);
    assert.equal(JSON.stringify(data), before);
  });

  test(`simple supply takes precedence over ${category} without summing rates`, () => {
    const data = scenario({ company_type: 'innovative', identical_count_band: 'ge14' }, {
      general_category: category, supply_category: 'api_self',
      supply_eligible: false, supply_extension: false, company_eligible: true
    });
    assert.deepEqual(amounts(data), repeated(680));
  });
}

for (const category of ['data_submission', 'improved', 'improved_combo', 'other']) {
  test(`simplified ${category} recovers from the fifth year at the basic rate for one or zero criteria`, () => {
    const one = E.assessPricing(scenario({}, { general_category: category, own_data: false }));
    const none = E.assessPricing(scenario({}, { general_category: category, own_data: false, dmf: false }));
    equal(one.years[4].amount, 360);
    equal(none.years[4].amount, 290);
    equal(one.years[9].amount, 360);
    equal(none.years[9].amount, 290);
    if (category === 'improved' || category === 'improved_combo') {
      const fourthYearPrice = category === 'improved' ? 700 : 680;
      equal(one.years[3].amount, fourthYearPrice);
      equal(none.years[3].amount, fourthYearPrice);
    }
  });
}

test('biologic post-addition rate remains 70 percent irrespective of generic criteria', () => {
  assert.deepEqual(amounts(scenario({}, { general_category: 'biologic', own_data: false, dmf: false })), [...repeated(800, 5), ...repeated(700, 5)]);
});

for (const field of ['own_data', 'dmf']) {
  test(`a malformed active recovery criterion ${field} cannot silently change the post-addition price`, () => {
    const result = E.assessPricing(scenario({}, { general_category: 'data_submission', [field]: 'false' }));
    assert.equal(result.status, 'invalid');
    assert.equal(result.amount, null);
    assert.equal(result.years.length, 0);
  });
}

test('simplified percentages use the original price directly and round monetary results half up', () => {
  const data = scenario({ original_price: '1003' }, { general_category: 'data_submission' });
  assert.deepEqual(amounts(data), ['702', ...repeated(602, 3), ...repeated(451, 6)]);
  assert.deepEqual(amounts(scenario({ original_price: '1003' }, { supply_category: 'api_self' })), repeated(682));
});

test('generic 14-item reduction cannot leak into a simplified general schedule', () => {
  for (const [category] of simpleGeneralCases) {
    const below14 = scenario({ identical_count_band: 'lt14' }, { general_category: category });
    const atLeast14 = scenario({ identical_count_band: 'ge14' }, { general_category: category });
    assert.deepEqual(amounts(atLeast14), amounts(below14));
  }
});

test('company eligibility and old extension choices do not alter the simplified general schedule', () => {
  for (const [category, expected] of simpleGeneralCases) {
    const data = scenario({ company_type: 'innovative' }, {
      general_category: category, company_eligible: true, domestic_extension: true,
      general_extension: true, general_long_extension: true
    });
    assert.deepEqual(amounts(data), expected);
  }
});

test('malformed preserved detailed flags cannot block a simplified calculation', () => {
  const data = scenario({}, { general_category: 'improved' });
  Object.assign(data.pricing_conditions, {
    general_recognized: 'false', general_extension: null,
    general_same_reference: 'old value', general_dose_equivalent: 1,
    general_long_extension: [], company_eligible: 'false',
    supply_eligible: 'false', supply_detail_eligible: null, supply_extension: 'false'
  });
  assert.deepEqual(amounts(data), [...repeated(700, 4), ...repeated(450, 6)]);
  data.pricing_conditions.supply_category = 'own_injectable_pediatric';
  assert.deepEqual(amounts(data), repeated(680));
});

test('selecting a simplified general year updates the shared cost denominator', () => {
  const data = scenario({}, { general_category: 'data_submission' });
  equal(E.calculate(data).pricing.amount, 700);
  data.pricing_conditions.selected_year = 3;
  const result = E.calculate(data);
  equal(result.pricing.amount, 600);
  equal(result.cost_rate, new E.Decimal(20).div(600).times(100));
  equal(result.total_cost, 20);
  assert.equal(data.manual_price, '300');
});

test('simplified general and supply schedules cannot bypass missing or invalid original-price validation', () => {
  for (const condition of [{ general_category: 'other' }, { supply_category: 'api_self' }]) {
    for (const original of ['', '0', '-1', 'not a price']) {
      const result = E.calculate(scenario({ original_price: original }, condition));
      equal(result.total_cost, 20);
      assert.equal(result.pricing.amount, null);
      assert.equal(result.pricing.years.length, 0);
      assert.equal(result.cost_rate, null);
    }
  }
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

for (const category of ['improved_combo', 'other']) {
  test(`new simplified category ${category} survives saving and loading with the chosen year`, () => {
    const data = scenario({}, { general_category: category, selected_year: 8 });
    const project = E.makeProject({ scenarios: [data] });
    const loaded = E.parseProject(E.serializeProject(project));
    assert.deepEqual(loaded, project);
    assert.equal(loaded.scenarios[0].pricing_conditions.general_category, category);
    assert.equal(loaded.scenarios[0].pricing_conditions.selected_year, 8);
    equal(E.calculate(loaded.scenarios[0]).pricing.amount, 450);
    assert.equal(loaded.scenarios[0].manual_price, '300');
  });
}

test('a legacy improved combination selection migrates to the separate simplified combination category', () => {
  const project = E.makeProject({ scenarios: [scenario({}, {
    general_category: 'improved', general_subtype: 'combination', selected_year: 1
  })] });
  delete project.scenarios[0].pricing_conditions.model_id;
  const originalText = JSON.stringify(project);
  const loaded = E.parseProject(originalText);
  assert.equal(JSON.stringify(project), originalText);
  const conditions = loaded.scenarios[0].pricing_conditions;
  assert.equal(conditions.general_category, 'improved_combo');
  assert.equal(conditions.general_subtype, 'combination');
  assert.equal(conditions.model_id, 'simplified-v1');
  equal(E.calculate(loaded.scenarios[0]).pricing.amount, 680);
  assert.equal(loaded.scenarios[0].manual_price, '300');
  assert.deepEqual(E.parseProject(E.serializeProject(loaded)), loaded);
});

test('editing a migrated combination to improved medicine stays improved on subsequent load', () => {
  const data = scenario({}, { general_category: 'improved', general_subtype: 'combination', model_id: 'simplified-v1' });
  const project = E.makeProject({ scenarios: [data] });
  const loaded = E.parseProject(E.serializeProject(project));
  assert.equal(loaded.scenarios[0].pricing_conditions.general_category, 'improved');
  assert.equal(loaded.scenarios[0].pricing_conditions.general_subtype, 'combination');
  equal(E.calculate(loaded.scenarios[0]).pricing.amount, 700);
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
