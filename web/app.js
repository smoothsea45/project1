/* Offline application controller. Domain arithmetic lives in engine.js. */
(function () {
  'use strict';
  const E = window.PharmaCost;
  const $ = id => document.getElementById(id);
  if (!E) { $('app-status').textContent = '계산 파일을 불러오지 못했습니다. ZIP 전체를 압축 해제했는지 확인하세요.'; return; }
  const D = window.Decimal;
  const STORAGE_KEY = 'pharma-cost-web-draft-v1';
  const kindNames = {api: 'API', excipient: '부형제'};
  const unitNames = {krw_g: '원/g', krw_kg: '원/kg', usd_g: '달러/g', usd_kg: '달러/kg'};
  let project = E.createExampleProject();
  let dirty = false;
  let selectedRows = new Set();
  let currentResult;
  let toastTimer;
  let storageMessage = '';
  let storageAvailable = true;
  let loadNotice = '';
  try {
    const draft = localStorage.getItem(STORAGE_KEY);
    if (draft) {
      project = useManualPricing(E.parseProject(draft));
      loadNotice = '이 브라우저에 저장된 초안을 복원했습니다. 약가는 직접 입력값을 사용합니다.';
    }
  } catch (error) {
    storageAvailable = false;
    loadNotice = '기존 브라우저 초안을 그대로 보관했습니다. 복원할 수 없습니다: ' + error.message;
  }

  function useManualPricing(value) {
    // The current screen supports direct pricing only; preserve all entered amounts.
    value.scenarios.forEach(s => { s.pricing_mode = 'manual'; });
    return value;
  }

  function active() { return project.scenarios.find(s => s.id === project.active_scenario_id); }
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function format(value, digits = 2, missing = '미완성') {
    if (value === null || value === undefined) return missing;
    let number;
    try { number = value instanceof D ? value : E.parseNumber(value); } catch (error) { return missing; }
    if (number === null) return missing;
    if (number.abs().gte('1e15')) return number.toExponential(digits);
    const parts = number.toFixed(digits).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return parts[0] + (parts[1] ? '.' + parts[1] : '');
  }
  function percentage(value, missing = '계산 불가', suffix = true) {
    if (value === null || value === undefined) return missing;
    const text = value.gt(0) && value.lt('0.1') ? '<0.1' : format(value, 1, missing);
    return text + (suffix ? '%' : '');
  }
  function rate(value) { return percentage(value); }
  // Keep every decimal digit the user entered. Separators are only presentation.
  function numericEntry(raw) {
    const text = String(raw === null || raw === undefined ? '' : raw).trim();
    if (!text) return {value: '', display: ''};
    try { if (E.parseNumber(text) === null) return {value: text, display: text}; }
    catch (error) { return {value: text, display: text}; }
    const value = text.replace(/,/g, '');
    const match = /^([+]?)(\d*)(\.\d*)?$/.exec(value);
    if (!match) return {value, display: value};
    return {value, display: match[1] + match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (match[3] || '')};
  }
  function setNumericDisplay(input, value) {
    input.value = numericEntry(value).display;
    input.dataset.numericDisplay = input.value;
  }
  function inputPosition(text, digitCount) {
    if (digitCount <= 0) return 0;
    let count = 0;
    for (let i = 0; i < text.length; i++) {
      if (text[i] !== ',') count++;
      if (count === digitCount) return i + 1;
    }
    return text.length;
  }
  function bindNumericInput(input, callback) {
    function commit(event) {
      const raw = input.value;
      const start = input.selectionStart === null ? raw.length : input.selectionStart;
      const end = input.selectionEnd === null ? start : input.selectionEnd;
      const direction = input.selectionDirection || 'none';
      const previous = input.dataset.numericDisplay || '';
      let candidate = raw;
      const inputType = event && typeof event.inputType === 'string' ? event.inputType : '';
      const interactive = inputType.startsWith('delete') || (inputType === 'insertText' && typeof event.data === 'string' && !event.data.includes(','));
      if (interactive && previous.includes(',') && raw.includes(',')) {
        try {
          if (E.parseNumber(previous) !== null) candidate = raw.replace(/,/g, '');
        } catch (error) { /* Malformed imported/pasted values must remain visible. */ }
      }
      const entry = numericEntry(candidate);
      input.value = entry.display;
      const before = raw.slice(0, start).replace(/,/g, '').length;
      const after = raw.slice(0, end).replace(/,/g, '').length;
      if (entry.display !== raw) input.setSelectionRange(inputPosition(entry.display, before), inputPosition(entry.display, after), direction);
      input.dataset.numericDisplay = entry.display;
      callback(entry.value);
    }
    input.addEventListener('input', commit);
    input.addEventListener('beforeinput', event => {
      const caret = input.selectionStart;
      if (caret === null || caret !== input.selectionEnd) return;
      let start = caret;
      let end = caret;
      if (event.inputType === 'deleteContentBackward' && input.value[caret - 1] === ',') start = Math.max(0, caret - 2);
      else if (event.inputType === 'deleteContentForward' && input.value[caret] === ',') end = Math.min(input.value.length, caret + 2);
      else return;
      event.preventDefault();
      input.value = input.value.slice(0, start) + input.value.slice(end);
      input.setSelectionRange(start, start);
      commit({inputType: event.inputType, data: null});
    });
  }
  function showToast(message) {
    clearTimeout(toastTimer);
    $('toast').textContent = message;
    $('toast').hidden = false;
    toastTimer = setTimeout(() => { $('toast').hidden = true; }, 6000);
  }
  function updateStatus() {
    $('project-status').textContent = dirty ? '파일 저장 필요' : '프로젝트 파일';
    $('app-status').textContent = storageMessage || loadNotice || '파일은 내 컴퓨터에 저장됩니다.';
    document.title = (dirty ? '* ' : '') + (project.product.product_name || '의약품 제조원가율 시뮬레이터');
  }
  function persistDraft() {
    if (!storageAvailable) return;
    try {
      const data = E.serializeProject(project);
      localStorage.setItem(STORAGE_KEY, data);
      storageMessage = '브라우저 초안 저장됨 · 보관하려면 프로젝트 저장을 눌러 주세요.';
    } catch (error) {
      if (error.name === 'QuotaExceededError' || error.name === 'SecurityError') {
        storageAvailable = false;
        storageMessage = '브라우저 초안 저장이 불가능합니다. JSON 파일로 저장해 주세요.';
      } else storageMessage = '숫자 입력 오류를 수정하면 브라우저 초안이 저장됩니다.';
    }
  }
  function changed() {
    dirty = true;
    recalculate();
    persistDraft();
    updateStatus();
  }
  function populateFields() {
    const s = active();
    document.querySelectorAll('[data-product-field]').forEach(input => { input.value = project.product[input.dataset.productField] || ''; });
    document.querySelectorAll('[data-field]').forEach(input => {
      const value = s[input.dataset.field];
      if (input.type === 'radio') input.checked = value === input.value;
      else if (input.inputMode === 'decimal') setNumericDisplay(input, value);
      else input.value = value === null || value === undefined ? '' : value;
    });
    document.querySelectorAll('[data-pricing-flag]').forEach(input => { input.checked = s.pricing_flags.includes(input.dataset.pricingFlag); });
  }
  function renderScenarioTabs() {
    $('scenario-tabs').replaceChildren();
    for (const s of project.scenarios) {
      const selected = s.id === project.active_scenario_id;
      const button = element('button', s.name, 'scenario-tab' + (selected ? ' active' : ''));
      button.type = 'button'; button.dataset.scenarioId = s.id;
      button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      button.title = s.name;
      button.addEventListener('click', () => activateScenario(s.id));
      $('scenario-tabs').append(button);
    }
    $('delete-scenario').disabled = project.scenarios.length < 2;
    $('clone-scenario').disabled = project.scenarios.length >= E.MAX_SCENARIOS;
    $('clone-scenario').title = project.scenarios.length >= E.MAX_SCENARIOS ? '한 프로젝트에는 최대 ' + E.MAX_SCENARIOS + '개 시나리오를 만들 수 있습니다.' : '현재 입력값을 새 시나리오로 복제합니다.';
    $('scenario-count').textContent = project.scenarios.length + '개 시나리오';
  }
  function activateScenario(id) {
    if (id === project.active_scenario_id || !project.scenarios.some(s => s.id === id)) return;
    project.active_scenario_id = id;
    selectedRows = new Set();
    populateFields(); renderScenarioTabs(); renderMaterials(); changed();
    [...$('scenario-tabs').children].find(button => button.dataset.scenarioId === id).focus();
  }
  function tableInput(row, field, label, numeric = false) {
    const input = element('input');
    input.type = 'text';
    input.value = row[field] === null ? '' : row[field];
    input.dataset.materialField = field;
    input.setAttribute('aria-label', label);
    if (numeric) {
      input.inputMode = 'decimal';
      setNumericDisplay(input, row[field]);
      bindNumericInput(input, value => { row[field] = value; changed(); });
    } else input.addEventListener('input', () => { row[field] = input.value; changed(); });
    return input;
  }
  function tableSelect(row, field, names, label) {
    const select = element('select');
    select.dataset.materialField = field;
    select.setAttribute('aria-label', label);
    for (const [value, labelText] of Object.entries(names)) {
      const option = element('option', labelText); option.value = value; select.append(option);
    }
    select.value = row[field];
    select.addEventListener('change', () => { row[field] = select.value; changed(); });
    return select;
  }
  function renderMaterials() {
    $('material-body').replaceChildren();
    for (const [index, row] of active().materials.entries()) {
      const tr = element('tr');
      tr.dataset.materialId = row.id;
      const checkbox = element('input'); checkbox.type = 'checkbox';
      checkbox.checked = selectedRows.has(row.id);
      checkbox.setAttribute('aria-label', '원료 ' + (index + 1) + '행 선택');
      checkbox.addEventListener('change', () => {
        checkbox.checked ? selectedRows.add(row.id) : selectedRows.delete(row.id);
        updateSelection();
      });
      const selectCell = element('td'); selectCell.append(checkbox); tr.append(selectCell);
      for (const field of ['kind', 'name', 'supplier', 'amount', 'price', 'price_unit']) {
        const td = element('td', undefined, ['amount', 'price'].includes(field) ? 'numeric' : '');
        const label = '원료 ' + (index + 1) + ' ' + ({kind: '구분', name: '원료명', supplier: '제조원·공급처', amount: '실제 투입량 mg/T', price: '구매단가', price_unit: '단가 단위'}[field]);
        td.append(field === 'kind' ? tableSelect(row, field, kindNames, label) : field === 'price_unit' ? tableSelect(row, field, unitNames, label) : tableInput(row, field, label, ['amount', 'price'].includes(field)));
        tr.append(td);
      }
      for (const output of ['batch_cost', 'unit_cost']) {
        const td = element('td', '미완성', 'cost-cell computed'); td.dataset.resultField = output; tr.append(td);
      }
      $('material-body').append(tr);
    }
    $('materials-empty').hidden = active().materials.length !== 0;
    updateSelection();
  }
  function updateSelection() {
    const count = active().materials.length;
    $('select-all-materials').checked = count > 0 && selectedRows.size === count;
    $('select-all-materials').indeterminate = selectedRows.size > 0 && selectedRows.size < count;
    $('delete-materials').disabled = selectedRows.size === 0;
  }
  function renderAll() {
    selectedRows = new Set();
    populateFields(); renderScenarioTabs(); renderMaterials(); recalculate(); updateStatus();
    $('example-banner').hidden = !project.is_example;
  }
  function markValidation(result) {
    document.querySelectorAll('[data-field],[data-material-field]').forEach(input => { input.removeAttribute('aria-invalid'); input.removeAttribute('title'); });
    $('material-body').querySelectorAll('tr').forEach(tr => tr.classList.remove('invalid-row'));
    for (const issue of result.issues) {
      let input;
      if (issue.path.startsWith('materials.')) {
        const [, id, field] = issue.path.split('.');
        const tr = [...$('material-body').children].find(row => row.dataset.materialId === id);
        input = tr && tr.querySelector('[data-material-field="' + field + '"]');
        if (tr && issue.severity === 'error') tr.classList.add('invalid-row');
      } else input = document.querySelector('[data-field="' + issue.path + '"]');
      if (input) {
        if (issue.severity === 'error') input.setAttribute('aria-invalid', 'true');
        input.title = issue.message;
      }
    }
    $('input-errors').replaceChildren();
    $('input-errors').hidden = result.issues.length === 0;
    if (result.issues.length) {
      const ul = element('ul');
      for (const issue of result.issues) {
        let prefix = issue.severity === 'warning' ? '안내: ' : '';
        if (issue.path.startsWith('materials.')) {
          const index = active().materials.findIndex(row => row.id === issue.path.split('.')[1]);
          prefix += '원료 ' + (index + 1) + '행: ';
        }
        ul.append(element('li', prefix + issue.message));
      }
      $('input-errors').append(ul);
    }
  }
  function recalculate() {
    const result = E.calculate(active());
    currentResult = result;
    const rows = new Map(result.rows.map(row => [row.id, row]));
    for (const tr of $('material-body').children) {
      const calculated = rows.get(tr.dataset.materialId);
      for (const cell of tr.querySelectorAll('[data-result-field]')) {
        const value = calculated ? calculated[cell.dataset.resultField] : null;
        cell.textContent = format(value);
        cell.title = value === null ? '계산에 필요한 값을 입력하세요.' : format(value);
      }
    }
    for (const [id, field] of Object.entries({'api-batch': 'api_batch', 'excipient-batch': 'excipient_batch', 'api-unit': 'api_unit', 'excipient-unit': 'excipient_unit', 'packaging-unit': 'packaging_unit', 'labor-unit': 'labor_unit'})) $(id).textContent = format(result[field]);
    markValidation(result);
    $('result-cost').textContent = format(result.total_cost);
    $('result-price').textContent = format(result.pricing.amount, 2, '미입력');
    $('result-rate').textContent = percentage(result.cost_rate, '계산 불가', false);
    $('batch-total-note').textContent = '배치 전체 비용 ' + format(result.batch_total) + ' 원';
    renderPricing(result.pricing); renderComposition(result); renderComparison();
  }
  function renderPricing(pricing) {
    $('pricing-status').textContent = '사용자 입력값';
    $('pricing-status').className = 'status-pill success';
    $('pricing-source').textContent = pricing.source;
    $('pricing-input-note').textContent = '가산 조건은 기록만 합니다. 원가율에는 직접 입력한 우리 제품 예상 약가를 사용합니다.';
  }
  function renderComposition(result, root = document.querySelector('.composition-card')) {
    const parts = {
      'composition-body': 'body', 'composition-stack': 'stack', 'composition-donut': 'donut',
      'raw-material-total': 'raw-total', 'raw-material-share': 'raw-share',
      'donut-rate': 'rate', 'donut-total': 'total', 'donut-note': 'note',
      'composition-remainder': 'remainder', 'composition-status': 'status'
    };
    const part = id => root.querySelector('[data-chart-part="' + parts[id] + '"]');
    const items = [['API', 'api', result.api_unit], ['부형제', 'excipient', result.excipient_unit], ['포장재비', 'packaging', result.packaging_unit], ['공수비', 'labor', result.labor_unit]];
    const total = result.total_cost;
    const price = result.pricing.amount;
    const complete = result.total_cost !== null;
    const positiveCost = complete && total.gt(0);
    const validPrice = price !== null && price.gt(0);
    const overPrice = positiveCost && validPrice && total.gt(price);
    const shareText = share => percentage(share, '—');
    const notices = [];
    part('composition-body').replaceChildren();
    part('composition-stack').replaceChildren();
    part('composition-body').style.gridTemplateRows = items.map(([, , cost]) => {
      const weight = positiveCost && cost !== null ? cost.div(total).mul(100).toNumber() : 1;
      return 'minmax(min-content, ' + weight + 'fr)';
    }).join(' ');

    // The enlarged stack and its labels use the same already-calculated costs.
    for (const [label, cls, cost] of items) {
      const share = positiveCost && cost !== null ? cost.div(total).mul(100) : null;
      const row = element('div', undefined, 'composition-row');
      row.dataset.item = cls;
      row.setAttribute('role', 'listitem');
      const labelNode = element('div', undefined, 'composition-label');
      const dot = element('span', '', 'legend-dot ' + cls);
      dot.setAttribute('aria-hidden', 'true');
      const nameAndShare = element('span');
      nameAndShare.append(document.createTextNode(label + ' '), element('span', shareText(share), 'composition-share'));
      labelNode.append(dot, nameAndShare);
      const amount = element('span', format(cost) + (cost === null ? '' : ' 원/T'), 'composition-amount');
      amount.title = cost === null ? '이 항목의 입력이 미완성입니다.' : format(cost) + ' 원/T';
      row.append(labelNode, amount);
      part('composition-body').append(row);
      if (share !== null) {
        const segment = element('span', undefined, 'composition-segment ' + cls);
        segment.dataset.item = cls;
        segment.dataset.share = share.toString();
        segment.style.height = share.toNumber() + '%';
        segment.title = label + ' ' + shareText(share) + ' · ' + format(cost) + ' 원/T';
        part('composition-stack').append(segment);
      }
    }
    part('composition-stack').dataset.state = !complete ? 'incomplete' : positiveCost ? 'ready' : 'zero';
    part('composition-stack').setAttribute('aria-label', !complete ? '필수 비용 입력이 미완성입니다. 제조원가 구성비를 계산할 수 없습니다.' : positiveCost ? '총 제조원가 기준. 위에서부터 API, 부형제, 포장재비, 공수비 순서입니다.' : '제조원가가 0원입니다. 총 제조원가 기준 구성비는 계산할 수 없습니다.');
    part('raw-material-total').textContent = format(result.raw_unit) + (result.raw_unit === null ? '' : ' 원/T');
    const rawShare = positiveCost && result.raw_unit !== null ? result.raw_unit.div(total).mul(100) : null;
    part('raw-material-share').textContent = shareText(rawShare);
    part('raw-material-share').title = '총 제조원가 대비 원재료비 비율';

    // An annular SVG avoids rounding or truncating the underlying Decimal data.
    const namespace = 'http://www.w3.org/2000/svg';
    const svgNode = (tag, attributes) => {
      const node = document.createElementNS(namespace, tag);
      for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
      return node;
    };
    const svg = svgNode('svg', {viewBox: '0 0 200 200', 'aria-hidden': 'true'});
    svg.append(svgNode('circle', {cx: 100, cy: 100, r: 80, fill: 'none', stroke: '#e3e8eb', 'stroke-width': 28}));
    let startAngle = -90;
    const point = (radius, angle) => {
      const radians = angle * Math.PI / 180;
      return (100 + radius * Math.cos(radians)).toFixed(6) + ' ' + (100 + radius * Math.sin(radians)).toFixed(6);
    };
    function appendSlice(cls, share, label, cost) {
      if (!share.gt(0)) return;
      const sweep = share.div(100).mul(360).toNumber();
      const endAngle = startAngle + sweep;
      let path;
      if (share.gte(100)) {
        path = 'M 100 6 A 94 94 0 1 1 100 194 A 94 94 0 1 1 100 6 Z M 100 34 A 66 66 0 1 0 100 166 A 66 66 0 1 0 100 34 Z';
      } else {
        const large = sweep > 180 ? 1 : 0;
        path = 'M ' + point(94, startAngle) + ' A 94 94 0 ' + large + ' 1 ' + point(94, endAngle) + ' L ' + point(66, endAngle) + ' A 66 66 0 ' + large + ' 0 ' + point(66, startAngle) + ' Z';
      }
      const segment = svgNode('path', {d: path, fill: cls === 'remainder' ? '#e3e8eb' : 'var(--' + cls + ')', 'fill-rule': 'evenodd', 'data-item': cls, 'data-share': share.toString()});
      const title = svgNode('title', {});
      title.textContent = label + ' ' + shareText(share) + ' · ' + format(cost) + ' 원/T';
      segment.append(title);
      svg.append(segment);
      startAngle = endAngle;
    }
    const donut = part('composition-donut');
    donut.dataset.basis = !complete || !validPrice ? 'unavailable' : overPrice ? 'manufacturing' : 'insurance';
    const denominator = complete && validPrice ? (overPrice ? total : price) : null;
    if (denominator !== null) {
      for (const [label, cls, cost] of items) appendSlice(cls, cost.div(denominator).mul(100), label, cost);
      if (!overPrice && price.gt(total)) appendSlice('remainder', price.minus(total).div(price).mul(100), '보험약가와 제조원가의 차액', price.minus(total));
    }
    donut.replaceChildren(svg);
    const centerRate = !complete ? '미완성' : !validPrice || result.cost_rate === null ? '계산 불가' : shareText(result.cost_rate);
    part('donut-rate').textContent = centerRate;
    part('donut-rate').style.fontSize = centerRate.includes('%') ? Math.max(10, Math.min(root.classList.contains('comparison-composition') ? 22 : 32, Math.floor((root.classList.contains('comparison-composition') ? 156 : 224) / centerRate.length))) + 'px' : '18px';
    part('donut-total').textContent = complete ? format(total) + ' 원/T' : '제조원가 미완성';
    part('composition-remainder').textContent = complete && validPrice ? format(price.minus(total)) + ' 원/T' : '계산 불가';
    part('donut-note').textContent = !complete ? '보험약가 기준 · 비용 입력 미완성' : !validPrice ? '보험약가 미입력·0·미확인' : overPrice ? '약가 초과 · 도넛은 제조원가 기준' : '보험약가 기준 · ' + format(price) + ' 원/T';
    if (!complete) notices.push('필수 비용을 입력하면 두 그래프의 비율을 표시합니다. 계산 가능한 항목의 금액은 유지합니다.');
    else {
      if (!validPrice) notices.push('보험약가가 없거나 0 또는 미확인 상태여서 도넛의 약가 대비 비율은 계산 불가입니다.');
      if (!positiveCost) notices.push('제조원가가 0원이므로 오른쪽 구성비와 원재료비 비율은 계산 불가(—)입니다.');
      if (overPrice) notices.push('제조원가가 보험약가를 초과했습니다. 중앙에는 실제 약가 대비 원가율을 표시하며, 도넛 구간은 제조원가 전체를 기준으로 표시합니다. 회색 차액 구간은 없습니다.');
    }
    part('composition-status').textContent = notices.join(' ');
    part('composition-status').hidden = notices.length === 0;
    donut.setAttribute('aria-label', notices.length ? centerRate + ', 총 제조원가 ' + format(total) + ' 원/T. ' + notices.join(' ') : '보험약가 ' + format(price) + ' 원/T 기준 API·부형제·포장재비·공수비와 차액. 제조원가율 ' + centerRate + ', 제조원가 ' + format(total) + ' 원/T.');
  }
  function renderComparison() {
    $('comparison-head').replaceChildren(); $('comparison-body').replaceChildren();
    $('comparison-body').closest('table').style.width = (166 + project.scenarios.length * 340) + 'px';
    const header = element('tr');
    const itemHeader = element('th', '비교 항목', 'row-label');
    itemHeader.scope = 'col'; header.append(itemHeader);
    const unitHeader = element('tr', undefined, 'comparison-unit-header');
    unitHeader.dataset.comparisonField = 'cost_basis';
    const costHeader = element('th', '비용 구분', 'row-label');
    costHeader.scope = 'row'; unitHeader.append(costHeader);
    for (const s of project.scenarios) {
      const th = element('th', s.name, s.id === project.active_scenario_id ? 'current' : '');
      th.scope = 'colgroup'; th.colSpan = 2; th.dataset.scenarioId = s.id; header.append(th);
      for (const [basis, label] of [['batch', '배치당 (원)'], ['unit', '1T당 (원/T)']]) {
        const unit = element('th', label, s.id === project.active_scenario_id ? 'current' : '');
        unit.scope = 'col'; unit.dataset.scenarioId = s.id; unit.dataset.costBasis = basis;
        unitHeader.append(unit);
      }
    }
    $('comparison-head').append(header);
    const results = project.scenarios.map(s => E.calculate(s));
    const apiDetails = (s, value) => {
      const list = element('div', undefined, 'comparison-api-list');
      for (const material of s.materials.filter(m => m.kind === 'api')) {
        const item = element('div');
        item.append(element('span', material.name || 'API', 'comparison-api-name'), element('span', value(material)));
        list.append(item);
      }
      if (!list.childElementCount) list.textContent = 'API 없음';
      return list;
    };
    const rows = [
      ['name', '시나리오명', s => s.name],
      ['batch_size', '배치사이즈 (T)', s => format(s.batch_size, 0, '미입력')],
      ['yield_percent', '수율 (%)', s => format(s.yield_percent, 1, '미입력') + (s.yield_percent === null || s.yield_percent === '' ? '' : '%')],
      ['packaging_form', '포장형태', s => s.packaging_form || '미입력'],
      ['api_supplier', 'API 제조원', s => apiDetails(s, m => m.supplier || '제조원 미입력')],
      ['api_price', 'API 단가', s => apiDetails(s, m => format(m.price, 2, '미입력') + ' ' + unitNames[m.price_unit])],
      ['price', '우리 제품 약가 (원/T)', (s, r) => format(r.pricing.amount, 2, '계산 불가')],
      ['total_cost', '제조원가 (원/T)', (s, r) => format(r.total_cost)],
      ['cost_rate', '제조원가율 (%)', (s, r) => rate(r.cost_rate)],
      ['composition', '비용 구성 그래프', (s, r) => {
        const chart = element('div', undefined, 'comparison-composition');
        chart.dataset.scenarioId = s.id;
        chart.append(document.querySelector('.composition-card .composition-charts').cloneNode(true), document.querySelector('.composition-card .composition-status').cloneNode(true));
        chart.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
        renderComposition(r, chart);
        return chart;
      }],
      ['api_cost', 'API 비용', (s, r) => [r.api_batch, r.api_unit]],
      ['excipient_cost', '부형제 비용', (s, r) => [r.excipient_batch, r.excipient_unit]],
      ['packaging_cost', '포자재비', (s, r) => [s.batch_packaging, r.packaging_unit]],
      ['labor_cost', '공수비', (s, r) => [s.batch_labor, r.labor_unit]]
    ];
    for (const [field, label, value] of rows) {
      if (field === 'api_cost') $('comparison-body').append(unitHeader);
      const tr = element('tr'); tr.dataset.comparisonField = field;
      if (['price', 'total_cost', 'cost_rate'].includes(field)) tr.className = 'emphasis-row';
      if (field === 'composition') tr.className = 'comparison-chart-row';
      const th = element('th', label, 'row-label'); th.scope = 'row'; tr.append(th);
      project.scenarios.forEach((s, index) => {
        const content = value(s, results[index]);
        if (Array.isArray(content)) {
          content.forEach((amount, costIndex) => {
            const td = element('td', format(amount), 'comparison-cost-cell numeric' + (s.id === project.active_scenario_id ? ' current' : ''));
            td.dataset.scenarioId = s.id; td.dataset.costBasis = costIndex === 0 ? 'batch' : 'unit';
            td.title = (costIndex === 0 ? '배치당: ' : '1T당: ') + format(amount) + (costIndex === 0 ? ' 원' : ' 원/T');
            tr.append(td);
          });
          return;
        }
        const td = element('td', undefined, s.id === project.active_scenario_id ? 'current' : '');
        td.colSpan = 2; td.dataset.scenarioId = s.id;
        if (typeof content === 'string') { td.textContent = content; td.title = content; }
        else { td.append(content); td.classList.add(field === 'composition' ? 'comparison-chart-cell' : 'text-value'); }
        tr.append(td);
      });
      $('comparison-body').append(tr);
    }
  }
  function selectTab(name) {
    document.querySelectorAll('[data-tab]').forEach(button => {
      const selected = button.dataset.tab === name; button.classList.toggle('active', selected); button.setAttribute('aria-selected', String(selected));
    });
    for (const panel of ['input', 'results', 'comparison']) $('tab-' + panel).hidden = name !== panel;
    document.querySelectorAll('[data-tab]').forEach(button => { button.tabIndex = button.dataset.tab === name ? 0 : -1; });
  }
  function prepareComparisonPrint() {
    renderComparison();
    $('print-product-name').textContent = project.product.product_name || '의약품 제조원가율 시뮬레이션';
    $('print-product-notes').textContent = project.product.notes;
    $('print-product-notes').hidden = !project.product.notes;
    $('print-date').textContent = new Date().toLocaleDateString('ko-KR');
    document.body.classList.add('printing-comparison');
  }
  function saveFile() {
    try {
      const data = E.serializeProject(project);
      const blob = new Blob([data], {type: 'application/json;charset=utf-8'});
      const url = URL.createObjectURL(blob); const a = element('a');
      const name = (project.product.product_name || '제조원가 프로젝트').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_');
      a.href = url; a.download = name + '.json'; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      dirty = false; persistDraft(); updateStatus(); showToast('프로젝트 JSON 파일을 내려받았습니다. 브라우저 다운로드 폴더를 확인하세요.');
      return true;
    } catch (error) { showToast('저장할 수 없습니다: ' + error.message); return false; }
  }
  async function confirmDiscard() {
    if (!dirty) return true;
    const dialog = element('dialog', undefined, 'project-dialog');
    dialog.innerHTML = '<h2>저장하지 않은 변경사항</h2><p>현재 프로젝트를 JSON 파일로 저장할까요?</p><div class="dialog-actions"><button class="button primary" data-choice="save">파일로 저장</button><button class="button outline" data-choice="discard">저장하지 않고 진행</button><button class="button subtle" data-choice="cancel">취소</button></div>';
    document.body.append(dialog);
    return new Promise(resolve => {
      let settled = false;
      const finish = value => { if (settled) return; settled = true; dialog.close(); dialog.remove(); resolve(value); };
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
      for (const button of dialog.querySelectorAll('[data-choice]')) button.addEventListener('click', () => {
        const choice = button.dataset.choice;
        if (choice === 'save') { if (saveFile()) finish(true); }
        else finish(choice === 'discard');
      });
      dialog.showModal();
    });
  }
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => selectTab(button.dataset.tab)));
  document.querySelectorAll('[data-product-field]').forEach(input => input.addEventListener('input', () => { project.product[input.dataset.productField] = input.value; changed(); }));
  document.querySelectorAll('[data-field]').forEach(input => {
    if (input.inputMode === 'decimal') {
      bindNumericInput(input, value => { active()[input.dataset.field] = value; changed(); });
      return;
    }
    const event = input.type === 'radio' || input.tagName === 'SELECT' ? 'change' : 'input';
    input.addEventListener(event, () => {
      if (input.type === 'radio' && !input.checked) return;
      active()[input.dataset.field] = input.value;
      changed();
    });
  });
  document.querySelectorAll('[data-pricing-flag]').forEach(input => input.addEventListener('change', () => {
    active().pricing_flags = [...document.querySelectorAll('[data-pricing-flag]:checked')].map(node => node.dataset.pricingFlag);
    changed();
  }));
  $('clone-scenario').addEventListener('click', () => {
    if (project.scenarios.length >= E.MAX_SCENARIOS) { showToast('한 프로젝트에는 최대 ' + E.MAX_SCENARIOS + '개 시나리오를 만들 수 있습니다.'); return; }
    const name = prompt('복제할 시나리오 이름을 입력하세요.', active().name + ' 복사');
    if (name === null) return; if (!name.trim()) { showToast('시나리오 이름을 입력하세요.'); return; }
    try { E.cloneScenario(project, active().id, name.trim()); renderAll(); changed(); }
    catch (error) { showToast(error.message); }
  });
  $('rename-scenario').addEventListener('click', () => {
    const name = prompt('시나리오 이름을 입력하세요.', active().name);
    if (name === null) return; if (!name.trim()) { showToast('시나리오 이름을 입력하세요.'); return; }
    active().name = name.trim(); renderScenarioTabs(); changed();
  });
  $('delete-scenario').addEventListener('click', () => {
    if (project.scenarios.length < 2) return;
    if (!confirm('현재 시나리오를 삭제할까요?')) return;
    project.scenarios = project.scenarios.filter(s => s.id !== project.active_scenario_id); project.active_scenario_id = project.scenarios[0].id; renderAll(); changed();
  });
  for (const [id, kind] of [['add-api', 'api'], ['add-excipient', 'excipient']]) $(id).addEventListener('click', () => {
    active().materials.push(E.makeMaterial(kind)); renderMaterials(); changed();
    const last = $('material-body').lastElementChild; last.querySelector('[data-material-field="name"]').focus();
  });
  $('select-all-materials').addEventListener('change', () => { selectedRows = new Set($('select-all-materials').checked ? active().materials.map(m => m.id) : []); renderMaterials(); });
  $('delete-materials').addEventListener('click', () => { active().materials = active().materials.filter(m => !selectedRows.has(m.id)); selectedRows.clear(); renderMaterials(); changed(); });
  $('save-project').addEventListener('click', saveFile);
  $('print-comparison').addEventListener('click', () => {
    selectTab('comparison');
    prepareComparisonPrint();
    try { window.print(); }
    catch (error) { document.body.classList.remove('printing-comparison'); showToast('출력 창을 열 수 없습니다: ' + error.message); }
  });
  window.addEventListener('beforeprint', prepareComparisonPrint);
  window.addEventListener('afterprint', () => document.body.classList.remove('printing-comparison'));
  $('new-project').addEventListener('click', async () => { if (!(await confirmDiscard())) return; project = E.makeProject(); dirty = false; renderAll(); persistDraft(); updateStatus(); });
  $('load-example').addEventListener('click', async () => { if (!(await confirmDiscard())) return; project = E.createExampleProject(); dirty = false; renderAll(); persistDraft(); updateStatus(); });
  $('open-project').addEventListener('click', () => $('open-file').click());
  $('open-file').addEventListener('change', async event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    try {
      if (file.size > 16 * 1024 * 1024) throw new Error('프로젝트 파일은 16MB 이하여야 합니다.');
      const loaded = useManualPricing(E.parseProject(await file.text()));
      if (!(await confirmDiscard())) return;
      project = loaded; dirty = false; renderAll(); persistDraft(); updateStatus(); showToast('프로젝트를 열었습니다: ' + file.name);
    } catch (error) { showToast('파일을 열 수 없습니다: ' + error.message); }
  });
  const pasteFields = ['kind', 'name', 'supplier', 'amount', 'price', 'price_unit'];
  const aliases = {kind: {api: 'api', API: 'api', '부형제': 'excipient', excipient: 'excipient'}, price_unit: {'원/g': 'krw_g', '원/kg': 'krw_kg', '달러/g': 'usd_g', '달러/kg': 'usd_kg', 'USD/g': 'usd_g', 'USD/kg': 'usd_kg', krw_g: 'krw_g', krw_kg: 'krw_kg', usd_g: 'usd_g', usd_kg: 'usd_kg'}};
  $('material-body').addEventListener('paste', event => {
    const text = event.clipboardData.getData('text/plain'); if (!text.includes('\t') && !/[\r\n]/.test(text)) return;
    const target = event.target.closest('[data-material-field]'); if (!target) return;
    event.preventDefault();
    const tr = target.closest('tr'); const firstRow = active().materials.findIndex(m => m.id === tr.dataset.materialId); const firstCol = pasteFields.indexOf(target.dataset.materialField);
    const rows = text.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n').map(line => line.split('\t'));
    if (rows.length > 5000 || firstRow + rows.length > 5000) { showToast('한 시나리오의 원료는 최대 5,000개입니다.'); return; }
    const updates = [];
    for (let r = 0; r < rows.length; r++) for (let c = 0; c < rows[r].length && firstCol + c < pasteFields.length; c++) {
      const field = pasteFields[firstCol + c]; let value = rows[r][c];
      if (aliases[field]) { value = aliases[field][value.trim()]; if (!value) { showToast('붙여넣을 선택값을 확인하세요: ' + rows[r][c]); return; } }
      else if (field === 'amount' || field === 'price') value = numericEntry(value).value;
      updates.push({row: firstRow + r, field, value});
    }
    while (active().materials.length < firstRow + rows.length) active().materials.push(E.makeMaterial('api'));
    for (const update of updates) active().materials[update.row][update.field] = update.value;
    renderMaterials(); changed();
    const first = $('material-body').children[firstRow];
    const replacement = first && first.querySelector('[data-material-field="' + target.dataset.materialField + '"]');
    if (replacement) replacement.focus();
  });
  document.addEventListener('keydown', event => {
    if (event.target.matches('#scenario-tabs [role="tab"]') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const buttons = [...$('scenario-tabs').children];
      const current = buttons.indexOf(event.target);
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      activateScenario(buttons[index].dataset.scenarioId);
      [...$('scenario-tabs').children][index].focus();
    }
    if (event.target.matches('[data-tab]') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const buttons = [...document.querySelectorAll('[data-tab]')];
      const current = buttons.indexOf(event.target);
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      selectTab(buttons[index].dataset.tab); buttons[index].focus();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); saveFile(); }
    if (event.target.matches('[data-material-field]') && event.key === 'Enter') { event.preventDefault(); event.target.blur(); }
  });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  renderAll();
  selectTab('input');
  if (loadNotice) showToast(loadNotice);
  window.PharmaCostApp = {getProject: () => JSON.parse(JSON.stringify(project)), getResult: () => currentResult};
})();
