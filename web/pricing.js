/* Offline price forecasting. User-defined simplified schedules and generic rules stay separate. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./vendor/decimal.js'));
  else root.PharmaPricing = factory(root.Decimal);
}(typeof globalThis !== 'undefined' ? globalThis : this, function (DecimalLibrary) {
  'use strict';
  const Decimal = DecimalLibrary.clone({ precision: 256, rounding: DecimalLibrary.ROUND_HALF_UP });
  const BASIS_DATE = '2026-08-01';
  const REGULATION = '약제의 결정 및 조정 기준 별표 1 · 사용자 지정 2026-08-01 기준';
  const LINKS = Object.freeze([
    'https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000283422',
    'https://www.law.go.kr/LSW/flDownload.do?bylClsCd=200201&flSeq=168756835'
  ]);
  const BOOLEAN_FIELDS = Object.freeze(['own_data', 'dmf', 'company_eligible', 'domestic_extension', 'supply_eligible', 'supply_extension', 'supply_detail_eligible', 'general_recognized', 'general_extension', 'general_same_reference', 'general_first_listed', 'general_dose_equivalent', 'general_target_biologic', 'general_reference_own', 'general_long_extension']);
  const CONDITION_DEFAULTS = Object.freeze({
    own_data: false, dmf: false, general_category: 'none', supply_category: 'none',
    company_eligible: false, domestic_extension: false, supply_eligible: false, supply_extension: false, supply_detail_eligible: false,
    listing_date: '', selected_year: 1, general_subtype: '', general_base: null, general_cap: null,
    general_recognized: false, general_extension: false, general_same_reference: false, general_first_listed: false,
    general_dose_equivalent: false, general_target_biologic: false, general_reference_own: false,
    general_trigger_date: '', general_long_extension: false, migration_review: '', model_id: 'simplified-v1'
  });
  function makePricingConditions(options) { return Object.assign({}, CONDITION_DEFAULTS, options || {}); }
  const blank = value => value === null || value === undefined || (typeof value === 'string' && !value.trim());
  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(value + 'T00:00:00Z');
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value && Number(value.slice(0, 4)) >= 1900 && Number(value.slice(0, 4)) <= 9988;
  }
  function addYears(value, years) {
    const [year, month, day] = value.split('-').map(Number);
    const target = year + years;
    const last = new Date(Date.UTC(target, month, 0)).getUTCDate();
    return String(target).padStart(4, '0') + '-' + String(month).padStart(2, '0') + '-' + String(Math.min(day, last)).padStart(2, '0');
  }
  function previousDay(value) {
    const date = new Date(value + 'T00:00:00Z');
    date.setUTCDate(date.getUTCDate() - 1);
    return date.toISOString().slice(0, 10);
  }
  const won = value => new Decimal(value).toDecimalPlaces(0, Decimal.ROUND_HALF_UP);
  // These are user-requested modelling assumptions, not verified legal benefit schedules.
  const SIMPLIFIED_SCHEDULES = Object.freeze({
    data_submission: Object.freeze({ label: '자료제출의약품', periods: [[1, 1, '0.70'], [2, 4, '0.60']] }),
    improved: Object.freeze({ label: '개량신약', periods: [[1, 1, '0.70']] }),
    improved_combo: Object.freeze({ label: '개량신약복합제', periods: [[1, 1, '0.68']] }),
    other: Object.freeze({ label: '기타', periods: [[1, 4, '0.60']] }),
    biologic: Object.freeze({ label: '생물의약품', periods: [[1, 5, '0.80']] })
  });
  // Explicit recovery assumptions are kept here so they can be revised independently.
  const RECOVERY_RATES = Object.freeze({ generic_by_requirement_count: Object.freeze(['0.29', '0.36', '0.45']), biologic: '0.70' });
  function assess(scenario, readNumber) {
    const conditions = makePricingConditions(scenario.pricing_conditions);
    const issues = [];
    const simple = conditions.general_category !== 'none' || conditions.supply_category !== 'none';
    const notes = simple ? [
      '사용자 지정 비율과 기간을 적용한 간편 가정 약가입니다. 실제 법정 약가 산정이나 가산 자격의 검증 결과를 뜻하지 않습니다.',
      '모든 간편 비율은 입력한 오리지널 기준약가에 직접 곱하며, 기존 세부 산정유형·개발목표금액·인정·기산일·연장·자격 체크값은 적용하지 않습니다.',
      '기업별·일반·수급안정 가산을 합산하지 않으며, 수급안정 항목을 선택하면 수급안정 일정 하나를 우선 적용합니다.',
      '간편 일반가산에는 동일제제 14개 이상에 따른 추가 감액을 자동 적용하지 않습니다.'
    ] : [
      '선택한 조건과 제도 유지 가정에 따른 예상치입니다.',
      '사용자 지정 2026-08-01 기준이며, 연결된 공식 별표의 일반 제네릭 산식을 확인하여 적용했습니다.',
      '최초 제네릭 등재군 참여를 전제로 하며 실거래가·사용량 연동·기등재 재평가 등 사후 조정은 포함하지 않습니다.'
    ];
    const steps = [];
    const effective = { own_data: conditions.own_data === true, dmf: conditions.dmf === true, count: Number(conditions.own_data === true) + Number(conditions.dmf === true), deemed_reasons: [] };
    const result = {
      amount: null, source: simple ? '간편 가정 약가' : '조건에 따른 예상 약가', status: 'missing',
      model: simple ? 'simplified-v1' : 'generic-regulation-v1', regulation: simple ? null : REGULATION,
      basis_date: simple ? null : BASIS_DATE, links: simple ? [] : [...LINKS], years: [], steps, notes, summary: '',
      base_amount: null, bonus_amount: null, reduced_amount: null, bonus_kind: 'none', selected_year: conditions.selected_year, effective_requirements: effective, issues
    };
    function issue(path, message, severity) { issues.push({ path, message, severity: severity || 'error' }); }
    function stop(status, message, path) {
      result.status = status; result.summary = message;
      issue(path || 'pricing_conditions.general_category', message, status === 'invalid' ? 'error' : 'warning');
      return result;
    }
    if (scenario.pricing_conditions !== undefined && (scenario.pricing_conditions === null || typeof scenario.pricing_conditions !== 'object' || Array.isArray(scenario.pricing_conditions))) return stop('invalid', '약가 조건 형식을 확인해 주세요.', 'pricing_conditions');
    if (!['none', ...Object.keys(SIMPLIFIED_SCHEDULES)].includes(conditions.general_category)) issue('pricing_conditions.general_category', '일반가산 유형을 확인해 주세요.');
    if (!['none', 'api_self', 'domestic_essential', 'own_injectable_pediatric'].includes(conditions.supply_category)) issue('pricing_conditions.supply_category', '수급안정 가산 유형을 확인해 주세요.');
    const requirementFields = !simple || (conditions.supply_category === 'none' && conditions.general_category !== 'biologic') ? ['own_data', 'dmf'] : [];
    for (const field of requirementFields) if (typeof conditions[field] !== 'boolean') issue('pricing_conditions.' + field, '기본 산정요건의 선택값은 체크 여부여야 합니다.');
    if (!simple) {
      for (const field of ['company_eligible', 'domestic_extension']) if (typeof conditions[field] !== 'boolean') issue('pricing_conditions.' + field, '약가 조건의 선택값은 체크 여부여야 합니다.');
      if (!['', 'general', 'innovative', 'near', 'supply_leader'].includes(scenario.company_type)) issue('company_type', '기업별 가산 유형을 확인해 주세요.');
    }
    if (!Number.isInteger(conditions.selected_year) || conditions.selected_year < 1 || conditions.selected_year > 10) issue('pricing_conditions.selected_year', '적용 연차는 1~10년차 중에서 선택해 주세요.');
    if (typeof conditions.migration_review !== 'string') issue('pricing_conditions.migration_review', '이전 약가 조건의 확인 상태를 확인해 주세요.');
    if (issues.length) return stop('invalid', '약가 조건의 입력 형식을 확인해 주세요.', 'pricing_conditions');
    if (!simple && conditions.migration_review) return stop('needs_conditions', conditions.migration_review, 'pricing_conditions.migration_review');
    if (!validDate(conditions.listing_date)) return stop(blank(conditions.listing_date) ? 'missing' : 'invalid', '예상 등재일을 올바른 날짜로 입력해 주세요.', 'pricing_conditions.listing_date');
    if (!simple && !['lt14', 'ge14'].includes(scenario.identical_count_band)) return stop('missing', '최초 등재 시 동일제제 품목 수를 선택해 주세요.', 'identical_count_band');
    if (!simple && !scenario.company_type) return stop('missing', '기업 유형을 선택해 주세요.', 'company_type');
    const original = readNumber(scenario.original_price, 'original_price', '오리지널 기준약가', issues, { required: true, positive: true });
    if (!original) return stop(blank(scenario.original_price) ? 'missing' : 'invalid', '오리지널 기준약가를 0보다 큰 금액으로 입력해 주세요.', 'original_price');
    let base, bonus = null, duration = 0, bonusLabel = '', bonusRate = '', baseRate = '', reductionApplies = false;
    if (simple) {
      const selectedSupply = conditions.supply_category !== 'none';
      const schedule = SIMPLIFIED_SCHEDULES[conditions.general_category];
      const recoveryRate = conditions.general_category === 'biologic' ? RECOVERY_RATES.biologic : RECOVERY_RATES.generic_by_requirement_count[effective.count];
      base = won(original.times(recoveryRate));
      baseRate = '오리지널 기준약가 × ' + new Decimal(recoveryRate).times(100).toString() + '% · 가산 종료 후 간편 가정';
      result.base_amount = base; result.reduced_amount = base;
      result.bonus_kind = selectedSupply ? 'supply' : 'general';
      notes.push(conditions.general_category === 'biologic' ? '생물의약품은 가산 종료 후 오리지널 기준약가의 70%로 계산한다는 가정을 사용합니다.' : '비생물의약품은 가산 종료 후 기본 산정요건 체크 수에 따른 오리지널 기준약가의 45%·36%·29%로 계산한다는 가정을 사용합니다.');
      if (selectedSupply) notes.push('수급안정 3종 모두 최초 5년 + 추가 5년을 적용하며, 6~10년차는 연장요건 충족 가정입니다. 기본요건·세부 자격 체크와 관계없이 선택한 간편 일정으로 계산합니다.');
      for (let year = 1; year <= 10; year += 1) {
        const period = selectedSupply ? [1, 10, '0.68'] : schedule.periods.find(item => year >= item[0] && year <= item[1]);
        const inBonus = Boolean(period);
        const rate = period ? period[2] : recoveryRate;
        const amount = won(original.times(rate));
        const assumption = selectedSupply && year > 5;
        const label = inBonus ? (selectedSupply ? '수급안정 가산 · 간편 가정' : schedule.label + ' · 간편 가정') + (assumption ? ' · 연장요건 충족 가정' : '') : '가산 종료 후 · 간편 가정';
        result.years.push({ year, start_date: addYears(conditions.listing_date, year - 1), end_date: previousDay(addYears(conditions.listing_date, year)), calendar_year: Number(conditions.listing_date.slice(0, 4)) + year - 1, amount, kind: inBonus ? 'bonus' : 'base', label, rate_label: '오리지널 기준약가 × ' + new Decimal(rate).times(100).toString() + '% · 간편 가정', assumption });
      }
      result.bonus_amount = result.years[0].amount;
      const periods = selectedSupply ? [[1, 5, '0.68'], [6, 10, '0.68']] : schedule.periods;
      for (const [start, end, rate] of periods) steps.push((start === end ? start : start + '~' + end) + '년차: 오리지널 기준약가 ' + original.toString() + ' × ' + new Decimal(rate).times(100).toString() + '% → 원 단위 반올림 ' + won(original.times(rate)).toString() + '원 · 간편 가정' + (selectedSupply && start === 6 ? ' · 연장요건 충족 가정' : ''));
      if (!selectedSupply) steps.push('가산 종료 후: ' + baseRate + ' → ' + base.toString() + '원');
    } else {
      const rate = RECOVERY_RATES.generic_by_requirement_count[effective.count];
      base = won(original.times(rate)); baseRate = String(new Decimal(rate).times(100)) + '%';
      steps.push('기본약가: 오리지널 기준약가 ' + original.toString() + ' × ' + baseRate + ' → 원 단위 반올림 ' + base.toString() + '원 (제2호가목(1)·표1)');
      reductionApplies = scenario.identical_count_band === 'ge14';
      if (scenario.company_type !== 'general') {
        const multipleApiRows = Array.isArray(scenario.materials) && scenario.materials.filter(material => material.kind === 'api').length > 1;
        if (effective.count === 2 && conditions.company_eligible === true && !multipleApiRows) {
          const numerator = scenario.company_type === 'innovative' ? 60 : 50;
          bonus = won(base.times(numerator).div(45)); duration = conditions.domestic_extension ? 4 : 1;
          bonusLabel = scenario.company_type === 'innovative' ? '혁신형 기업가산' : scenario.company_type === 'near' ? '준혁신형 기업가산' : '수급안정 선도기업 가산';
          bonusRate = '기본약가 × ' + numerator + '/45'; result.bonus_kind = 'company';
          if (conditions.domestic_extension) notes.push('국내생산 연장요건 충족 시나리오로 총 4년간 기업가산을 적용합니다.');
        } else notes.push(multipleApiRows && conditions.company_eligible ? '기업가산 미적용: API가 복수 행으로 입력되어 일반 단일제 여부를 확정할 수 없습니다. 복합제는 제4호가목(1)(가)의 기업가산 대상에서 제외되며, 적용 산정경로를 확인해야 합니다.' : '기업가산 미적용: 일반 단일제 제네릭 적용대상 확인 및 두 기본 산정요건을 모두 충족해야 합니다. 기업 자격 선택만으로 가산하지 않습니다.');
      }
      const reduced = reductionApplies ? won(base.times('0.85')) : base;
      result.base_amount = base; result.bonus_amount = bonus; result.reduced_amount = reduced;
      if (bonus) steps.push(bonusLabel + ': ' + bonusRate + ' → 원 단위 반올림 ' + bonus.toString() + '원. 기간 ' + duration + '년');
      if (reductionApplies) steps.push('다품목 등재관리: 가산 종료 후(가산이 없으면 1년 유예 후) 기본약가 ' + base.toString() + ' × 85% → 원 단위 반올림 ' + reduced.toString() + '원. 가산약가에는 85%를 적용하지 않습니다.');
      for (let year = 1; year <= 10; year += 1) {
        const inBonus = bonus !== null && year <= duration;
        const inGrace = bonus === null && reductionApplies && year === 1;
        const amount = inBonus ? bonus : (inGrace ? base : reduced);
        result.years.push({ year, start_date: addYears(conditions.listing_date, year - 1), end_date: previousDay(addYears(conditions.listing_date, year)), calendar_year: Number(conditions.listing_date.slice(0, 4)) + year - 1, amount, kind: inBonus ? 'bonus' : inGrace ? 'grace' : reductionApplies ? 'reduced' : 'base', label: inBonus ? bonusLabel : inGrace ? '다품목 감액 유예' : reductionApplies ? '가산 전 기본약가의 85%' : '가산 전 기본약가', rate_label: inBonus ? bonusRate : inGrace ? baseRate : reductionApplies ? baseRate + ' → 기본약가 × 85%' : baseRate, assumption: false });
      }
    }
    result.amount = result.years[conditions.selected_year - 1].amount;
    result.status = result.amount.isZero() ? 'zero' : 'ready';
    const groups = [];
    for (const entry of result.years) {
      const last = groups[groups.length - 1];
      if (last && last.amount.eq(entry.amount) && last.assumption === entry.assumption) last.end = entry.year;
      else groups.push({ start: entry.year, end: entry.year, amount: entry.amount, assumption: entry.assumption });
    }
    result.summary = groups.map(group => group.start + (group.end === group.start ? '' : '~' + group.end) + '년차 ' + group.amount.toString() + '원' + (group.assumption ? ' (연장요건 충족 가정)' : '')).join(' → ');
    if (result.amount.isZero()) issue('original_price', '원 단위 반올림 결과가 0원이므로 제조원가율은 계산하지 않습니다.', 'warning');
    return result;
  }
  return Object.freeze({ BASIS_DATE, REGULATION, LINKS, CONDITION_DEFAULTS, BOOLEAN_FIELDS, makePricingConditions, SIMPLIFIED_SCHEDULES, RECOVERY_RATES, validDate, addYears, assess });
}));
