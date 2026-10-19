/* Offline SF analysis. Sales and aggregate costs use millions of KRW (백만원). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./engine.js'));
  else root.PharmaProfit = factory(root.PharmaCost);
}(typeof globalThis !== 'undefined' ? globalThis : this, function (E) {
  'use strict';

  if (!E) throw new Error('원가 계산 모듈을 불러오지 못했습니다.');
  const Decimal = E.Decimal;
  const blank = value => value === null || value === undefined || (typeof value === 'string' && value.trim() === '');
  const problem = (path, message) => ({ path, message, severity: 'error' });

  function readSales(value, path, issues) {
    if (blank(value)) {
      issues.push(problem(path, 'SF 판매금액을 입력해 주세요.'));
      return null;
    }
    try { return E.parseNumber(value); }
    catch (error) {
      issues.push(problem(path, 'SF 판매금액: ' + error.message));
      return null;
    }
  }

  function positivePrice(value, issues) {
    if (value !== null && value !== undefined) {
      const amount = new Decimal(value);
      if (amount.isFinite() && amount.gt(0)) return amount;
    }
    issues.push(problem('price', '해당 연차의 약가가 없거나 0이어서 이익을 계산할 수 없습니다.'));
    return null;
  }

  function calculate(project) {
    const settings = project && project.profit_analysis;
    const output = {
      enabled: Boolean(settings && settings.enabled === true), years: settings ? settings.years : 8,
      baseline_id: project && Array.isArray(project.scenarios) && project.scenarios.length ? project.scenarios[0].id : null,
      scenarios: [], issues: []
    };
    // Existing costing remains independent of dormant SF entries.
    if (!output.enabled) return output;
    if (!Number.isInteger(output.years) || output.years < 1 || output.years > 10) {
      output.issues.push(problem('profit_analysis.years', '분석 기간은 1~10년의 정수로 입력해 주세요.'));
      return output;
    }
    const common = Array.isArray(settings.common_sales) ? settings.common_sales : [];
    for (const scenario of project.scenarios) {
      const calculated = E.calculate(scenario);
      const forecast = scenario.sales_forecast || {};
      const custom = Array.isArray(forecast.sales) ? forecast.sales : [];
      const item = {
        id: scenario.id, name: scenario.name, rows: [],
        total_sales: null, total_cost: null, total_profit: null, difference_from_baseline: null, complete: false
      };
      let cumulativeSales = new Decimal(0);
      let cumulativeCost = new Decimal(0);
      let cumulativeProfit = new Decimal(0);
      for (let index = 0; index < output.years; index += 1) {
        const issues = [];
        const useCustom = forecast.use_custom === true && !blank(custom[index]);
        const source = useCustom ? 'custom' : 'common';
        const path = useCustom ? 'scenarios.' + scenario.id + '.sales_forecast.sales.' + index : 'profit_analysis.common_sales.' + index;
        const sales = readSales(useCustom ? custom[index] : common[index], path, issues);
        const forecastYear = scenario.pricing_mode === 'official' && Array.isArray(calculated.pricing.years)
          ? calculated.pricing.years.find(year => year.year === index + 1) : null;
        const price = positivePrice(scenario.pricing_mode === 'manual' ? calculated.pricing.amount : forecastYear && forecastYear.amount, issues);
        const rawCost = calculated.total_cost;
        const cost = rawCost !== null && rawCost !== undefined && rawCost.isFinite() && rawCost.gte(0) ? new Decimal(rawCost) : null;
        if (cost === null) issues.push(problem('cost_per_unit', '제조원가 입력을 완료하면 이익을 계산할 수 있습니다.'));
        const rate = price !== null && cost !== null ? cost.div(price).times(100) : null;
        // The input unit is already 백만원; a dimensionless cost/price ratio preserves it.
        const manufacturing = sales !== null && price !== null && cost !== null ? sales.times(cost).div(price) : null;
        const profit = manufacturing !== null ? sales.minus(manufacturing) : null;
        cumulativeSales = cumulativeSales !== null && sales !== null ? cumulativeSales.plus(sales) : null;
        cumulativeCost = cumulativeCost !== null && manufacturing !== null ? cumulativeCost.plus(manufacturing) : null;
        cumulativeProfit = cumulativeProfit !== null && profit !== null ? cumulativeProfit.plus(profit) : null;
        item.rows.push({
          year: index + 1, sales, price, cost_per_unit: cost, cost_rate: rate, manufacturing_cost: manufacturing, profit,
          cumulative_sales: cumulativeSales, cumulative_cost: cumulativeCost, cumulative_profit: cumulativeProfit,
          sales_source: source, issues
        });
        output.issues.push(...issues.map(entry => Object.assign({ scenario_id: scenario.id, year: index + 1 }, entry)));
      }
      item.complete = item.rows.every(row => row.sales !== null && row.manufacturing_cost !== null && row.profit !== null);
      item.total_sales = item.complete ? cumulativeSales : null;
      item.total_cost = item.complete ? cumulativeCost : null;
      item.total_profit = item.complete ? cumulativeProfit : null;
      output.scenarios.push(item);
    }
    const baseline = output.scenarios.length ? output.scenarios[0].total_profit : null;
    output.scenarios.forEach(scenario => {
      scenario.difference_from_baseline = baseline !== null && scenario.total_profit !== null ? scenario.total_profit.minus(baseline) : null;
    });
    return output;
  }

  return Object.freeze({ calculate });
}));
