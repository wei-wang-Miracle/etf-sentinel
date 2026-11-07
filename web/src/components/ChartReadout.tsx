import { useState } from "react";

export type ReadoutRow = { date: string; values: Record<string, string> };

export default function ChartReadout({ rows }: { rows: ReadoutRow[] }) {
  const [selectedDate, setSelectedDate] = useState("");
  if (!rows.length) return null;
  const selected = rows.findIndex((row) => row.date === selectedDate);
  const index = selected < 0 ? rows.length - 1 : selected;
  const row = rows[index];
  return <details className="chart-readout"><summary>键盘日期读数</summary>
    <div className="readout-controls"><button disabled={index === 0} onClick={() => setSelectedDate(rows[index - 1].date)} type="button">上一日</button>
      <label>读数日期<select aria-label="读数日期" value={row.date} onChange={(event) => setSelectedDate(event.target.value)}>{rows.map((item) => <option key={item.date}>{item.date}</option>)}</select></label>
      <button disabled={index === rows.length - 1} onClick={() => setSelectedDate(rows[index + 1].date)} type="button">下一日</button></div>
    <dl aria-live="polite" className="readout-values">{Object.entries(row.values).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </details>;
}
