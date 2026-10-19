/* SF 결과 표시 전용 모듈. 계산과 프로젝트 데이터 변경은 하지 않습니다. */
(function () {
  'use strict';
  const D = window.PharmaCost.Decimal;
  const NS = 'http://www.w3.org/2000/svg';
  const COLORS = ['#087f82', '#8b5ca9', '#cb8b32', '#4e76ac'];
  const assignedColors = new Map();
  const $ = id => document.getElementById(id);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function svg(tag, attrs = {}, text) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function color(id) {
    if (!assignedColors.has(id)) {
      const used = new Set(assignedColors.values());
      assignedColors.set(id, COLORS.find(item => !used.has(item)) || COLORS[assignedColors.size % COLORS.length]);
    }
    return assignedColors.get(id);
  }
  function money(value, places = 2) {
    if (value === null || value === undefined) return '—';
    return new D(value).toFixed(places).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
  function rate(value) { return value === null || value === undefined ? '계산 불가' : money(value, 1) + '%'; }
  function dot(id) {
    const node = el('span', 'profit-color-dot');
    node.style.backgroundColor = color(id);
    node.setAttribute('aria-hidden', 'true');
    return node;
  }
  function namedScenario(scenario) {
    const node = el('span', 'profit-scenario-name');
    node.append(dot(scenario.id), el('span', '', scenario.name));
    return node;
  }
  function issuesText(issues) {
    return (issues || []).map(issue => typeof issue === 'string' ? issue : issue.message || issue.label || '').filter(Boolean).join(' · ');
  }
  function tooltip(scenario, row, cumulative) {
    return scenario.name + ' · ' + row.year + '년차\nSF 판매수량 ' + money(row.quantity, 0) + ' T\n매출액 ' + money(row.sales) + ' 원\n약가 ' + money(row.price, 0) + ' 원/T · 제조원가율 ' + rate(row.cost_rate) + '\n예상 제조원가 ' + money(row.manufacturing_cost) + ' 원\n예상이익 ' + money(row.profit) + ' 원' + (cumulative ? '\n누적 예상이익 ' + money(row.cumulative_profit) + ' 원' : '');
  }
  function axisLabel(value) {
    const amount = new D(value);
    if (amount.abs().gte('1000000000000000000000') || (!amount.eq(0) && amount.abs().lt('0.01'))) return amount.toExponential(1).replace('e+', 'e');
    return money(amount, amount.eq(0) || amount.abs().gte(1) ? 0 : 2);
  }
  function renderChart(result, cumulative) {
    const host = $(cumulative ? 'profit-cumulative-chart' : 'profit-annual-chart');
    host.replaceChildren();
    const values = [];
    const key = cumulative ? 'cumulative_profit' : 'profit';
    result.scenarios.forEach(scenario => scenario.rows.forEach(row => {
      if (row[key] !== null && row[key] !== undefined) values.push(new D(row[key]));
    }));
    if (!values.length) {
      host.append(el('div', 'profit-chart-empty', '연차별 SF와 원가 계산에 필요한 값을 입력하면 그래프가 표시됩니다.'));
      return;
    }
    let low = D.min(0, ...values), high = D.max(0, ...values);
    if (high.eq(low)) high = low.plus(1);
    // Round only the display axis to useful intervals; domain values stay exact.
    const targetStep = high.minus(low).div(4);
    const magnitude = new D(10).pow(targetStep.e);
    const normalizedStep = targetStep.div(magnitude);
    const factor = [1, 2, 2.5, 5, 10].find(value => normalizedStep.lte(value));
    const step = magnitude.times(factor);
    low = low.div(step).floor().times(step);
    high = high.div(step).ceil().times(step);
    if (high.eq(low)) high = low.plus(step);
    const tickCount = high.minus(low).div(step).toNumber();
    const range = high.minus(low);
    const axisLabels = Array.from({length: tickCount + 1}, (_, tick) => axisLabel(high.minus(step.times(tick))));
    const labelWidth = Math.max(...axisLabels.map(label => label.length)) * 6.5;
    const width = 720, height = 350, left = Math.max(92, Math.min(198, labelWidth + 18)), right = 20, top = 32, bottom = 45;
    const chartWidth = width - left - right, chartHeight = height - top - bottom;
    const y = value => top + new D(high).minus(value).div(range).times(chartHeight).toNumber();
    const x = year => left + chartWidth * (year - 0.5) / result.years;
    const zero = y(0);
    const graphic = svg('svg', {viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': (cumulative ? '누적' : '연차별') + ' 예상이익, 금액 단위 원', class: 'profit-chart-svg'});
    graphic.append(svg('title', {}, (cumulative ? '누적' : '연차별') + ' 예상이익 비교'));
    graphic.append(svg('desc', {}, '가로축은 1년차부터 ' + result.years + '년차, 세로축 금액은 원입니다. 음수는 기준선 아래에 표시하며 미입력값은 표시하지 않습니다. 자세한 값은 아래 계산 내역 표에서 확인할 수 있습니다.'));
    graphic.append(svg('text', {x: left, y: 17, class: 'profit-axis-unit'}, '원'));
    for (let tick = 0; tick <= tickCount; tick++) {
      const value = high.minus(step.times(tick)), py = y(value);
      graphic.append(svg('line', {x1: left, x2: width - right, y1: py, y2: py, class: 'profit-gridline'}));
      graphic.append(svg('text', {x: left - 10, y: py + 4, 'text-anchor': 'end', class: 'profit-axis-label'}, axisLabel(value)));
    }
    graphic.append(svg('line', {x1: left, x2: width - right, y1: zero, y2: zero, class: 'profit-zero-line', 'data-zero-y': zero}));
    for (let year = 1; year <= result.years; year++) {
      graphic.append(svg('text', {x: x(year), y: height - 17, 'text-anchor': 'middle', class: 'profit-axis-label'}, year + '년차'));
    }
    result.scenarios.forEach((scenario, scenarioIndex) => {
      const tint = color(scenario.id);
      if (cumulative) {
        let segment = [];
        const appendSegment = () => {
          if (segment.length > 1) graphic.append(svg('polyline', {points: segment.join(' '), fill: 'none', stroke: tint, 'stroke-width': 2.5, 'stroke-linejoin': 'round', class: 'profit-cumulative-line', 'data-scenario-id': scenario.id}));
          segment = [];
        };
        scenario.rows.forEach(row => {
          if (row.cumulative_profit === null || row.cumulative_profit === undefined) { appendSegment(); return; }
          segment.push(x(row.year) + ',' + y(row.cumulative_profit));
        });
        appendSegment();
      }
      scenario.rows.forEach(row => {
        const value = row[key];
        if (value === null || value === undefined) return;
        let mark;
        if (cumulative) {
          mark = svg('circle', {cx: x(row.year), cy: y(value), r: 4, fill: tint, stroke: '#fff', 'stroke-width': 1.4});
        } else {
          const groupWidth = chartWidth / result.years * .74;
          const slotWidth = groupWidth / result.scenarios.length;
          const barWidth = Math.min(30, slotWidth * .82);
          const px = x(row.year) - groupWidth / 2 + slotWidth * (scenarioIndex + .5) - barWidth / 2;
          const point = y(value), isZero = new D(value).eq(0);
          mark = svg('rect', {x: px, y: isZero ? zero - 1.5 : Math.min(zero, point), width: barWidth, height: isZero ? 3 : Math.max(.6, Math.abs(zero - point)), rx: 2, fill: tint, class: isZero ? 'profit-zero-marker' : 'profit-annual-bar'});
        }
        const label = tooltip(scenario, row, cumulative);
        mark.setAttribute('tabindex', '0');
        mark.setAttribute('role', 'img');
        mark.setAttribute('aria-label', label.replace(/\n/g, ' · '));
        mark.dataset.scenarioId = scenario.id;
        mark.dataset.year = row.year;
        mark.dataset.value = new D(value).toString();
        mark.dataset.kind = cumulative ? 'cumulative' : 'annual';
        mark.append(svg('title', {}, label));
        graphic.append(mark);
      });
    });
    host.append(graphic);
  }
  function renderSummary(result) {
    const head = $('profit-summary-head'), body = $('profit-summary-body');
    head.replaceChildren(); body.replaceChildren();
    const heading = el('tr');
    ['시나리오', '누적 판매수량 (T)', '누적 매출액 (원)', '누적 제조원가 (원)', '누적 예상이익 (원)', '기준 대비 이익 차이 (원)', '입력 상태'].forEach((text, index) => {
      const th = el('th', index > 0 && index < 6 ? 'numeric' : '', text);
      th.scope = 'col'; heading.append(th);
    });
    head.append(heading);
    result.scenarios.forEach(scenario => {
      const row = el('tr'); row.dataset.scenarioId = scenario.id;
      const name = el('th'); name.scope = 'row'; name.append(namedScenario(scenario)); row.append(name);
      ['total_quantity', 'total_sales', 'total_cost', 'total_profit', 'difference_from_baseline'].forEach(key => {
        const cell = el('td', 'numeric' + (key === 'total_profit' ? ' profit-total-cell' : ''), money(scenario[key], key === 'total_quantity' ? 0 : 2));
        cell.dataset.profitField = key;
        if (scenario[key] !== null && scenario[key] !== undefined && new D(scenario[key]).lt(0)) cell.classList.add('negative');
        row.append(cell);
      });
      const status = el('td', 'profit-completeness');
      status.append(el('span', 'status-pill ' + (scenario.complete ? 'success' : 'warning'), scenario.complete ? '입력 완료' : '미완성'));
      if (!scenario.complete) {
        const missing = scenario.rows.filter(item => item.profit === null || item.profit === undefined).map(item => item.year + '년차');
        if (missing.length) status.append(el('small', '', missing.join(' · ')));
      }
      row.append(status); body.append(row);
    });
    const baseline = result.scenarios.find(item => item.id === result.baseline_id);
    $('profit-baseline-note').textContent = '분석기간: 1~' + result.years + '년차 · 기준 시나리오: ' + (baseline ? baseline.name : '—') + ' · 미완성인 누적값과 이익 차이는 확정해 표시하지 않습니다.';
  }
  function renderDetails(result) {
    const head = $('profit-details-head'), body = $('profit-details-body');
    head.replaceChildren(); body.replaceChildren();
    const scenarios = el('tr'), labels = el('tr');
    const year = el('th', '', '연차'); year.rowSpan = 2; year.scope = 'col'; scenarios.append(year);
    result.scenarios.forEach(scenario => {
      const name = el('th'); name.colSpan = 4; name.scope = 'colgroup'; name.append(namedScenario(scenario)); scenarios.append(name);
      ['판매수량 (T)', '매출액 (원)', '제조원가 (원)', '예상이익 (원)'].forEach(text => { const th = el('th', 'numeric', text); th.scope = 'col'; labels.append(th); });
    });
    head.append(scenarios, labels);
    for (let index = 0; index < result.years; index++) {
      const row = el('tr'); row.dataset.year = index + 1;
      const name = el('th', '', index + 1 + '년차'); name.scope = 'row'; row.append(name);
      result.scenarios.forEach(scenario => {
        const item = scenario.rows.find(entry => entry.year === index + 1);
        ['quantity', 'sales', 'manufacturing_cost', 'profit'].forEach(key => {
          const cell = el('td', 'numeric', money(item ? item[key] : null, key === 'quantity' ? 0 : 2));
          cell.dataset.scenarioId = scenario.id; cell.dataset.profitField = key;
          if (item) cell.title = tooltip(scenario, item, false) + (item.issues && item.issues.length ? '\n' + issuesText(item.issues) : '');
          if (item && item[key] !== null && item[key] !== undefined && new D(item[key]).lt(0)) cell.classList.add('negative');
          row.append(cell);
        });
      });
      body.append(row);
    }
  }
  function render(result) {
    if (!result || !result.enabled) return;
    const activeIds = new Set(result.scenarios.map(scenario => scenario.id));
    for (const id of assignedColors.keys()) if (!activeIds.has(id)) assignedColors.delete(id);
    const legend = $('profit-scenario-legend');
    legend.replaceChildren();
    result.scenarios.forEach(scenario => legend.append(namedScenario(scenario)));
    const anySales = result.scenarios.some(scenario => scenario.rows.some(row => row.quantity !== null && row.quantity !== undefined));
    const complete = result.scenarios.every(scenario => scenario.complete);
    const status = $('profit-analysis-status');
    status.classList.toggle('warning', !complete && anySales);
    status.textContent = !anySales ? '입력 탭에서 연차별 SF 판매수량(T)을 입력해 주세요. 판매가 없는 연도에는 0을 입력하세요.' : complete ? '모든 시나리오의 입력이 완료되었습니다. 현재 제조원가/T를 분석기간 동안 동일하게 적용합니다.' : '미입력 또는 계산 불가인 연도가 있습니다. 계산 가능한 연도만 그래프에 표시하며, 이후 누적값은 입력을 완료해야 계산됩니다.';
    renderChart(result, false);
    renderChart(result, true);
    renderSummary(result);
    renderDetails(result);
  }
  window.PharmaProfitView = Object.freeze({render});
}());
