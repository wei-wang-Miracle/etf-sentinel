import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

// 每次运行可续接轮次；轮内候选根据上一轮最优及亏损诊断生成，分段是否参与调参由每轮冻结口径明确记录。
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.resolve(process.argv[2] ?? path.join(web, '../.local/turning-research/2026-11-18-rerun'));
const requested = Number(process.argv[3] ?? 50);
const finalize = process.argv.includes('--finalize');
if (!Number.isInteger(requested) || requested < 0 || requested > 50) throw Error('轮次须为0至50');
const build = path.join(directory, 'engine');
fs.mkdirSync(build, { recursive: true });
execFileSync(process.execPath, [path.join(web, 'node_modules/typescript/bin/tsc'), 'src/lib/turningPoints.ts', '--outDir', build, '--target', 'ES2022', '--module', 'ES2022', '--moduleResolution', 'bundler', '--skipLibCheck'], { cwd: web, stdio: 'pipe' });
fs.writeFileSync(path.join(build, 'package.json'), '{"type":"module"}');
const source = fs.readFileSync(path.join(web, 'src/lib/turningPoints.ts'), 'utf8');
const hash = text => createHash('sha256').update(text).digest('hex');
const engineFiles = [
  ['turningPoints.ts', source],
  ['turning_simulator.py', fs.readFileSync(path.join(web, 'scripts/turning_simulator.py'), 'utf8')],
  ['backtest.py', fs.readFileSync(path.join(web, '../api/app/backtest.py'), 'utf8')],
  ['strategy_research.py', fs.readFileSync(path.join(web, '../api/app/strategy_research.py'), 'utf8')],
  ['strategies.py', fs.readFileSync(path.join(web, '../api/app/strategies.py'), 'utf8')],
];
const engineHash = hash(engineFiles.map(([name, text]) => `${name}\n${text}`).join('\n'));
const runnerHash = hash(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8'));
const { calculateTurningPoints, DEFAULT_TURNING_OPTIONS, TURNING_VERSION } = await import(pathToFileURL(path.join(build, 'turningPoints.js')));
const inputText = fs.readFileSync(path.join(directory, 'history.json'), 'utf8');
const history = JSON.parse(fs.readFileSync(path.join(directory, 'qualified-history.json'), 'utf8'));
const qualifiedText = fs.readFileSync(path.join(directory, 'qualified-history.json'), 'utf8');
const groups = JSON.parse(fs.readFileSync(path.join(directory, 'classification.json'), 'utf8'));
const groupByCode = Object.fromEntries(Object.entries(groups).flatMap(([group, value]) => value.codes.map(code => [code, group])));
const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'data-manifest.json')));
if (hash(qualifiedText) !== manifest.qualifiedSha256 || hash(inputText) !== manifest.sha256) throw Error('冻结输入摘要不符');
const costs = { initialCash: 50000, lotSize: 100, commissionRate: .0001, minimumCommission: 0, slippageBps: 5 };
const logPath = path.join(directory, 'rounds.json');
const rounds = fs.existsSync(logPath) ? JSON.parse(fs.readFileSync(logPath)) : [];
const write = (file, value) => fs.writeFileSync(path.join(directory, file), JSON.stringify(value, null, 2));
const key = option => JSON.stringify(Object.fromEntries(Object.entries(option).sort(([a], [b]) => a.localeCompare(b))));
const grids = {
  topMaWindow: [3, 5, 7, 10, 15, 20], topBreakoutWindow: [2, 3, 5, 7, 10, 15], topConfirmationDays: [1, 2, 3], topTrailingAtr: [0, .5, 1, 1.5, 2, 3],
  backgroundDays: [1, 2, 3, 5, 7, 10], slopeThreshold: [.01, .03, .05, .08, .12, .2],
  shortSlopeThreshold: [0, .03, .05, .1, .2, .3], breakoutWindow: [2, 3, 5, 7, 10, 15, 20],
  breakoutAtrMultiplier: [0, .1, .2, .4, .6, 1], confirmationDays: [1, 2, 3, 4, 5],
  cooldownDays: [0, 5, 10, 15, 20, 30], confirmationMaWindow: [3, 5, 10, 15, 20, 30],
};
let seed = 20261118 + rounds.length * 1009;
const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
const pick = list => list[Math.floor(random() * list.length)];
function evaluate(optionsByGroup, begin, end, selectedGroup) {
  const signalMap = {};
  for (const [code, item] of Object.entries(history)) {
    if (!item.eligible || !groupByCode[code] || (selectedGroup && groupByCode[code] !== selectedGroup)) continue;
    const input = item.rows.filter(row => row.date >= item.analysisStart && row.date <= end);
    signalMap[code] = calculateTurningPoints(input, optionsByGroup[groupByCode[code]], begin).signals;
  }
  const funds = JSON.parse(execFileSync(path.join(web, '../api/.venv/bin/python'),
    [path.join(web, 'scripts/turning_simulator.py'), directory, begin, end],
    { input: JSON.stringify(signalMap), maxBuffer: 32 * 1024 * 1024, encoding: 'utf8' }));
  const pairs = funds.flatMap(fund => fund.pairs.map(pair => ({ code: fund.code, ...pair })));
  const wins = pairs.filter(pair => pair.profit > 0).length;
  const initial = costs.initialCash * funds.length;
  const equity = funds.reduce((sum, fund) => sum + fund.finalEquity, 0);
  const summary = { group: selectedGroup ?? '总体', trades: pairs.length, wins, winRate: pairs.length ? wins / pairs.length : null,
    totalReturn: equity / initial - 1, finalEquity: equity,
    worstFundDrawdown: Math.min(...funds.map(fund => fund.maxDrawdown)),
    profitableFunds: funds.filter(fund => fund.totalReturn > 0).length,
    openFunds: funds.filter(fund => fund.openQuantity > 0).length,
    openProfit: funds.reduce((sum, fund) => sum + fund.openProfit, 0),
    losingOpenFunds: funds.filter(fund => fund.openProfit < 0).length,
    maxHoldingDays: Math.max(0, ...pairs.map(pair => pair.holdingDays)),
    maxOpenHoldingDays: Math.max(0, ...funds.map(fund => fund.openHoldingDays)),
    profitFactor: pairs.some(pair => pair.profit < 0) ? pairs.filter(pair => pair.profit > 0).reduce((s, p) => s + p.profit, 0) / -pairs.filter(pair => pair.profit < 0).reduce((s, p) => s + p.profit, 0) : null,
  };
  const score = (summary.winRate ?? 0) - Math.max(0, 30 - pairs.length) * .05
    - summary.losingOpenFunds * .025 - Math.max(0, -summary.openProfit / initial) * .25
    + Math.min(.5, summary.totalReturn) * .1 + summary.worstFundDrawdown * .2;
  return { option: selectedGroup ? optionsByGroup[selectedGroup] : optionsByGroup, summary, score, funds };
}
function diagnose(result) {
  const losses = result.funds.flatMap(f => f.pairs.filter(p => p.profit <= 0).map(p => {
    const rows = history[f.code].rows.filter(row => row.date >= p.entryDate && row.date <= p.exitDate);
    const entry = f.trades.find(t => t.tradeDate === p.entryDate && t.side === 'buy').price;
    const favorable = Math.max(...rows.map(row => row.high)) / entry - 1;
    const adverse = Math.min(...rows.map(row => row.low)) / entry - 1;
    return { code: f.code, ...p, favorable, adverse };
  }));
  const gaveBack = losses.filter(p => p.favorable > .025).length;
  const quickLosses = losses.filter(p => p.holdingDays < 15).length;
  return { losses: losses.length, gaveBack, quickLosses,
    worst: [...losses].sort((a, b) => a.profit - b.profit).slice(0, 5),
    focus: gaveBack > losses.length / 2 ? '顶部响应偏慢，优先缩短退出确认与窗口' : quickLosses > losses.length / 2 ? '短期假反转较多，优先收紧入场确认' : '入场趋势与结构过滤需要比较，保留完整亏损样本' };
}
const optionsPath = path.join(directory, 'group-options.json');
let incumbent = fs.existsSync(optionsPath) ? JSON.parse(fs.readFileSync(optionsPath, 'utf8'))
  : Object.fromEntries(Object.keys(groups).map(group => [group, rounds.at(-1)?.selected.option ?? DEFAULT_TURNING_OPTIONS]));
