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
  const companyNames = {innovative: '혁신형 제약기업', near: '준혁신형·수급안정 선도기업', general: '일반기업', '': '미선택'};
  const flagNames = {originator_data: '오리지널·자료제출의약품', improved: '개량신약·개량신약복합제', biologic: '생물의약품', api_self: '원료직접생산의약품', domestic_essential: '국산원료 국가필수의약품', own_injectable_pediatric: '직접 생산 항생주사제·소아의약품'};
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
    if (draft) { project = E.parseProject(draft); loadNotice = '이 브라우저에 저장된 초안을 복원했습니다.'; }
  } catch (error) { storageAvailable = false; loadNotice = '브라우저 초안을 읽지 못했습니다. JSON 파일로 저장해 주세요.'; }

  function active() { return project.scenarios.find(s => s.id === project.active_scenario_id); }
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function format(value, digits = 4, missing = '미완성') {
    if (value === null || value === undefined) return missing;
    let number;
    try { number = value instanceof D ? value : E.parseNumber(value); } catch (error) { return missing; }
    if (number === null) return missing;
    if (number.abs().gte('1e15')) return number.toExponential(digits);
    const parts = number.toFixed(digits).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    if (parts[1]) parts[1] = parts[1].replace(/0+$/, '');
    return parts[0] + (parts[1] ? '.' + parts[1] : '');
  }
  function rate(value) { return value === null ? '계산 불가' : format(value, 2) + '%'; }
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
    const flag = s.pricing_flags.length === 1 ? s.pricing_flags[0] : null;
    document.querySelectorAll('[data-pricing-flag]').forEach(input => { input.checked = input.dataset.pricingFlag === flag; });
    $('manual-price').disabled = s.pricing_mode !== 'manual';
  }
  function renderScenarioSelect() {
    $('scenario-select').replaceChildren();
    for (const s of project.scenarios) {
      const option = element('option', s.name);
      option.value = s.id;
      option.selected = s.id === project.active_scenario_id;
      $('scenario-select').append(option);
    }
    $('delete-scenario').disabled = project.scenarios.length < 2;
    $('scenario-count').textContent = project.scenarios.length + '개 시나리오';
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
    populateFields(); renderScenarioSelect(); renderMaterials(); recalculate(); updateStatus();
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
    if (active().pricing_flags.length > 1) result.issues.push({path: 'pricing_flags', message: '기존 프로젝트에 약제별 가산이 여러 개 선택되어 있습니다. 6개 항목 중 하나를 다시 선택해 주세요.', severity: 'warning'});
    currentResult = result;
    const rows = new Map(result.rows.map(row => [row.id, row]));
    for (const tr of $('material-body').children) {
      const calculated = rows.get(tr.dataset.materialId);
      for (const cell of tr.querySelectorAll('[data-result-field]')) {
        const value = calculated ? calculated[cell.dataset.resultField] : null;
        cell.textContent = format(value);
        cell.title = value === null ? '계산에 필요한 값을 입력하세요.' : value.toString();
      }
    }
    for (const [id, field] of Object.entries({'api-batch': 'api_batch', 'excipient-batch': 'excipient_batch', 'api-unit': 'api_unit', 'excipient-unit': 'excipient_unit', 'packaging-unit': 'packaging_unit', 'labor-unit': 'labor_unit'})) $(id).textContent = format(result[field]);
    markValidation(result);
    $('result-cost').textContent = format(result.total_cost);
    $('result-price').textContent = format(result.pricing.amount, 4, active().pricing_mode === 'official' ? '미확인' : '미입력');
    $('result-rate').textContent = format(result.cost_rate, 2, '계산 불가');
    $('batch-total-note').textContent = '배치 전체 비용 ' + format(result.batch_total) + ' 원';
    $('result-post-rate').textContent = active().post_price === null || active().post_price === '' ? '미입력 (선택 항목)' : rate(result.post_rate);
    renderPricing(result.pricing); renderComposition(result); renderComparison();
  }
  function renderPricing(pricing) {
    const manual = active().pricing_mode === 'manual';
    $('pricing-status').textContent = manual ? '사용자 입력값' : '자동 산정 미확인';
    $('pricing-status').className = 'status-pill ' + (manual ? 'success' : 'warning');
    $('pricing-calculation-badge').textContent = manual ? '직접 입력' : '규정 확인 필요';
    $('pricing-source').textContent = pricing.source;
    $('pricing-rule').textContent = pricing.regulation || (manual ? '사용자 입력값 · 자동 산정률 적용 없음' : '공식 규정 확인 전');
    $('pricing-date').textContent = pricing.basis_date || '—';
    $('pricing-input-note').textContent = manual ? '가산 조건은 기록만 합니다. 원가율에는 우리 제품 예상 약가를 사용합니다.' : '공식 규정·산정률이 확인되지 않아 자동 약가와 해당 원가율을 계산하지 않습니다.';
    $('pricing-steps').replaceChildren();
    const list = element('ol');
    for (const step of pricing.steps || []) list.append(element('li', step));
    $('pricing-steps').append(list);
    for (const link of pricing.links || []) {
      if (!/^https:\/\//.test(link.url)) continue;
      const p = element('p'); const a = element('a', link.title || '공식 자료');
      a.href = link.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); $('pricing-steps').append(p);
    }
  }
  function renderComposition(result) {
    const items = [['API', 'api', result.api_unit], ['부형제', 'excipient', result.excipient_unit], ['포자재비', 'packaging', result.packaging_unit], ['공수비', 'labor', result.labor_unit]];
    $('composition-body').replaceChildren(); $('composition-bar').replaceChildren();
    const complete = result.total_cost !== null;
    for (const [label, cls, cost] of items) {
      const tr = element('tr'); const labelCell = element('td');
      labelCell.append(element('span', '', 'legend-dot ' + cls), document.createTextNode(label));
      const share = complete && result.total_cost.gt(0) && cost !== null ? cost.div(result.total_cost).mul(100) : null;
      tr.append(labelCell, element('td', format(cost), 'numeric'), element('td', share === null ? '—' : format(share, 2) + '%', 'numeric'));
      $('composition-body').append(tr);
      if (share !== null) { const segment = element('span', '', cls); segment.style.width = share.toString() + '%'; segment.title = label + ': ' + format(cost) + '원/T'; $('composition-bar').append(segment); }
    }
    $('composition-bar').setAttribute('aria-label', complete ? 'API·부형제·포자재비·공수비의 제조원가 구성' : '필수 비용이 미입력되어 비용 구성은 미완성입니다.');
  }
  function renderComparison() {
    $('comparison-head').replaceChildren(); $('comparison-body').replaceChildren();
    const header = element('tr'); header.append(element('th', '비교 항목', 'row-label'));
    for (const s of project.scenarios) {
      const th = element('th', s.name, s.id === project.active_scenario_id ? 'current' : ''); th.scope = 'col'; header.append(th);
    }
    $('comparison-head').append(header);
    const results = project.scenarios.map(s => E.calculate(s));
    const rows = [
      ['배치사이즈 (T)', s => format(s.batch_size, 0, '미입력')],
      ['수율 (%)', s => format(s.yield_percent, 2, '미입력')],
      ['환율 (원/USD)', s => format(s.exchange_rate, 2, '미입력')],
      ['원료·처방 (mg/T)', s => s.materials.map(m => (m.name || '원료') + ' ' + format(m.amount, 4, '미입력')).join(' / ') || '원료 없음'],
      ['API 제조원·단가', s => s.materials.filter(m => m.kind === 'api').map(m => (m.supplier || '공급처 미입력') + ' / ' + format(m.price, 4, '미입력') + ' ' + unitNames[m.price_unit]).join(' / ') || 'API 없음'],
      ['오리지널 약가 (원/T)', s => format(s.original_price, 4, '미입력')],
      ['기업 구분', s => companyNames[s.company_type]],
      ['가산 조건', s => s.pricing_flags.map(flag => flagNames[flag]).join(' / ') || '미선택'],
      ['동일제제 품목 수', s => s.identical_count_band === 'lt14' ? '14개 미만' : s.identical_count_band === 'ge14' ? '14개 이상' : '미선택'],
      ['배치당 API 비용 (원)', (s, r) => format(r.api_batch)],
      ['배치당 부형제 비용 (원)', (s, r) => format(r.excipient_batch)],
      ['1T당 API 비용 (원/T)', (s, r) => format(r.api_unit)],
      ['1T당 부형제 비용 (원/T)', (s, r) => format(r.excipient_unit)],
      ['배치 포자재비 (원)', s => format(s.batch_packaging)],
      ['배치 공수비 (원)', s => format(s.batch_labor)],
      ['1T당 포자재비 (원/T)', (s, r) => format(r.packaging_unit)],
      ['1T당 공수비 (원/T)', (s, r) => format(r.labor_unit)],
      ['제조원가 (원/T)', (s, r) => format(r.total_cost)],
      ['우리 제품 약가 (원/T)', (s, r) => format(r.pricing.amount, 4, '계산 불가')],
      ['약가 출처', (s, r) => r.pricing.source],
      ['제조원가율 (%)', (s, r) => rate(r.cost_rate)],
      ['가산 종료 후 원가율 (%)', (s, r) => rate(r.post_rate)]
    ];
    for (const [label, value] of rows) {
      const tr = element('tr'); const th = element('th', label, 'row-label'); th.scope = 'row'; tr.append(th);
      project.scenarios.forEach((s, index) => { const text = value(s, results[index]); const td = element('td', text, s.id === project.active_scenario_id ? 'current' : ''); td.title = text; tr.append(td); });
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
  function saveFile() {
    try {
      if (project.scenarios.some(s => s.pricing_flags.length > 1)) throw new Error('약제별 가산이 여러 개 선택된 시나리오에서 6개 항목 중 하나를 다시 선택하세요.');
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
      if (input.dataset.field === 'pricing_mode') $('manual-price').disabled = input.value !== 'manual';
      changed();
    });
  });
  document.querySelectorAll('[data-pricing-flag]').forEach(input => input.addEventListener('change', () => {
    if (!input.checked) return;
    active().pricing_flags = [input.dataset.pricingFlag]; changed();
  }));
  $('scenario-select').addEventListener('change', () => { project.active_scenario_id = $('scenario-select').value; selectedRows = new Set(); populateFields(); renderMaterials(); changed(); });
  $('clone-scenario').addEventListener('click', () => {
    const name = prompt('복제할 시나리오 이름을 입력하세요.', active().name + ' 복사');
    if (name === null) return; if (!name.trim()) { showToast('시나리오 이름을 입력하세요.'); return; }
    const cloned = E.cloneScenario(project, active().id, name.trim()); project.active_scenario_id = cloned.id; renderAll(); changed();
  });
  $('rename-scenario').addEventListener('click', () => {
    const name = prompt('시나리오 이름을 입력하세요.', active().name);
    if (name === null) return; if (!name.trim()) { showToast('시나리오 이름을 입력하세요.'); return; }
    active().name = name.trim(); renderScenarioSelect(); changed();
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
  $('new-project').addEventListener('click', async () => { if (!(await confirmDiscard())) return; project = E.makeProject(); dirty = false; renderAll(); persistDraft(); updateStatus(); });
  $('load-example').addEventListener('click', async () => { if (!(await confirmDiscard())) return; project = E.createExampleProject(); dirty = false; renderAll(); persistDraft(); updateStatus(); });
  $('open-project').addEventListener('click', () => $('open-file').click());
  $('open-file').addEventListener('change', async event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    try {
      if (file.size > 16 * 1024 * 1024) throw new Error('프로젝트 파일은 16MB 이하여야 합니다.');
      const loaded = E.parseProject(await file.text());
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
