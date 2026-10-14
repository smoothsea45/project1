/* Offline domain model. No network, browser storage, or screen code belongs here. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./vendor/decimal.js'));
  } else {
    root.PharmaCost = factory(root.Decimal);
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, function (DecimalLibrary) {
  'use strict';

  if (!DecimalLibrary) throw new Error('오프라인 계산 라이브러리를 불러오지 못했습니다.');
  // A separate context keeps the UI's display preferences out of calculations.
  const Decimal = DecimalLibrary.clone({ precision: 256, rounding: DecimalLibrary.ROUND_HALF_UP });
  const FORMAT = 'pharma-cost-web-project';
  const VERSION = 1;
  const MAX_SCENARIOS = 4;
  const SCENARIO_LIMIT_MESSAGE = '한 프로젝트의 시나리오는 최대 ' + MAX_SCENARIOS + '개까지 사용할 수 있습니다. 원본 데이터는 변경하지 않았습니다.';
  const UNITS = Object.freeze({
    krw_g: { divisor: '1000', foreign: false },
    krw_kg: { divisor: '1000000', foreign: false },
    usd_g: { divisor: '1000', foreign: true },
    usd_kg: { divisor: '1000000', foreign: true }
  });
  const FLAGS = Object.freeze(['originator_data', 'improved', 'biologic', 'api_self', 'domestic_essential', 'own_injectable_pediatric']);
  const SCENARIO_KEYS = ['id', 'name', 'batch_size', 'yield_percent', 'packaging_form', 'exchange_rate', 'original_price', 'manual_price', 'post_price', 'target_rate', 'batch_packaging', 'batch_labor', 'pricing_mode', 'company_type', 'identical_count_band', 'pricing_flags', 'materials'];
  const MATERIAL_KEYS = ['id', 'kind', 'name', 'supplier', 'amount', 'price', 'price_unit'];
  const NUMBER_FIELDS = ['batch_size', 'yield_percent', 'exchange_rate', 'original_price', 'manual_price', 'post_price', 'target_rate', 'batch_packaging', 'batch_labor'];
  const blank = value => value === null || value === undefined || (typeof value === 'string' && value.trim() === '');
  const copy = value => JSON.parse(JSON.stringify(value));
  const zero = () => new Decimal(0);

  function newId() {
    if (typeof globalThis !== 'undefined' && globalThis.crypto && globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID();
    return 'id-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2) + '-' + Math.random().toString(36).slice(2);
  }

  function makeMaterial(options) {
    const supplied = typeof options === 'string' ? { kind: options } : (options || {});
    return Object.assign({ id: newId(), kind: 'api', name: '', supplier: '', amount: null, price: null, price_unit: 'krw_kg' }, supplied);
  }

  function makeScenario(options) {
    const supplied = typeof options === 'string' ? { name: options } : (options || {});
    const result = Object.assign({
      id: newId(), name: '기본안', batch_size: null, yield_percent: '100', packaging_form: '', exchange_rate: null,
      original_price: null, manual_price: null, post_price: null, target_rate: '20',
      batch_packaging: '0', batch_labor: '0', pricing_mode: 'manual', company_type: '',
      identical_count_band: '', pricing_flags: [], materials: []
    }, supplied);
    result.pricing_flags = [...result.pricing_flags];
    result.materials = result.materials.map(material => copy(material));
    return result;
  }

  function normalizeScenario(scenario) {
    // Version 1 projects and browser drafts created before this field remain usable.
    if (scenario !== null && typeof scenario === 'object' && !Array.isArray(scenario) && !Object.prototype.hasOwnProperty.call(scenario, 'packaging_form')) scenario.packaging_form = '';
    return scenario;
  }

  function makeProject(options) {
    const supplied = options || {};
    if (Array.isArray(supplied.scenarios) && supplied.scenarios.length > MAX_SCENARIOS) throw new Error(SCENARIO_LIMIT_MESSAGE);
    const scenarios = supplied.scenarios ? supplied.scenarios.map(scenario => normalizeScenario(copy(scenario))) : [makeScenario()];
    return Object.assign({
      format: FORMAT, schema_version: VERSION,
      product: { product_name: '', notes: '' }, scenarios,
      active_scenario_id: scenarios.length ? scenarios[0].id : '', is_example: false
    }, supplied, { product: Object.assign({ product_name: '', notes: '' }, supplied.product || {}), scenarios });
  }

  function createExampleProject() {
    const scenario = makeScenario({
      name: '가상 예제 · 기본안', batch_size: '100000', yield_percent: '100', packaging_form: 'PTP 10T × 3', exchange_rate: '1350',
      original_price: '600', manual_price: '300', post_price: '250', target_rate: '20',
      batch_packaging: '1000000', batch_labor: '2000000', company_type: 'general', identical_count_band: 'lt14',
      materials: [
        makeMaterial({ kind: 'api', name: '가상 API A', supplier: '가상 제조원 A', amount: '20', price: '1000000', price_unit: 'krw_kg' }),
        makeMaterial({ kind: 'api', name: '가상 API B', supplier: '가상 제조원 B', amount: '10', price: '2000000', price_unit: 'krw_kg' }),
        makeMaterial({ kind: 'excipient', name: '가상 부형제', supplier: '가상 공급처', amount: '100', price: '100000', price_unit: 'krw_kg' })
      ]
    });
    const project = makeProject({ product: { product_name: '가상 복합정', notes: '학습용 가상 예제입니다. 실제 처방·견적·보험약가가 아닙니다.' }, scenarios: [scenario], is_example: true });
    const savings = cloneScenario(project, scenario.id, '가상 예제 · API 단가 절감안');
    savings.materials.filter(material => material.kind === 'api').forEach(material => {
      material.price = new Decimal(material.price).div(2).toString();
    });
    project.active_scenario_id = scenario.id;
    return project;
  }

  function cloneScenario(project, id, name) {
    if (project.scenarios.length >= MAX_SCENARIOS) throw new Error(SCENARIO_LIMIT_MESSAGE);
    const original = project.scenarios.find(scenario => scenario.id === id);
    if (!original) throw new Error('복제할 시나리오를 찾지 못했습니다.');
    const duplicate = normalizeScenario(copy(original));
    duplicate.id = newId();
    duplicate.name = name === undefined ? original.name + ' · 복제' : name;
    duplicate.materials.forEach(material => { material.id = newId(); });
    project.scenarios.push(duplicate);
    project.active_scenario_id = duplicate.id;
    return duplicate;
  }

  function issue(issues, path, message, severity) {
    if (!issues.some(item => item.path === path && item.message === message)) issues.push({ path, message, severity: severity || 'error' });
  }

  function readNumber(value, path, label, issues, options) {
    const opts = options || {};
    if (blank(value)) {
      if (opts.required) issue(issues, path, label + '을(를) 입력해 주세요.');
      return null;
    }
    if (typeof value !== 'string') {
      issue(issues, path, label + '은(는) 숫자 문자열로 입력해 주세요.');
      return null;
    }
    let text = value.trim();
    if (text.includes(',')) {
      if (!/^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?$/.test(text)) {
        issue(issues, path, label + '의 천 단위 구분을 확인해 주세요. 예: 1,000,000');
        return null;
      }
      text = text.replace(/,/g, '');
    }
    const match = /^([+-]?)(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?$/.exec(text);
    if (!match) {
      issue(issues, path, label + '에 올바른 숫자를 입력해 주세요.');
      return null;
    }
    const digits = match[2].replace('.', '').length;
    const exponent = match[3] === undefined ? 0 : Number(match[3]);
    if (digits > 128 || !Number.isFinite(exponent) || Math.abs(exponent) > 1000) {
      issue(issues, path, label + '의 숫자가 너무 큽니다. 유효 숫자는 128자리, 지수는 ±1000 이내로 입력해 주세요.');
      return null;
    }
    const result = new Decimal(text);
    if (!result.isFinite() || Math.abs(result.e) > 1000) {
      issue(issues, path, label + '의 숫자 범위를 확인해 주세요.');
      return null;
    }
    if (result.isNegative() && !result.isZero()) {
      issue(issues, path, label + '에는 음수를 입력할 수 없습니다.');
      return null;
    }
    if (opts.positive && !result.gt(0)) {
      issue(issues, path, label + '은(는) 0보다 커야 합니다.');
      return null;
    }
    if (opts.integer && !result.isInteger()) {
      issue(issues, path, label + '은(는) 정수로 입력해 주세요.');
      return null;
    }
    if (opts.maximum !== undefined && result.gt(opts.maximum)) {
      issue(issues, path, label + '은(는) ' + opts.maximum + ' 이하여야 합니다.');
      return null;
    }
    return result;
  }

  /**
   * Future official rules must be separately verified and injected by a trusted
   * caller. They need {verified:true, regulation, basis_date, links, calculate}.
   * calculate(scenario) returns {amount, steps}. No rate is assumed here.
   */
  function assessPricing(scenario, ruleSet) {
    const issues = [];
    if (scenario.pricing_mode === 'manual') {
      const amount = readNumber(scenario.manual_price, 'manual_price', '우리 제품 예상 약가', issues);
      if (blank(scenario.manual_price)) issue(issues, 'manual_price', '약가를 입력하면 제조원가율을 계산할 수 있습니다.', 'warning');
      else if (amount && amount.isZero()) issue(issues, 'manual_price', '약가가 0이어서 제조원가율을 계산할 수 없습니다.', 'warning');
      return {
        amount, source: '사용자 입력값', status: amount === null ? (blank(scenario.manual_price) ? 'missing' : 'invalid') : (amount.isZero() ? 'zero' : 'ready'),
        regulation: null, basis_date: null,
        steps: amount === null ? [] : ['우리 제품 예상 약가 직접 입력: ' + amount.toString() + ' 원/T'], links: [], issues
      };
    }
    if (scenario.pricing_mode !== 'official') {
      issue(issues, 'pricing_mode', '약가 입력 방식을 확인해 주세요.');
      return { amount: null, source: '약가 입력 방식 오류', status: 'invalid', regulation: null, basis_date: null, steps: [], links: [], issues };
    }
    if (!ruleSet || ruleSet.verified !== true || typeof ruleSet.calculate !== 'function' || !ruleSet.regulation || !ruleSet.basis_date) {
      issue(issues, 'pricing_mode', '자동 약가 산정 규칙이 아직 검증되지 않았습니다. 직접 입력 방식을 사용해 주세요.', 'warning');
      return { amount: null, source: '자동 산정 미확인', status: 'unverified', regulation: null, basis_date: null, steps: [], links: [], issues };
    }
    try {
      const computed = ruleSet.calculate(copy(scenario));
      if (!computed || computed.amount === null || computed.amount === undefined) throw new Error('적용 조건이 충족되지 않았습니다.');
      const amount = new Decimal(computed.amount);
      if (!amount.isFinite() || amount.lt(0)) throw new Error('산정 결과가 올바르지 않습니다.');
      return {
        amount, source: '검증된 규정에 따른 자동 산정', status: amount.isZero() ? 'zero' : 'ready',
        regulation: ruleSet.regulation, basis_date: ruleSet.basis_date,
        steps: Array.isArray(computed.steps) ? [...computed.steps] : [], links: Array.isArray(ruleSet.links) ? [...ruleSet.links] : [], issues
      };
    } catch (error) {
      issue(issues, 'pricing_mode', '약가 자동 산정을 완료할 수 없습니다: ' + error.message);
      return { amount: null, source: '자동 산정 불가', status: 'invalid', regulation: ruleSet.regulation, basis_date: ruleSet.basis_date, steps: [], links: ruleSet.links || [], issues };
    }
  }

  function calculate(scenario, ruleSet) {
    const issues = [];
    const batch = readNumber(scenario.batch_size, 'batch_size', '배치사이즈', issues, { required: true, positive: true, integer: true });
    const yieldPercent = readNumber(scenario.yield_percent, 'yield_percent', '수율', issues, { required: true, positive: true, maximum: '100' });
    const materials = Array.isArray(scenario.materials) ? scenario.materials : [];
    if (!Array.isArray(scenario.materials)) issue(issues, 'materials', '원료표 형식이 올바르지 않습니다.');
    const needsExchange = materials.some(material => UNITS[material.price_unit] && UNITS[material.price_unit].foreign);
    const exchange = readNumber(scenario.exchange_rate, 'exchange_rate', '환율', issues, { required: needsExchange, positive: true });
    const packaging = readNumber(scenario.batch_packaging, 'batch_packaging', '배치 전체 포자재비', issues, { required: true });
    const labor = readNumber(scenario.batch_labor, 'batch_labor', '배치 전체 공수비', issues, { required: true });
    const target = readNumber(scenario.target_rate, 'target_rate', '목표 제조원가율', issues);
    const postPrice = readNumber(scenario.post_price, 'post_price', '가산 종료 후 예상 약가', issues);
    readNumber(scenario.original_price, 'original_price', '오리지널 약가', issues);
    if (postPrice && postPrice.isZero()) issue(issues, 'post_price', '가산 종료 후 약가가 0이어서 해당 원가율을 계산할 수 없습니다.', 'warning');
    const denominator = batch && yieldPercent ? batch.times(yieldPercent).div(100) : null;
    const rows = [];
    let apiBatch = batch ? zero() : null;
    let excipientBatch = batch ? zero() : null;
    let kindsValid = true;
    for (const material of materials) {
      const prefix = 'materials.' + material.id + '.';
      const amount = readNumber(material.amount, prefix + 'amount', '실제 투입량', issues, { required: true });
      const purchase = readNumber(material.price, prefix + 'price', '구매단가', issues, { required: true });
      const unit = UNITS[material.price_unit];
      if (!unit) issue(issues, prefix + 'price_unit', '구매단가 단위를 선택해 주세요.');
      const validKind = material.kind === 'api' || material.kind === 'excipient';
      if (!validKind) {
        kindsValid = false;
        issue(issues, prefix + 'kind', 'API 또는 부형제 구분을 선택해 주세요.');
      }
      let batchCost = null;
      if (batch && amount && purchase && unit && validKind && (!unit.foreign || exchange)) {
        const price = unit.foreign ? purchase.times(exchange) : purchase;
        batchCost = amount.times(batch).times(price).div(unit.divisor);
      }
      const unitCost = batchCost !== null && denominator ? batchCost.div(denominator) : null;
      rows.push({ id: material.id, batch_cost: batchCost, unit_cost: unitCost });
      if (material.kind === 'api') apiBatch = apiBatch === null || batchCost === null ? null : apiBatch.plus(batchCost);
      if (material.kind === 'excipient') excipientBatch = excipientBatch === null || batchCost === null ? null : excipientBatch.plus(batchCost);
    }
    if (!kindsValid || !Array.isArray(scenario.materials)) { apiBatch = null; excipientBatch = null; }
    const rawBatch = apiBatch !== null && excipientBatch !== null ? apiBatch.plus(excipientBatch) : null;
    const apiUnit = apiBatch !== null && denominator ? apiBatch.div(denominator) : null;
    const excipientUnit = excipientBatch !== null && denominator ? excipientBatch.div(denominator) : null;
    const rawUnit = rawBatch !== null && denominator ? rawBatch.div(denominator) : null;
    const packagingUnit = packaging !== null && denominator ? packaging.div(denominator) : null;
    const laborUnit = labor !== null && denominator ? labor.div(denominator) : null;
    const total = rawUnit !== null && packagingUnit !== null && laborUnit !== null ? rawUnit.plus(packagingUnit).plus(laborUnit) : null;
    const batchTotal = rawBatch !== null && packaging !== null && labor !== null ? rawBatch.plus(packaging).plus(labor) : null;
    const pricing = assessPricing(scenario, ruleSet);
    issues.push(...pricing.issues);
    delete pricing.issues;
    const price = pricing.amount;
    const rate = total !== null && price !== null && price.gt(0) ? total.div(price).times(100) : null;
    const postRate = total !== null && postPrice !== null && postPrice.gt(0) ? total.div(postPrice).times(100) : null;
    const allowed = price !== null && price.gt(0) && target !== null ? price.times(target).div(100) : null;
    const saving = total !== null && allowed !== null ? Decimal.max(0, total.minus(allowed)) : null;
    return {
      api_batch: apiBatch, excipient_batch: excipientBatch, api_unit: apiUnit, excipient_unit: excipientUnit,
      raw_batch: rawBatch, raw_unit: rawUnit, packaging_unit: packagingUnit, labor_unit: laborUnit,
      batch_total: batchTotal, total_cost: total, cost_rate: rate, post_rate: postRate,
      allowed_cost: allowed, required_saving: saving, target_gap: rate !== null && target !== null ? rate.minus(target) : null,
      rows, issues, pricing
    };
  }

  function fileError(message) { throw new Error('프로젝트 파일 오류: ' + message); }
  function object(value, path, keys) {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) fileError(path + '의 형식이 올바르지 않습니다.');
    const extra = Object.keys(value).filter(key => !keys.includes(key));
    if (extra.length) fileError(path + '에 지원하지 않는 항목이 있습니다: ' + extra.join(', ') + '. 다른 버전의 파일인지 확인해 주세요.');
    const missing = keys.filter(key => !Object.prototype.hasOwnProperty.call(value, key));
    if (missing.length) fileError(path + '에 필요한 항목이 없습니다: ' + missing.join(', '));
  }
  function string(value, path, nonempty) {
    if (typeof value !== 'string' || (nonempty && !value.trim())) fileError(path + '은(는) ' + (nonempty ? '비어 있지 않은 ' : '') + '문자열이어야 합니다.');
  }
  function choice(value, path, choices) {
    if (!choices.includes(value)) fileError(path + '의 선택값을 지원하지 않습니다.');
  }
  function fileNumber(value, path, options) {
    if (value !== null && typeof value !== 'string') fileError(path + '은(는) 숫자 문자열 또는 미입력(null)이어야 합니다.');
    const issues = [];
    readNumber(value, path, path, issues, options);
    if (issues.length) fileError(issues[0].message);
  }
  function validateProject(project) {
    if (project === null || typeof project !== 'object' || Array.isArray(project)) fileError('JSON 프로젝트 객체가 필요합니다.');
    if (project.format !== FORMAT) fileError('지원하지 않는 파일 형식입니다. 기존 데스크톱 JSON은 자동 변환하지 않습니다.');
    if (project.schema_version !== VERSION) fileError('지원하지 않는 파일 버전입니다. 지원 버전: ' + VERSION);
    object(project, '프로젝트', ['format', 'schema_version', 'product', 'scenarios', 'active_scenario_id', 'is_example']);
    object(project.product, '제품정보', ['product_name', 'notes']);
    string(project.product.product_name, '제품명');
    string(project.product.notes, '비고');
    if (typeof project.is_example !== 'boolean') fileError('예제 표시값이 올바르지 않습니다.');
    if (!Array.isArray(project.scenarios) || !project.scenarios.length) fileError('시나리오가 하나 이상 필요합니다.');
    if (project.scenarios.length > MAX_SCENARIOS) fileError(SCENARIO_LIMIT_MESSAGE);
    const ids = new Set();
    project.scenarios.forEach((scenario, index) => {
      const path = '시나리오 ' + (index + 1);
      normalizeScenario(scenario);
      object(scenario, path, SCENARIO_KEYS);
      string(scenario.id, path + ' ID', true);
      if (ids.has(scenario.id)) fileError('시나리오 ID가 중복되어 있습니다.');
      ids.add(scenario.id);
      string(scenario.name, path + ' 이름', true);
      string(scenario.packaging_form, path + ' 포장형태');
      choice(scenario.pricing_mode, path + ' 약가 방식', ['manual', 'official']);
      choice(scenario.company_type, path + ' 기업 구분', ['', 'innovative', 'near', 'general']);
      choice(scenario.identical_count_band, path + ' 동일제제 품목 수', ['', 'lt14', 'ge14']);
      if (!Array.isArray(scenario.pricing_flags)) fileError(path + ' 가산 조건의 형식이 올바르지 않습니다.');
      scenario.pricing_flags.forEach(flag => choice(flag, path + ' 가산 조건', FLAGS));
      if (new Set(scenario.pricing_flags).size !== scenario.pricing_flags.length) fileError(path + ' 가산 조건이 중복되어 있습니다.');
      NUMBER_FIELDS.forEach(field => {
        const opts = field === 'batch_size' ? { positive: true, integer: true } : field === 'yield_percent' ? { positive: true, maximum: '100' } : field === 'exchange_rate' ? { positive: true } : {};
        fileNumber(scenario[field], path + ' ' + field, opts);
      });
      if (!Array.isArray(scenario.materials)) fileError(path + ' 원료표 형식이 올바르지 않습니다.');
      const materialIds = new Set();
      scenario.materials.forEach((material, materialIndex) => {
        const materialPath = path + ' 원료 ' + (materialIndex + 1);
        object(material, materialPath, MATERIAL_KEYS);
        string(material.id, materialPath + ' ID', true);
        if (materialIds.has(material.id)) fileError(materialPath + ' ID가 중복되어 있습니다.');
        materialIds.add(material.id);
        string(material.name, materialPath + ' 이름');
        string(material.supplier, materialPath + ' 제조원·공급처');
        choice(material.kind, materialPath + ' 구분', ['api', 'excipient']);
        choice(material.price_unit, materialPath + ' 단가 단위', Object.keys(UNITS));
        fileNumber(material.amount, materialPath + ' 실제 투입량');
        fileNumber(material.price, materialPath + ' 구매단가');
      });
    });
    string(project.active_scenario_id, '현재 시나리오 ID', true);
    if (!ids.has(project.active_scenario_id)) fileError('현재 시나리오를 찾을 수 없습니다.');
    return project;
  }

  function parseProject(text) {
    if (typeof text !== 'string') fileError('파일 내용을 읽지 못했습니다.');
    let project;
    try { project = JSON.parse(text.replace(/^\uFEFF/, '')); }
    catch (_) { fileError('JSON 문법이 올바르지 않습니다. 파일이 손상되었는지 확인해 주세요.'); }
    return validateProject(project);
  }

  function serializeProject(project) {
    validateProject(project);
    return JSON.stringify(project, null, 2) + '\n';
  }

  function parseNumber(value) {
    const issues = [];
    const result = readNumber(value, 'number', '입력값', issues);
    if (issues.length) throw new Error(issues[0].message);
    return result;
  }

  return Object.freeze({ Decimal, FORMAT, VERSION, MAX_SCENARIOS, makeProject, makeScenario, makeMaterial, createExampleProject, cloneScenario, calculate, assessPricing, parseProject, serializeProject, validateProject, parseNumber });
}));
