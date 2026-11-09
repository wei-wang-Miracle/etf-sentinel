import { useState } from "react";
import { api } from "../lib/api";
import type { EntrustCandidate, PlanSignal } from "../lib/strategyLab";

const root = "/strategy-lab";
const number = (value: string | number) =>
  Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });

export function ExecutionForm({
  signal,
  refresh,
  report,
}: {
  signal: PlanSignal;
  refresh: () => Promise<void>;
  report: (message: string) => void;
}) {
  const [candidates, setCandidates] = useState<EntrustCandidate[] | null>(null);
  const [chosen, setChosen] = useState("");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [planPreceded, setPlanPreceded] = useState(false);
  const [busy, setBusy] = useState(false);
  async function action(operation: () => Promise<unknown>) {
    setBusy(true);
    try {
      await operation();
      await refresh();
    } catch (e) {
      report((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const candidate = candidates?.find((row) => row.entrust_no === chosen);
  return (
    <details className="backtest-assumptions">
      <summary>核对真实累计委托／主动跳过</summary>
      <p>
        委托匹配仅为候选，不代表已执行；请先同步真实成交，再依据券商明细确认成交日期和计划在先。
      </p>
      <button
        disabled={busy}
        onClick={() =>
          void action(async () => {
            const rows = await api<EntrustCandidate[]>(
              `${root}/signals/${signal.id}/candidates`,
            );
            setCandidates(rows);
            setChosen("");
          })
        }
      >
        读取累计委托候选
      </button>
      {candidates && (
        <>
          <label>
            累计委托{" "}
            <select value={chosen} onChange={(e) => setChosen(e.target.value)}>
              <option value="">请明确选择</option>
              {candidates.map((row) => (
                <option key={row.entrust_no} value={row.entrust_no}>
                  {row.entrust_no} · {row.curr_date} · {number(row.quantity)}份
                  · {row.price}元
                </option>
              ))}
            </select>
          </label>
          {!candidates.length && (
            <p>暂无符合标的、方向及日期的累计成交候选。</p>
          )}
          {candidate && (
            <p>
              {candidate.note}；费用 {candidate.fee_amount} 元。
            </p>
          )}
        </>
      )}
      <form
        className="backtest-controls"
        onSubmit={(e) => {
          e.preventDefault();
          if (candidate)
            void action(() =>
              api(`${root}/signals/${signal.id}/link`, "POST", {
                curr_date: candidate.curr_date,
                entrust_no: candidate.entrust_no,
                confirmed_trade_date: date,
                confirm_plan_preceded_trade: planPreceded,
                confirmation_note: note,
              }),
            );
        }}
      >
        <label>
          实际成交日
          <input
            type="date"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label>
          券商核对依据／跳过原因
          <input
            required
            maxLength={1000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <label className="switch">
          <input type="checkbox" checked={planPreceded} onChange={(e) => setPlanPreceded(e.target.checked)} />
          已依据券商明细确认计划先于实际成交（含集合竞价）
        </label>
        <button
          disabled={
            busy || !candidate || !note.trim() || !date || !planPreceded || !!signal.skip_note
          }
        >
          确认关联该累计委托
        </button>
        <button
          type="button"
          disabled={
            busy ||
            !note.trim() ||
            !!signal.skip_note ||
            signal.execution.links.length > 0
          }
          onClick={() =>
            void action(() =>
              api(`${root}/signals/${signal.id}/skip`, "POST", { note }),
            )
          }
        >
          记录主动跳过
        </button>
      </form>
    </details>
  );
}