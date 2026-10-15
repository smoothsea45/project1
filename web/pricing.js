/* Verified, offline price forecasting. Regulatory rounding is isolated from manufacturing costs. */
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
    general_trigger_date: '', general_long_extension: false, migration_review: ''
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
  function assess(scenario, readNumber) {
    const conditions = makePricingConditions(scenario.pricing_conditions);
    const issues = [];
    const notes = ['선택한 조건과 제도 유지 가정에 따른 예상치입니다.', '사용자 지정 2026-08-01 기준이며, 연결된 공식 별표의 산식을 확인하여 적용했습니다.', '최초 제네릭 등재군 참여를 전제로 하며 실거래가·사용량 연동·기등재 재평가 등 사후 조정은 포함하지 않습니다.'];
    const steps = [];
    const effective = { own_data: conditions.own_data === true, dmf: conditions.dmf === true, count: 0, deemed_reasons: [] };
    const result = { amount: null, source: '조건에 따른 예상 약가', status: 'missing', regulation: REGULATION, basis_date: BASIS_DATE, links: [...LINKS], years: [], steps, notes, summary: '', base_amount: null, bonus_amount: null, reduced_amount: null, bonus_kind: 'none', selected_year: conditions.selected_year, effective_requirements: effective, issues };
    function issue(path, message, severity) { issues.push({ path, message, severity: severity || 'error' }); }
    function stop(status, message, path) {
      result.status = status;
      result.summary = message;
      issue(path || 'pricing_conditions.general_subtype', message, status === 'invalid' ? 'error' : 'warning');
      return result;
    }
    if (scenario.pricing_conditions !== undefined && (scenario.pricing_conditions === null || typeof scenario.pricing_conditions !== 'object' || Array.isArray(scenario.pricing_conditions))) return stop('invalid', '약가 조건 형식을 확인해 주세요.', 'pricing_conditions');
    for (const field of BOOLEAN_FIELDS) if (typeof conditions[field] !== 'boolean') issue('pricing_conditions.' + field, '약가 조건의 선택값은 체크 여부여야 합니다.');
    if (!['none', 'data_submission', 'improved', 'biologic'].includes(conditions.general_category)) issue('pricing_conditions.general_category', '일반가산 유형을 확인해 주세요.');
    if (!['none', 'api_self', 'domestic_essential', 'own_injectable_pediatric'].includes(conditions.supply_category)) issue('pricing_conditions.supply_category', '수급안정 가산 유형을 확인해 주세요.');
    if (!['', 'general', 'innovative', 'near', 'supply_leader'].includes(scenario.company_type)) issue('company_type', '기업별 가산 유형을 확인해 주세요.');
    if (!Number.isInteger(conditions.selected_year) || conditions.selected_year < 1 || conditions.selected_year > 10) issue('pricing_conditions.selected_year', '적용 연차는 1~10년차 중에서 선택해 주세요.');
    if (typeof conditions.migration_review !== 'string') issue('pricing_conditions.migration_review', '이전 약가 조건의 확인 상태를 확인해 주세요.');
    if (issues.length) return stop('invalid', '약가 조건의 입력 형식을 확인해 주세요.', 'pricing_conditions');
    if (conditions.migration_review) return stop('needs_conditions', conditions.migration_review, 'pricing_conditions.migration_review');
    if (!validDate(conditions.listing_date)) return stop(blank(conditions.listing_date) ? 'missing' : 'invalid', '예상 등재일을 올바른 날짜로 입력해 주세요.', 'pricing_conditions.listing_date');
    const general = conditions.general_category;
    if (general === 'none' && !['lt14', 'ge14'].includes(scenario.identical_count_band)) return stop('missing', '최초 등재 시 동일제제 품목 수를 선택해 주세요.', 'identical_count_band');
    if (!scenario.company_type) return stop('missing', '기업 유형을 선택해 주세요.', 'company_type');
    if (conditions.supply_category === 'domestic_essential' && conditions.supply_eligible === true) {
      effective.own_data = true; effective.dmf = true;
      effective.deemed_reasons.push('국산 원료 사용 국가필수의약품 요건 확인: 별표 1 제2호가목 표1에 따라 두 기준요건 충족 간주');
    }
    effective.count = Number(effective.own_data) + Number(effective.dmf);
    let base = null, bonus = null, extendedBonus = null, duration = 0, bonusLabel = '', bonusRate = '', baseRate = '', reductionApplies = false;
    if (general === 'none') {
      const original = readNumber(scenario.original_price, 'original_price', '오리지널 기준약가', issues, { required: true, positive: true });
      if (!original) return stop(blank(scenario.original_price) ? 'missing' : 'invalid', '오리지널 기준약가를 0보다 큰 금액으로 입력해 주세요.', 'original_price');
      const rate = ['0.29', '0.36', '0.45'][effective.count];
      base = won(original.times(rate)); baseRate = String(new Decimal(rate).times(100)) + '%';
      steps.push('기본약가: 오리지널 기준약가 ' + original.toString() + ' × ' + baseRate + ' → 원 단위 반올림 ' + base.toString() + '원 (제2호가목(1)·표1)');
      reductionApplies = scenario.identical_count_band === 'ge14';
      const selectedSupply = conditions.supply_category !== 'none';
      const supplyDetail = conditions.supply_category !== 'own_injectable_pediatric' || conditions.supply_detail_eligible === true;
      const supplyEligible = selectedSupply && conditions.supply_eligible === true && effective.count === 2 && supplyDetail;
      if (supplyEligible) {
        bonus = won(base.times(68).div(45)); duration = conditions.supply_extension ? 10 : 5;
        bonusLabel = '수급안정 가산'; bonusRate = '기본약가 × 68/45';
        result.bonus_kind = 'supply';
        notes.push('기업가산을 중복 합산하지 않습니다. 수급안정 가산은 같은 등재일부터 5년을 기산합니다.');
        if (conditions.supply_extension) notes.push('6~10년차: 연장요건 충족 가정이며 확정된 혜택이 아닙니다.');
      } else {
        if (selectedSupply) notes.push('수급안정 가산 미적용: 최초 가산요건, 두 기본 산정요건 및 해당 시 직접생산·공급회사 수 세부요건을 모두 충족해야 합니다.');
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
      }
    } else {
      notes[2] = '일반가산은 해당 개발·허가 경로의 별도 기준금액으로 산정합니다. 일반 제네릭의 14개 이상 감액을 자동 적용하지 않습니다.';
      if (conditions.supply_category !== 'none') return stop('needs_conditions', '추가 산정조건 필요: 자료제출·개량신약 일반가산과 수급안정 가산을 함께 선택한 경로는 제4호다목(4)의 재산정·요건 및 기산일 확인이 필요합니다.', 'pricing_conditions.supply_category');
      if (general === 'biologic') return stop('needs_conditions', '추가 산정조건 필요: 생물의약품은 동등생물·개량생물 구분, 최초등재·조정 경로, 국내 임상 및 인정요건, 비교 상한금액을 확인해야 합니다. 일반 제네릭 45%를 적용하지 않습니다.');
      if (!['salt_isomer', 'new_form', 'new_dose'].includes(conditions.general_subtype)) return stop('needs_conditions', '추가 산정조건 필요: 별첨 1의 염변경·이성체, 새 제형, 새 용법·용량 중 확인된 비생물 단일제 경로를 선택해 주세요. 개량신약복합제는 구성성분별 기준금액·산정경로 확인이 필요합니다.');
      if (general === 'improved' && !conditions.general_recognized) return stop('needs_conditions', '추가 산정조건 필요: 개량신약 인정 여부를 확인해 주세요.', 'pricing_conditions.general_recognized');
      if (conditions.general_target_biologic || conditions.general_reference_own) return stop('needs_conditions', '추가 산정조건 필요: 개발목표가 생물의약품이거나 자사 제품인 산정경로는 별첨 2·표2 등 추가 규정 확인이 필요합니다.');
      if (!conditions.general_first_listed || !conditions.general_dose_equivalent) return stop('needs_conditions', '추가 산정조건 필요: 최초등재제품 여부 및 개발목표제품과의 투약비용 비교기준 확인이 필요합니다.');
      const reference = readNumber(conditions.general_base, 'pricing_conditions.general_base', '개발목표제품 상한금액', issues, { required: true, positive: true });
      if (!reference) return stop(blank(conditions.general_base) ? 'missing' : 'invalid', '별첨 1에 적용할 개발목표제품 상한금액을 입력해 주세요.', 'pricing_conditions.general_base');
      const same = conditions.general_same_reference;
      const rate = conditions.general_subtype === 'new_dose' ? (same ? '1.1' : '1') : (same ? '1' : '0.9');
      base = won(reference.times(rate)); baseRate = '개발목표제품 상한금액 × ' + new Decimal(rate).times(100).toString() + '%';
      steps.push('비생물 자료제출의약품 별첨 1: ' + reference.toString() + ' × ' + new Decimal(rate).times(100).toString() + '% → 원 단위 반올림 ' + base.toString() + '원. 투약비용 비교기준 확인값을 사용합니다.');
      if (same) {
        if (!validDate(conditions.general_trigger_date) || conditions.general_trigger_date !== conditions.listing_date) return stop('needs_conditions', '추가 산정조건 필요: 일반가산의 실제 기산일(개발목표 조정원인 제품의 최초고시일 포함)을 확인해 주세요. 현재 10개 연차 표시는 기산일과 예상 등재일이 같은 경로를 지원합니다.', 'pricing_conditions.general_trigger_date');
        bonus = won(base.times(70).div(45)); duration = conditions.general_extension ? 4 : 1;
        bonusLabel = '자료제출의약품 일반가산'; bonusRate = '별첨 1 산정금액 × 70/45'; result.bonus_kind = 'general';
        if (conditions.general_extension && !conditions.general_recognized) {
          const cap = readNumber(conditions.general_cap, 'pricing_conditions.general_cap', '조정 전 상한금액', issues, { required: true, positive: true });
          if (!cap) return stop('needs_conditions', '추가 산정조건 필요: 비개량 자료제출의약품의 연장기간에는 제4호가목(9)에 따른 조정 전 상한금액 상한을 확인해야 합니다.', 'pricing_conditions.general_cap');
          extendedBonus = Decimal.min(won(base.times(60).div(45)), won(cap));
          notes.push('비개량 자료제출의약품 연장기간인 2~4년차에는 제4호가목(9)·다목(3)에 따라 60/45로 재산정하고 조정 전 상한금액을 한도로 적용합니다.');
        }
        if (conditions.general_long_extension && conditions.general_recognized && conditions.general_extension) {
          duration = 10; notes.push('5~10년차: 개량신약의 동일제제 1개 회사 유지 및 제도 유지 가정입니다. 2개 이상이 되면 가산이 종료됩니다.');
        }
        // Unlike company bonuses, the general bonus must not be silently replaced or summed with a supply bonus.
        if (conditions.supply_category !== 'none') return stop('needs_conditions', '추가 산정조건 필요: 자료제출의약품 일반가산과 수급안정 가산을 함께 선택한 경로는 제4호다목(4)의 재산정·요건 및 기산일 확인이 필요합니다.', 'pricing_conditions.supply_category');
      } else notes.push('개발목표제품과 동일제제가 등재되어 있지 않아 제4호가목(2)의 70/45 가산을 적용하지 않습니다.');
    }
    if (base === null) return stop('needs_conditions', '추가 산정조건 필요');
    const reduced = reductionApplies ? won(base.times('0.85')) : base;
    result.base_amount = base; result.bonus_amount = bonus; result.reduced_amount = reduced;
    if (bonus) steps.push(bonusLabel + ': ' + bonusRate + ' → 원 단위 반올림 ' + bonus.toString() + '원. 기간 ' + duration + '년');
    if (reductionApplies) steps.push('다품목 등재관리: 가산 종료 후(가산이 없으면 1년 유예 후) 기본약가 ' + base.toString() + ' × 85% → 원 단위 반올림 ' + reduced.toString() + '원. 가산약가에는 85%를 적용하지 않습니다.');
    for (let year = 1; year <= 10; year += 1) {
      const inBonus = bonus !== null && year <= duration;
      const inGrace = bonus === null && reductionApplies && year === 1;
      const extension = inBonus && result.bonus_kind === 'general' && year > 1 && extendedBonus !== null;
      const amount = inBonus ? (extension ? extendedBonus : bonus) : (inGrace ? base : reduced);
      const assumption = inBonus && ((result.bonus_kind === 'supply' && year > 5) || (result.bonus_kind === 'general' && year > 4));
      result.years.push({ year, start_date: addYears(conditions.listing_date, year - 1), end_date: previousDay(addYears(conditions.listing_date, year)), calendar_year: Number(conditions.listing_date.slice(0, 4)) + year - 1, amount, kind: inBonus ? 'bonus' : inGrace ? 'grace' : reductionApplies ? 'reduced' : 'base', label: inBonus ? bonusLabel + (assumption ? ' · 연장요건 충족 가정' : extension ? ' · 연장 재산정' : '') : inGrace ? '다품목 감액 유예' : reductionApplies ? '가산 전 기본약가의 85%' : '가산 전 기본약가', rate_label: inBonus ? (extension ? '별첨 1 산정금액 × 60/45 · 상한 적용' : bonusRate) : inGrace ? baseRate : reductionApplies ? baseRate + ' → 기본약가 × 85%' : baseRate, assumption });
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
    if (result.amount.isZero()) issue('original_price', '규정상 원 단위 반올림 결과가 0원이므로 제조원가율은 계산하지 않습니다.', 'warning');
    return result;
  }
  return Object.freeze({ BASIS_DATE, REGULATION, LINKS, CONDITION_DEFAULTS, BOOLEAN_FIELDS, makePricingConditions, validDate, addYears, assess });
}));
