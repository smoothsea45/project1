/* Offline application controller. Domain arithmetic lives in engine.js. */
(function () {
  'use strict';
  const E = window.PharmaCost;
  const F = window.PharmaProfit;
  const ProfitView = window.PharmaProfitView;
  const $ = id => document.getElementById(id);
  if (!E || !F || !ProfitView) { $('app-status').textContent = '계산·화면 파일을 불러오지 못했습니다. ZIP 전체를 압축 해제했는지 확인하세요.'; return; }
  const D = window.Decimal;
  const STORAGE_KEY = 'pharma-cost-web-draft-v1';
  const COMPARISON_YEAR_COUNT = 8;
  const kindNames = {api: 'API', excipient: '부형제'};
  const unitNames = {krw_g: '원/g', krw_kg: '원/kg', usd_g: '달러/g', usd_kg: '달러/kg'};
  let project = E.createExampleProject();
  let dirty = false;
  let selectedRows = new Set();
  let currentResult;
  let currentProfitResult;
  // The comparison preview starts at year 1 independently of the input-page selection.
  const comparisonYears = new Map();
  let draggingScenarioId = null;
  let toastTimer;
  let storageMessage = '';
  let storageAvailable = true;
  let loadNotice = '';
  try {
    const draft = localStorage.getItem(STORAGE_KEY);
    if (draft) {
      project = E.parseProject(draft);
      loadNotice = '이 브라우저에 저장된 초안을 복원했습니다.';
    }
  } catch (error) {
    storageAvailable = false;
    loadNotice = '기존 브라우저 초안을 그대로 보관했습니다. 복원할 수 없습니다: ' + error.message;
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
  function comparisonApiPrices(scenario, material) {
    let purchase = null, exchange = null;
    try { purchase = E.parseNumber(material.price); } catch (_) { /* Keep invalid input visible in its original row. */ }
    try { exchange = E.parseNumber(scenario.exchange_rate); } catch (_) { /* The known quote currency remains usable. */ }
    if (exchange !== null && !exchange.gt(0)) exchange = null;
    let krw = null, usd = null;
    if (purchase !== null && Object.prototype.hasOwnProperty.call(unitNames, material.price_unit)) {
      const perKg = material.price_unit.endsWith('_g') ? purchase.times(1000) : purchase;
      if (material.price_unit.startsWith('krw_')) {
        krw = perKg; if (exchange !== null) usd = perKg.div(exchange);
      } else {
        usd = perKg; if (exchange !== null) krw = perKg.times(exchange);
      }
    }
    const prices = element('span', undefined, 'comparison-api-prices');
    if (krw !== null) prices.dataset.krwKg = krw.toString();
    if (usd !== null) prices.dataset.usdKg = usd.toString();
    const missing = purchase === null ? '단가 미입력' : '환율 필요';
    prices.append(
      element('span', krw === null ? missing + ' · 원/kg' : format(krw, 0) + ' 원/kg', 'comparison-api-krw'),
      element('span', usd === null ? missing + ' · 달러/kg' : format(usd, 0) + ' 달러/kg', 'comparison-api-usd')
    );
    return prices;
  }
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
    document.querySelectorAll('[data-pricing-field]').forEach(input => {
      const value = s.pricing_conditions[input.dataset.pricingField];
      if (input.type === 'checkbox') input.checked = value;
      else if (input.type === 'radio') input.checked = value === input.value;
      else if (input.inputMode === 'decimal') setNumericDisplay(input, value);
      else input.value = value === null || value === undefined ? '' : value;
    });
    renderProfitInputs();
  }
  function syncProfitControls() {
    const settings = project.profit_analysis;
    $('profit-enabled').checked = settings.enabled;
    $('profit-years').value = String(settings.years);
    $('sf-custom').checked = active().sales_forecast.use_custom;
    $('sf-input-card').hidden = !settings.enabled;
    const existing = $('tab-button-profit');
    if (settings.enabled && !existing) {
      const button = $('profit-tab-template').content.firstElementChild.cloneNode(true);
      button.addEventListener('click', () => selectTab('profit'));
      $('tab-button-comparison').after(button);
    } else if (!settings.enabled && existing) {
      if (existing.getAttribute('aria-selected') === 'true') selectTab('input');
      existing.remove();
    }
    if (!settings.enabled) $('tab-profit').hidden = true;
  }
  function renderProfitInputs() {
    syncProfitControls();
    const settings = project.profit_analysis;
    $('sf-sales-table').style.setProperty('--sf-years', settings.years);
    const scenario = active();
    const head = element('tr');
    const unit = element('th', 'SF · 판매수량(T)'); unit.scope = 'col'; head.append(unit);
    for (let year = 1; year <= settings.years; year++) {
      const th = element('th', year + '년차'); th.scope = 'col'; head.append(th);
    }
    $('sf-sales-head').replaceChildren(head);
    $('sf-sales-body').replaceChildren();
    for (const scope of scenario.sales_forecast.use_custom ? ['common', 'custom'] : ['common']) {
      const row = element('tr'); row.dataset.sfScope = scope;
      const label = element('th', scope === 'common' ? '공통 SF' : '현재 시나리오 SF');
      label.scope = 'row'; row.append(label);
      const values = scope === 'common' ? settings.common_quantities : scenario.sales_forecast.quantities;
      for (let year = 1; year <= settings.years; year++) {
        const td = element('td');
        const input = element('input', undefined, 'sf-sales-input numeric');
        input.type = 'text'; input.inputMode = 'numeric';
        input.dataset.sfScope = scope; input.dataset.sfYear = String(year);
        input.setAttribute('aria-label', year + '년차 ' + (scope === 'common' ? '공통 SF' : '현재 시나리오 SF') + ' 판매수량 T');
        input.placeholder = scope === 'common' ? '판매수량 입력' : '공통값 사용';
        setNumericDisplay(input, values[year - 1]);
        bindNumericInput(input, value => { values[year - 1] = value; changed(); });
        td.append(input); row.append(td);
      }
      $('sf-sales-body').append(row);
    }
  }
  function renderProfitAnalysis() {
    syncProfitControls();
    $('sf-input-errors').replaceChildren();
    $('sf-input-errors').hidden = true;
    currentProfitResult = F.calculate(project);
    if (!currentProfitResult.enabled) return;
    const errors = [];
    for (const input of $('sf-sales-body').querySelectorAll('.sf-sales-input')) {
      input.removeAttribute('aria-invalid'); input.removeAttribute('title');
      const year = Number(input.dataset.sfYear);
      const values = input.dataset.sfScope === 'common' ? project.profit_analysis.common_quantities : active().sales_forecast.quantities;
      try { E.parseQuantity(values[year - 1]); }
      catch (error) {
        input.setAttribute('aria-invalid', 'true'); input.title = error.message;
        errors.push(year + '년차 ' + (input.dataset.sfScope === 'common' ? '공통 SF' : '현재 시나리오 SF') + ': ' + error.message);
      }
    }
    if (errors.length) {
      const list = element('ul');
      for (const message of errors) list.append(element('li', message));
      $('sf-input-errors').append(list); $('sf-input-errors').hidden = false;
    }
    ProfitView.render(currentProfitResult);
  }
  function renderScenarioTabs() {
    $('scenario-tabs').replaceChildren();
    for (const [index, s] of project.scenarios.entries()) {
      const selected = s.id === project.active_scenario_id;
      const number = String(index + 1).padStart(2, '0');
      const button = element('button', undefined, 'scenario-tab' + (selected ? ' active' : ''));
      const handle = element('span', '⠿', 'scenario-drag-handle');
      handle.setAttribute('aria-hidden', 'true');
      const badge = element('span', number, 'tab-number scenario-number');
      badge.setAttribute('aria-hidden', 'true');
      button.append(handle, badge, element('span', s.name, 'scenario-name'));
      button.type = 'button'; button.dataset.scenarioId = s.id;
      button.draggable = project.scenarios.length > 1;
      button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(selected));
      button.setAttribute('aria-label', (index + 1) + '번 시나리오: ' + s.name);
      button.setAttribute('aria-describedby', 'scenario-reorder-hint');
      button.setAttribute('aria-keyshortcuts', 'Alt+Shift+ArrowLeft Alt+Shift+ArrowRight');
      button.tabIndex = selected ? 0 : -1;
      button.title = number + '. ' + s.name + (project.scenarios.length > 1 ? '\n드래그해 순서 변경 · 키보드: Alt+Shift+←/→' : '');
      button.addEventListener('click', () => activateScenario(s.id));
      button.addEventListener('dragstart', event => {
        if (project.scenarios.length < 2 || !event.dataTransfer) { event.preventDefault(); return; }
        clearScenarioDrag();
        draggingScenarioId = s.id;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', s.id);
        event.dataTransfer.setData('application/x-pharma-cost-scenario', s.id);
        button.classList.add('dragging');
        $('scenario-tabs').classList.add('dragging-scenarios');
      });
      button.addEventListener('dragend', clearScenarioDrag);
      $('scenario-tabs').append(button);
    }
    $('delete-scenario').disabled = project.scenarios.length < 2;
    $('clone-scenario').disabled = project.scenarios.length >= E.MAX_SCENARIOS;
    $('clone-scenario').title = project.scenarios.length >= E.MAX_SCENARIOS ? '한 프로젝트에는 최대 ' + E.MAX_SCENARIOS + '개 시나리오를 만들 수 있습니다.' : '현재 입력값을 새 시나리오로 복제합니다.';
    $('scenario-count').textContent = project.scenarios.length + '개 시나리오';
  }
  function clearScenarioDropMarkers() {
    $('scenario-tabs').querySelectorAll('.drop-before,.drop-after').forEach(button => button.classList.remove('drop-before', 'drop-after'));
  }
  function clearScenarioDrag() {
    draggingScenarioId = null;
    clearScenarioDropMarkers();
    $('scenario-tabs').classList.remove('dragging-scenarios');
    $('scenario-tabs').querySelectorAll('.dragging').forEach(button => button.classList.remove('dragging'));
  }
  function scenarioDropPosition(event) {
    const from = project.scenarios.findIndex(s => s.id === draggingScenarioId);
    if (from < 0) return null;
    const tabs = $('scenario-tabs');
    let button = event.target.closest('.scenario-tab');
    if (!button || button.parentElement !== tabs) {
      // Resolve gaps and the spare end of the tab list, including its two-row layout.
      let nearest = Infinity;
      for (const candidate of tabs.children) {
        const box = candidate.getBoundingClientRect();
        const dx = Math.max(box.left - event.clientX, 0, event.clientX - box.right);
        const dy = Math.max(box.top - event.clientY, 0, event.clientY - box.bottom);
        const distance = dx * dx + dy * dy;
        if (distance < nearest) { nearest = distance; button = candidate; }
      }
    }
    if (!button) return null;
    const box = button.getBoundingClientRect();
    const after = event.clientX >= box.left + box.width / 2;
    let index = project.scenarios.findIndex(s => s.id === button.dataset.scenarioId) + Number(after);
    if (index > from) index -= 1;
    return {button, after, index};
  }
  function moveScenario(id, index) {
    const from = project.scenarios.findIndex(s => s.id === id);
    const to = Math.max(0, Math.min(project.scenarios.length - 1, index));
    if (from < 0 || from === to) return;
    const [moved] = project.scenarios.splice(from, 1);
    project.scenarios.splice(to, 0, moved);
    renderScenarioTabs(); changed();
    [...$('scenario-tabs').children].find(button => button.dataset.scenarioId === project.active_scenario_id).focus({preventScroll: true});
    showToast(moved.name + ' 시나리오를 ' + (to + 1) + '번째로 옮겼습니다.');
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
    document.querySelectorAll('[data-field],[data-material-field],[data-pricing-field]').forEach(input => { input.removeAttribute('aria-invalid'); input.removeAttribute('title'); });
    $('material-body').querySelectorAll('tr').forEach(tr => tr.classList.remove('invalid-row'));
    for (const issue of result.issues) {
      let input;
      if (issue.path.startsWith('materials.')) {
        const [, id, field] = issue.path.split('.');
        const tr = [...$('material-body').children].find(row => row.dataset.materialId === id);
        input = tr && tr.querySelector('[data-material-field="' + field + '"]');
        if (tr && issue.severity === 'error') tr.classList.add('invalid-row');
      } else if (issue.path.startsWith('pricing_conditions.')) input = document.querySelector('[data-pricing-field="' + issue.path.split('.')[1] + '"]');
      else input = document.querySelector('[data-field="' + issue.path + '"]');
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
    $('result-price').textContent = format(result.pricing.amount, 0, '미입력');
    $('result-rate').textContent = percentage(result.cost_rate, '계산 불가', false);
    $('batch-total-note').textContent = '배치 전체 비용 ' + format(result.batch_total) + ' 원';
    renderPricing(result.pricing); renderComposition(result); renderComparison(); renderProfitAnalysis();
  }
  function renderPricing(pricing) {
    const s = active();
    const p = s.pricing_conditions;
    const automatic = s.pricing_mode === 'official';
    const general = p.general_category !== 'none';
    const simple = general || p.supply_category !== 'none';
    $('manual-price-wrap').hidden = automatic;
    $('manual-price').disabled = automatic;
    $('calculated-price-wrap').hidden = !automatic;
    $('calculated-price').textContent = format(pricing.amount, 0, '계산 불가');
    $('selected-pricing-year').textContent = '선택 연차: ' + p.selected_year + '년차';
    $('pricing-company-details').hidden = simple || !s.company_type || s.company_type === 'general';
    $('pricing-base-criteria').hidden = p.general_category === 'biologic' || p.supply_category !== 'none';
    $('pricing-supply-details').hidden = p.supply_category === 'none';
    $('pricing-general-details').hidden = !general;
    // Disabled inputs cannot receive clicks, focus, or keyboard edits in manual mode.
    document.querySelectorAll('[data-pricing-automatic]').forEach(input => {
      const hidden = input.closest('[hidden]');
      const field = input.dataset.pricingField;
      const parentUnmet = field === 'domestic_extension' && !p.company_eligible;
      input.disabled = !automatic || parentUnmet || Boolean(hidden && document.querySelector('.pricing-card').contains(hidden));
    });
    const scheduleNotes = {
      data_submission: '1년차 70% → 2~4년차 60%', improved: '1~4년차 70%',
      improved_combo: '1~4년차 68%', other: '1~4년차 60%', biologic: '1~5년차 80%'
    };
    $('pricing-general-input-note').textContent = p.supply_category !== 'none'
      ? '수급안정 선택 중에는 일반가산 일정을 적용하지 않습니다.' : scheduleNotes[p.general_category] || '';
    $('pricing-supply-input-note').textContent = '1~5년차 68% + 6~10년차 68% · 수급안정 일정 우선 적용 · 일반/기업 가산 합산 없음';
    $('pricing-simple-note').hidden = !simple;
    $('pricing-migration-notice').hidden = simple || !p.migration_review;
    $('pricing-migration-message').textContent = p.migration_review;
    $('pricing-review-legacy').disabled = !automatic;
    $('pricing-status').textContent = !automatic ? '사용자 입력값' : ['ready', 'zero'].includes(pricing.status) ? (simple ? '간편 가정' : '예상 약가') : pricing.status === 'needs_conditions' ? '조건 확인' : '입력 확인';
    $('pricing-status').className = 'status-pill' + ((!automatic || pricing.status === 'ready') ? ' success' : '');
    $('pricing-source').textContent = pricing.source + (automatic ? ' · ' + p.selected_year + '년차' : '');
    $('pricing-input-note').textContent = automatic
      ? '선택한 연차의 약가를 원가계산에 사용합니다. 간편 가산 비율은 오리지널 기준약가에 직접 적용합니다.'
      : '직접 입력한 우리 제품 약가를 원가계산에 사용합니다.';
    renderPricingForecast(pricing, automatic);
  }
  function renderPricingForecast(pricing, automatic) {
    $('pricing-forecast').hidden = !automatic;
    const bars = $('pricing-year-bars');
    const axis = $('pricing-y-axis');
    bars.replaceChildren(); axis.replaceChildren();
    $('pricing-forecast-summary').textContent = '';
    $('pricing-forecast-context').textContent = '선택한 조건과 제도 유지 가정에 따른 예상치';
    $('pricing-calculation-details').replaceChildren();
    const years = pricing.years || [];
    const ready = automatic && ['ready', 'zero'].includes(pricing.status) && years.length === 10;
    $('pricing-forecast-chart').hidden = !ready;
    $('pricing-forecast-message').hidden = ready;
    if (!ready) {
      const messages = currentResult.issues.filter(issue => /^(pricing_|original_price|company_type|identical_count_band)/.test(issue.path)).map(issue => issue.message);
      $('pricing-forecast-message').textContent = [...new Set(messages)].join(' ') || pricing.summary || '';
      if (!$('pricing-forecast-message').textContent.trim()) $('pricing-forecast-message').textContent = '오리지널 기준약가, 기준요건, 품목 수와 예상 등재일을 확인해 주세요.';
      return;
    }
    const groups = [];
    for (const year of years) {
      const last = groups[groups.length - 1];
      if (last && last.amount.eq(year.amount) && last.assumption === year.assumption) last.end = year.year;
      else groups.push({start: year.year, end: year.year, amount: year.amount, assumption: year.assumption});
    }
    $('pricing-forecast-summary').textContent = groups.map(group => group.start + (group.end === group.start ? '' : '~' + group.end) + '년차 ' + format(group.amount, 0) + '원' + (group.assumption ? ' (연장요건 충족 가정)' : '')).join(' → ');
    const s = active();
    const company = {general: '일반기업', innovative: '혁신형 제약기업', near: '준혁신형 제약기업', supply_leader: '수급안정 선도기업'}[s.company_type];
    $('pricing-forecast-context').textContent = pricing.model === 'simplified-v1'
      ? '간편 가정 · 오리지널 기준약가 대비 비율 · 가산 중복 합산 없음'
      : [company, '최초 제네릭 등재군', s.identical_count_band === 'ge14' ? '14개 이상 유발' : s.identical_count_band === 'lt14' ? '14개 미만' : ''].filter(Boolean).join(' · ');
    let maximum = new D(0);
    years.forEach(year => { if (year.amount.gt(maximum)) maximum = year.amount; });
    const scale = maximum.gt(0) ? maximum.mul('1.18') : new D(1);
    for (const step of [4, 3, 2, 1, 0]) axis.append(element('span', format(scale.mul(step).div(4), 0)));
    for (const year of years) {
      const selected = year.year === active().pricing_conditions.selected_year;
      const button = element('button', undefined, 'pricing-year-button' + (selected ? ' selected' : '') + (year.kind === 'bonus' ? ' bonus' : '') + (year.assumption ? ' extension' : ''));
      button.type = 'button';
      button.dataset.pricingYear = year.year;
      button.dataset.amount = year.amount.toString();
      button.setAttribute('aria-pressed', String(selected));
      const amount = format(year.amount, 0);
      const tooltip = year.year + '년차 · ' + amount + ' 원/T · ' + year.start_date + '~' + year.end_date + '\n' + (year.label || '') + (year.rate_label ? ' · ' + year.rate_label : '') + (year.assumption ? ' · 연장요건 충족 가정' : '');
      button.title = tooltip;
      button.setAttribute('aria-label', tooltip);
      const column = element('span', undefined, 'pricing-year-column');
      const fill = element('span', undefined, 'pricing-year-fill');
      const height = year.amount.div(scale).mul(100).toNumber() + '%';
      column.style.setProperty('--bar-height', height);
      fill.style.height = height;
      fill.setAttribute('aria-hidden', 'true');
      column.append(element('span', amount, 'pricing-year-amount'), fill);
      const label = element('span', undefined, 'pricing-year-label');
      label.append(element('strong', String(year.calendar_year)), element('small', year.year + '년차'));
      button.append(column, label);
      button.addEventListener('click', () => {
        active().pricing_conditions.selected_year = year.year;
        changed();
        const replacement = bars.querySelector('[data-pricing-year="' + year.year + '"]');
        if (replacement) replacement.focus({preventScroll: true});
      });
      bars.append(button);
    }
    let details = $('pricing-calculation-details');
    if (pricing.model === 'simplified-v1') {
      const disclosure = element('details');
      disclosure.append(element('summary', '계산 가정 보기'));
      const body = element('div'); disclosure.append(body); details.append(disclosure); details = body;
    }
    const effective = pricing.effective_requirements;
    if (effective && pricing.model !== 'simplified-v1') {
      details.append(element('p', '실제 적용 기준요건: 생동·임상 ' + (effective.own_data ? '충족' : '미충족') + ' · DMF ' + (effective.dmf ? '충족' : '미충족') + ' (' + effective.count + '개)'));
      for (const reason of effective.deemed_reasons || []) details.append(element('p', reason));
    }
    for (const step of pricing.steps || []) details.append(element('p', step));
    for (const note of pricing.notes || []) details.append(element('p', note));
    if (pricing.regulation) {
      const source = element('p');
      source.append(document.createTextNode('적용 기준: ' + pricing.regulation + ' · ' + pricing.basis_date + ' (사용자 지정 기준일) · '));
      const link = element('a', '공식 별표 1');
      link.href = 'https://www.law.go.kr/LSW/flDownload.do?bylClsCd=200201&flSeq=168756835';
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      source.append(link); details.append(source);
    }
  }
  function renderComposition(result, root = document.querySelector('.composition-card')) {
    const money = value => format(value, root.classList.contains('comparison-composition') ? 1 : 2);
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
      const amount = element('span', money(cost) + (cost === null ? '' : ' 원/T'), 'composition-amount');
      amount.title = cost === null ? '이 항목의 입력이 미완성입니다.' : money(cost) + ' 원/T';
      row.append(labelNode, amount);
      part('composition-body').append(row);
      if (share !== null) {
        const segment = element('span', undefined, 'composition-segment ' + cls);
        segment.dataset.item = cls;
        segment.dataset.share = share.toString();
        segment.style.height = share.toNumber() + '%';
        segment.title = label + ' ' + shareText(share) + ' · ' + money(cost) + ' 원/T';
        part('composition-stack').append(segment);
      }
    }
    part('composition-stack').dataset.state = !complete ? 'incomplete' : positiveCost ? 'ready' : 'zero';
    part('composition-stack').setAttribute('aria-label', !complete ? '필수 비용 입력이 미완성입니다. 제조원가 구성비를 계산할 수 없습니다.' : positiveCost ? '총 제조원가 기준. 위에서부터 API, 부형제, 포장재비, 공수비 순서입니다.' : '제조원가가 0원입니다. 총 제조원가 기준 구성비는 계산할 수 없습니다.');
    part('raw-material-total').textContent = money(result.raw_unit) + (result.raw_unit === null ? '' : ' 원/T');
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
      title.textContent = label + ' ' + shareText(share) + ' · ' + money(cost) + ' 원/T';
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
    part('donut-total').textContent = complete ? money(total) + ' 원/T' : '제조원가 미완성';
    part('composition-remainder').textContent = complete && validPrice ? money(price.minus(total)) + ' 원/T' : '계산 불가';
    part('donut-note').textContent = !complete ? '보험약가 기준 · 비용 입력 미완성' : !validPrice ? '보험약가 미입력·0·미확인' : overPrice ? '약가 초과 · 도넛은 제조원가 기준' : '보험약가 기준 · ' + format(price, 0) + ' 원/T';
    if (!complete) notices.push('필수 비용을 입력하면 두 그래프의 비율을 표시합니다. 계산 가능한 항목의 금액은 유지합니다.');
    else {
      if (!validPrice) notices.push('보험약가가 없거나 0 또는 미확인 상태여서 도넛의 약가 대비 비율은 계산 불가입니다.');
      if (!positiveCost) notices.push('제조원가가 0원이므로 오른쪽 구성비와 원재료비 비율은 계산 불가(—)입니다.');
      if (overPrice) notices.push('제조원가가 보험약가를 초과했습니다. 중앙에는 실제 약가 대비 원가율을 표시하며, 도넛 구간은 제조원가 전체를 기준으로 표시합니다. 회색 차액 구간은 없습니다.');
    }
    part('composition-status').textContent = notices.join(' ');
    part('composition-status').hidden = notices.length === 0;
    donut.setAttribute('aria-label', notices.length ? centerRate + ', 총 제조원가 ' + money(total) + ' 원/T. ' + notices.join(' ') : '보험약가 ' + format(price, 0) + ' 원/T 기준 API·부형제·포장재비·공수비와 차액. 제조원가율 ' + centerRate + ', 제조원가 ' + money(total) + ' 원/T.');
  }
  function renderComparison() {
    $('comparison-head').replaceChildren(); $('comparison-body').replaceChildren();
    $('comparison-body').closest('table').style.width = (166 + project.scenarios.length * 340) + 'px';
    const header = element('tr');
    const itemHeader = element('th', '시나리오명', 'row-label');
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
    const results = project.scenarios.map(s => E.calculate(Object.assign({}, s, {
      pricing_conditions: Object.assign({}, s.pricing_conditions, {selected_year: comparisonYears.get(s.id) || 1})
    })));
    let comparisonMaximum = new D(0);
    for (const result of results) {
      const amounts = (result.pricing.years || []).slice(0, COMPARISON_YEAR_COUNT).map(year => year.amount);
      amounts.push(result.pricing.amount, result.total_cost);
      for (const amount of amounts) if (amount !== null && amount !== undefined && amount.gt(comparisonMaximum)) comparisonMaximum = amount;
    }
    const comparisonScale = comparisonMaximum.gt(0) ? comparisonMaximum.mul('1.25') : new D(1);
    const apiDetails = (s, value) => {
      const list = element('div', undefined, 'comparison-api-list');
      for (const material of s.materials.filter(m => m.kind === 'api')) {
        const item = element('div');
        const detail = value(material);
        const valueNode = element('span');
        if (typeof detail === 'string') valueNode.textContent = detail;
        else valueNode.append(detail);
        item.append(element('span', material.name || 'API', 'comparison-api-name'), valueNode);
        list.append(item);
      }
      if (!list.childElementCount) list.textContent = 'API 없음';
      return list;
    };
    const rows = [
      ['batch_size', '배치사이즈 (T)', s => format(s.batch_size, 0, '미입력')],
      ['yield_percent', '수율 (%)', s => format(s.yield_percent, 1, '미입력') + (s.yield_percent === null || s.yield_percent === '' ? '' : '%')],
      ['packaging_form', '포장형태', s => s.packaging_form || '미입력'],
      ['api_supplier', 'API 제조원', s => apiDetails(s, m => m.supplier || '제조원 미입력')],
      ['api_price', 'API 단가', s => apiDetails(s, m => comparisonApiPrices(s, m))],
      ['price', '우리 제품 약가 (원/T)', (s, r) => format(r.pricing.amount, 0, '계산 불가')],
      ['total_cost', '제조원가 (원/T)', (s, r) => format(r.total_cost, 1)],
      ['cost_rate', '제조원가율 (%)', (s, r) => rate(r.cost_rate)],
      ['composition', '비용 구성 그래프', (s, r) => {
        const chart = element('div', undefined, 'comparison-composition');
        chart.dataset.scenarioId = s.id;
        chart.append(document.querySelector('.composition-card .composition-charts').cloneNode(true), document.querySelector('.composition-card .composition-status').cloneNode(true));
        chart.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
        chart.querySelector('.donut-column').prepend(element('span', (comparisonYears.get(s.id) || 1) + '년차', 'comparison-donut-year'));
        renderComposition(r, chart);
        return chart;
      }],
      ['price_forecast', '연차별 약가 · 제조원가', (s, r) => renderComparisonPrices(s, r, comparisonScale)],
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
            const digits = costIndex === 0 ? 0 : 1;
            const td = element('td', format(amount, digits), 'comparison-cost-cell numeric' + (s.id === project.active_scenario_id ? ' current' : ''));
            td.dataset.scenarioId = s.id; td.dataset.costBasis = costIndex === 0 ? 'batch' : 'unit';
            td.title = (costIndex === 0 ? '배치당: ' : '1T당: ') + format(amount, digits) + (costIndex === 0 ? ' 원' : ' 원/T');
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
  function renderComparisonPrices(scenario, result, scale) {
    const chart = element('div', undefined, 'comparison-price-chart');
    chart.dataset.scenarioId = scenario.id;
    chart.dataset.scaleMaximum = scale.toString();
    const selected = comparisonYears.get(scenario.id) || 1;
    const heading = element('div', undefined, 'comparison-price-heading');
    heading.append(element('strong', selected + '년차 기준' + (result.pricing.model === 'simplified-v1' ? ' · 간편 가정' : '')), element('span', '공통 축 0~' + format(scale, 1) + ' 원/T', 'comparison-price-scale'));
    chart.append(heading);
    let years = (result.pricing.years || []).slice(0, COMPARISON_YEAR_COUNT);
    if (scenario.pricing_mode === 'manual' && result.pricing.amount !== null) {
      years = Array.from({length: COMPARISON_YEAR_COUNT}, (_, i) => ({year: i + 1, amount: result.pricing.amount, label: '직접 입력 약가 유지 가정'}));
    }
    if (years.length !== COMPARISON_YEAR_COUNT) {
      chart.append(element('p', '약가 조건을 입력하면 8년 약가를 표시합니다.', 'comparison-price-message'));
      const legend = element('p', undefined, 'comparison-price-legend');
      legend.append(element('span', '제조원가 ' + format(result.total_cost, 1) + (result.total_cost === null ? '' : ' 원/T'), 'comparison-cost-key'));
      chart.append(legend);
      return chart;
    }
    const plot = element('div', undefined, 'comparison-price-plot');
    const bars = element('div', undefined, 'comparison-price-bars');
    for (const year of years) {
      const button = element('button', undefined, 'comparison-price-year' + (year.kind === 'bonus' ? ' bonus' : '') + (year.assumption ? ' extension' : ''));
      button.type = 'button';
      button.dataset.comparisonYear = year.year;
      button.dataset.scenarioId = scenario.id;
      button.dataset.amount = year.amount.toString();
      button.setAttribute('aria-pressed', String(selected === year.year));
      const ratio = result.total_cost !== null && year.amount.gt(0) ? result.total_cost.div(year.amount).mul(100) : null;
      button.title = year.year + '년차 · 약가 ' + format(year.amount, 0) + ' 원/T · 제조원가 ' + format(result.total_cost, 1) + (result.total_cost === null ? '' : ' 원/T')
        + ' · 제조원가율 ' + percentage(ratio)
        + (year.start_date ? '\n' + year.start_date + '~' + year.end_date : '') + (year.label ? '\n' + year.label : '');
      button.setAttribute('aria-label', scenario.name + ' ' + button.title);
      const column = element('span', undefined, 'comparison-price-column');
      const total = result.total_cost !== null && result.total_cost.gt(year.amount) ? result.total_cost : year.amount;
      const withinPrice = result.total_cost === null ? new D(0) : result.total_cost.gt(year.amount) ? year.amount : result.total_cost;
      const costFraction = withinPrice.div(scale);
      const stackHeight = total.div(scale).mul(100).toNumber() + '%';
      column.style.setProperty('--stack-height', stackHeight);
      column.style.setProperty('--cost-height', costFraction.mul(100).toNumber() + '%');
      const stack = element('span', undefined, 'comparison-price-stack');
      stack.dataset.total = total.toString(); stack.style.height = stackHeight;
      function appendSegment(segment, amount) {
        segment.dataset.segmentAmount = amount.toString();
        segment.style.height = total.gt(0) ? amount.div(total).mul(100).toNumber() + '%' : '0%';
        segment.setAttribute('aria-hidden', 'true'); stack.append(segment);
      }
      if (result.total_cost === null) {
        appendSegment(element('span', undefined, 'comparison-unresolved-fill'), year.amount);
      } else {
        const remainder = year.amount.gt(result.total_cost) ? year.amount.minus(result.total_cost) : new D(0);
        const excess = result.total_cost.gt(year.amount) ? result.total_cost.minus(year.amount) : new D(0);
        if (excess.gt(0)) {
          const excessFill = element('span', undefined, 'comparison-excess-fill');
          excessFill.dataset.excess = excess.toString(); appendSegment(excessFill, excess);
        }
        const fill = element('span', undefined, 'comparison-price-fill');
        fill.dataset.remainder = remainder.toString(); appendSegment(fill, remainder);
        const costFill = element('span', undefined, 'comparison-cost-fill');
        costFill.dataset.cost = result.total_cost.toString();
        appendSegment(costFill, withinPrice);
      }
      const ratioText = ratio === null ? '계산불가' : ratio.gte(1000) ? ratio.toExponential(1).replace('e+', 'e') + '%' : percentage(ratio);
      const ratioLabel = element('span', ratioText, 'comparison-year-rate' + (costFraction.lt('0.14') ? ' compact' : '') + (result.total_cost !== null && result.total_cost.isZero() ? ' zero' : '') + (ratio === null ? ' unavailable' : ''));
      ratioLabel.title = '제조원가율 ' + percentage(ratio);
      const priceLabel = element('span', format(year.amount, 0) + '원', 'comparison-year-price');
      priceLabel.title = year.year + '년차 약가 ' + format(year.amount, 0) + ' 원/T';
      column.append(stack, priceLabel, ratioLabel);
      button.append(column, element('span', String(year.year), 'comparison-price-label'));
      button.addEventListener('click', () => {
        comparisonYears.set(scenario.id, year.year);
        renderComparison();
        const replacement = [...$('comparison-body').querySelectorAll('[data-comparison-year]')].find(node => node.dataset.scenarioId === scenario.id && Number(node.dataset.comparisonYear) === year.year);
        if (replacement) replacement.focus({preventScroll: true});
      });
      bars.append(button);
    }
    plot.append(bars);
    chart.append(plot);
    const legend = element('p', undefined, 'comparison-price-legend');
    if (result.total_cost === null) legend.append(element('span', '약가 · 원가 미완성', 'comparison-unknown-key'));
    else {
      const phases = new Map();
      for (const year of years) {
        const phase = year.assumption ? 'extension' : year.kind === 'bonus' ? 'bonus' : 'base';
        if (!phases.has(phase)) phases.set(phase, []);
        phases.get(phase).push(year.year);
      }
      for (const [phase, phaseYears] of phases) {
        const first = phaseYears[0], last = phaseYears[phaseYears.length - 1];
        const period = (phaseYears.every((year, index) => year === first + index) ? first + (last === first ? '' : '~' + last) : phaseYears.join('·')) + '년';
        const key = element('span', '약가 차액' + (phases.size > 1 ? ' (' + period + ')' : ''), 'comparison-price-key' + (phase === 'base' ? '' : ' ' + phase));
        key.dataset.pricePhase = phase;
        legend.append(key);
      }
    }
    legend.append(element('span', '제조원가 ' + format(result.total_cost, 1) + (result.total_cost === null ? '' : ' 원/T'), 'comparison-cost-key'));
    if (result.total_cost !== null && years.some(year => result.total_cost.gt(year.amount))) legend.append(element('span', '원가 초과', 'comparison-excess-key'));
    chart.append(legend);
    return chart;
  }
  function selectTab(name) {
    if (name === 'profit' && !project.profit_analysis.enabled) name = 'input';
    document.querySelectorAll('[data-tab]').forEach(button => {
      const selected = button.dataset.tab === name; button.classList.toggle('active', selected); button.setAttribute('aria-selected', String(selected));
    });
    for (const panel of ['input', 'results', 'comparison', 'profit']) $('tab-' + panel).hidden = name !== panel;
    document.querySelectorAll('[data-tab]').forEach(button => { button.tabIndex = button.dataset.tab === name ? 0 : -1; });
    if (name === 'profit' && currentProfitResult && currentProfitResult.enabled) ProfitView.render(currentProfitResult);
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
  $('profit-enabled').addEventListener('change', event => {
    project.profit_analysis.enabled = event.target.checked;
    renderProfitInputs(); changed();
    if (project.profit_analysis.enabled) {
      selectTab('input');
      $('sf-sales-body').querySelector('.sf-sales-input').focus();
    }
  });
  $('profit-years').addEventListener('change', event => {
    project.profit_analysis.years = Number(event.target.value);
    renderProfitInputs(); changed();
  });
  $('sf-custom').addEventListener('change', event => {
    active().sales_forecast.use_custom = event.target.checked;
    renderProfitInputs(); changed();
  });
  $('sf-sales-body').addEventListener('paste', event => {
    const input = event.target.closest('.sf-sales-input');
    if (!input) return;
    const text = event.clipboardData.getData('text/plain');
    if (!/[\t\r\n]/.test(text)) return;
    const rows = text.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n').map(row => row.split('\t'));
    if (rows.length > 1 && rows.some(row => row.length > 1)) { event.preventDefault(); showToast('SF는 한 행 또는 한 열의 판매수량(T)을 붙여넣어 주세요.'); return; }
    const cells = rows.length === 1 ? rows[0] : rows.map(row => row[0]);
    const first = Number(input.dataset.sfYear) - 1;
    if (first + cells.length > project.profit_analysis.years) { event.preventDefault(); showToast('선택한 분석기간 안에 들어가는 SF만 붙여넣어 주세요.'); return; }
    event.preventDefault();
    const values = input.dataset.sfScope === 'common' ? project.profit_analysis.common_quantities : active().sales_forecast.quantities;
    cells.forEach((value, index) => { values[first + index] = numericEntry(value).value; });
    renderProfitInputs(); changed();
    const replacement = $('sf-sales-body').querySelector('[data-sf-scope="' + input.dataset.sfScope + '"][data-sf-year="' + (first + 1) + '"]');
    if (replacement) replacement.focus();
  });
  $('scenario-tabs').addEventListener('dragover', event => {
    const position = scenarioDropPosition(event);
    if (!position) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    clearScenarioDropMarkers();
    if (project.scenarios[position.index].id !== draggingScenarioId) position.button.classList.add(position.after ? 'drop-after' : 'drop-before');
  });
  $('scenario-tabs').addEventListener('dragleave', event => {
    if (!event.relatedTarget || !$('scenario-tabs').contains(event.relatedTarget)) clearScenarioDropMarkers();
  });
  $('scenario-tabs').addEventListener('drop', event => {
    const position = scenarioDropPosition(event);
    if (!position) return;
    event.preventDefault();
    const id = draggingScenarioId;
    clearScenarioDrag();
    moveScenario(id, position.index);
  });
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
      if (input.dataset.field === 'pricing_mode' && input.value === 'official') active().pricing_conditions.selected_year = 1;
      changed();
    });
  });
  document.querySelectorAll('[data-pricing-field]').forEach(input => {
    const field = input.dataset.pricingField;
    if (input.inputMode === 'decimal') {
      bindNumericInput(input, value => { active().pricing_conditions[field] = value; changed(); });
      return;
    }
    const event = input.type === 'checkbox' || input.type === 'radio' || input.tagName === 'SELECT' ? 'change' : 'input';
    input.addEventListener(event, () => {
      if (input.type === 'radio' && !input.checked) return;
      active().pricing_conditions[field] = input.type === 'checkbox' ? input.checked : input.value;
      changed();
    });
  });
  $('pricing-review-legacy').addEventListener('click', () => {
    active().pricing_conditions.migration_review = '';
    changed();
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
    comparisonYears.delete(project.active_scenario_id);
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
  $('new-project').addEventListener('click', async () => { if (!(await confirmDiscard())) return; comparisonYears.clear(); project = E.makeProject(); dirty = false; renderAll(); persistDraft(); updateStatus(); });
  $('load-example').addEventListener('click', async () => { if (!(await confirmDiscard())) return; comparisonYears.clear(); project = E.createExampleProject(); dirty = false; renderAll(); persistDraft(); updateStatus(); });
  $('open-project').addEventListener('click', () => $('open-file').click());
  $('open-file').addEventListener('change', async event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    try {
      if (file.size > 16 * 1024 * 1024) throw new Error('프로젝트 파일은 16MB 이하여야 합니다.');
      const loaded = E.parseProject(await file.text());
      if (!(await confirmDiscard())) return;
      comparisonYears.clear();
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
    if (event.key === 'Escape') clearScenarioDrag();
    if (event.target.matches('#scenario-tabs [role="tab"]') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const buttons = [...$('scenario-tabs').children];
      const current = buttons.indexOf(event.target);
      if (event.altKey && event.shiftKey && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
        moveScenario(event.target.dataset.scenarioId, current + (event.key === 'ArrowRight' ? 1 : -1));
        return;
      }
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
    if (event.target.matches('[data-material-field],.sf-sales-input') && event.key === 'Enter') { event.preventDefault(); event.target.blur(); }
  });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  renderAll();
  selectTab('input');
  if (loadNotice) showToast(loadNotice);
  window.PharmaCostApp = {getProject: () => JSON.parse(JSON.stringify(project)), getResult: () => currentResult, getProfitResult: () => currentProfitResult};
})();