const seen = new Set(rounds.flatMap(round => round.candidates.map(candidate => `${round.engineHash}:${round.group ?? ''}:${key(candidate.option)}`)));
while (rounds.length < requested) {
  const number = rounds.length + 1;
  seed = 20261118 + number * 1009;
  const groupKeys = Object.keys(groups);
  const firstGroupRound = manifest.classificationStartRound ?? 1;
  const group = groupKeys[((number - firstGroupRound) % groupKeys.length + groupKeys.length) % groupKeys.length];
  const beforeResult = evaluate(incumbent, '0000-01-01', manifest.fitEnd, group);
  const before = diagnose(beforeResult);
  const candidates = [incumbent[group]];
  if (number > 20) {
    // 一项逐点比较加双项邻域；停滞时扩大扰动。每一轮都重新诊断当前最优。
    const keys = Object.keys(grids);
    const focusKeys = before.gaveBack > before.losses / 2 ? ['topMaWindow', 'topBreakoutWindow', 'topConfirmationDays', 'topTrailingAtr'] : ['backgroundDays', 'breakoutWindow', 'confirmationDays'];
    const axis = number % 2 === 0 ? focusKeys[Math.floor(number / 2) % focusKeys.length] : keys[(number - 2) % keys.length];
    if (grids[axis]) for (const value of grids[axis]) candidates.push({ ...incumbent[group], [axis]: value });
    for (let i = 0; i < 10; i++) {
      const candidate = { ...incumbent[group] };
      const count = number % 7 === 0 ? 4 : 2;
      for (let j = 0; j < count; j++) { const field = pick(keys); candidate[field] = pick(grids[field]); }
      candidates.push(candidate);
    }
  }
  const evaluated = [beforeResult];
  for (const candidate of candidates) {
    const id = `${engineHash}:${group}:${key(candidate)}`;
    if (seen.has(id) || key(candidate) === key(incumbent[group])) continue;
    seen.add(id);
    evaluated.push(evaluate({ ...incumbent, [group]: candidate }, '0000-01-01', manifest.fitEnd, group));
  }
  evaluated.sort((a, b) => b.score - a.score || b.summary.totalReturn - a.summary.totalReturn);
  const best = evaluated[0];
  // 逐项评估以所研究组参数覆盖；选项来自评分第一名，保存后供后续同组轮次续接。
  incumbent[group] = best.option ?? incumbent[group];
  const diagnostic = diagnose(best);
  const allGroups = Object.fromEntries(Object.keys(groups).map(name => [name, evaluate(incumbent, '0000-01-01', manifest.fitEnd, name).summary]));
  const allTargets = Object.values(allGroups).every(item => item.trades >= 30 && item.winRate >= .8 && item.totalReturn > 0);
  const record = { round: number, group, groupName: groups[group].name, engineHash, version: TURNING_VERSION, dataSha256: manifest.sha256,
    evaluation: { begin: '各ETF折算后起始日', end: manifest.fitEnd, qualifiedSha256: manifest.qualifiedSha256, usedHistoryForFitting: manifest.checkUsedForResearchAfterRound != null },
    seed: 20261118 + number * 1009, diagnosisBefore: before, axis: number <= 20 ? '统一规则阶段；不作为分类结果' : '按ETF所属跟踪指数分类，依据该类亏损K线调整',
    candidates: evaluated.map(({ option, summary, score }) => ({ option, summary, score })),
    selected: { option: incumbent[group], summary: best.summary, score: best.score }, groupOptions: structuredClone(incumbent), groupSummaries: allGroups, diagnosisAfter: diagnostic, target: allTargets };
  rounds.push(record);
  write('group-options.json', incumbent);
  fs.writeFileSync(path.join(directory, `engine-${engineHash.slice(0, 12)}.ts`), source);
  fs.copyFileSync(path.join(web, 'scripts/turning_simulator.py'), path.join(directory, `simulator-${engineHash.slice(0, 12)}.py`));
  fs.copyFileSync(path.join(web, 'scripts/fit-turning-points.mjs'), path.join(directory, `runner-round-${number}.mjs`));
  const selected = evaluate(incumbent, '0000-01-01', manifest.fitEnd, group);
  write(`round-${String(number).padStart(2, '0')}-selected.json`, selected);
  write('rounds.json', rounds);
  console.log(JSON.stringify({ round: number, group, candidates: evaluated.length, ...selected.summary, target: allTargets }));
  if (allTargets) break;
}
if (finalize) {
  // 近期区间此前已用于观察，只作历史诊断，不作为独立样本外验证。
  const recentDiagnostic = Object.fromEntries(Object.keys(groups).map(group => [group, evaluate(incumbent, manifest.checkStart, manifest.end, group)]));
  const full = Object.fromEntries(Object.keys(groups).map(group => [group, evaluate(incumbent, '0000-01-01', manifest.end, group)]));
  const fitted = Object.fromEntries(Object.keys(groups).map(group => [group, evaluate(incumbent, '0000-01-01', manifest.fitEnd, group)]));
  for (const [name, contents] of engineFiles) fs.writeFileSync(path.join(directory, `snapshot-${name}`), contents);
  write('final.json', { rounds: rounds.length, engineHash, runnerHash, manifest, costs, optionsByGroup: incumbent, fitted, recentDiagnostic, full });
  console.log(JSON.stringify({ final: true, rounds: rounds.length, fitted: Object.fromEntries(Object.entries(fitted).map(([k,v])=>[k,v.summary])), recentDiagnostic: Object.fromEntries(Object.entries(recentDiagnostic).map(([k,v])=>[k,v.summary])), full: Object.fromEntries(Object.entries(full).map(([k,v])=>[k,v.summary])) }));
}
