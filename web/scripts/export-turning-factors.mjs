import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

// 顶底仅导出为独立因子；用截至当日现金分红构造的含息OHLC消除除息跳变。
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.resolve(process.argv[2]);
const build = path.join(directory, 'turning-engine');
fs.mkdirSync(build, { recursive: true });
execFileSync(process.execPath, [path.join(web, 'node_modules/typescript/bin/tsc'), 'src/lib/turningPoints.ts', '--outDir', build, '--target', 'ES2022', '--module', 'ES2022', '--moduleResolution', 'bundler', '--skipLibCheck'], { cwd: web });
fs.writeFileSync(path.join(build, 'package.json'), '{"type":"module"}');
const { calculateTurningPoints, DEFAULT_TURNING_OPTIONS, TURNING_VERSION } = await import(pathToFileURL(path.join(build, 'turningPoints.js')));
const history = JSON.parse(fs.readFileSync(path.join(directory, 'input.json'), 'utf8'));
const output = {};
for (const [code, item] of Object.entries(history)) {
  const options = { ...DEFAULT_TURNING_OPTIONS, pairSignals: false };
  const result = calculateTurningPoints(item.factorRows, options);
  // 抽取多个历史前缀，验证扩展行情不会改写此前确认事件。
  for (const end of [120, 250, 400].filter(end => end < item.factorRows.length)) {
    const prefix = calculateTurningPoints(item.factorRows.slice(0, end), options).signals;
    const expected = result.signals.filter(s => s.date <= item.factorRows[end - 1].date);
    if (JSON.stringify(prefix) !== JSON.stringify(expected)) throw Error(`${code}顶底因子前缀不一致`);
  }
  output[code] = { version: TURNING_VERSION, options, signals: result.signals };
}
fs.writeFileSync(path.join(directory, 'turning.json'), JSON.stringify(output));
console.log(`已导出${Object.keys(output).length}只ETF顶底因子，前缀检查通过`);
