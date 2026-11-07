import { useEffect, useState } from "react";

export function dateAgo(days: number) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
}
export function useResearchQuery(defaults: Record<string, string>) {
  const read = () => {
    const query = new URLSearchParams(location.search);
    return Object.fromEntries(
      Object.entries(defaults).map(([key, value]) => [
        key,
        query.get(key) ?? value,
      ]),
    );
  };
  const [state, setState] = useState(read);
  useEffect(() => {
    const changed = () => setState(read());
    window.addEventListener("popstate", changed);
    return () => window.removeEventListener("popstate", changed);
  }, []);
  function update(values: Record<string, string>, options?: { history: "push" | "replace" }) {
    const query = new URLSearchParams(location.search);
    Object.entries(values).forEach(([key, value]) => query.set(key, value));
    if (values.object?.startsWith("etf:")) query.set("code", values.object.slice(4));
    else if (values.object?.startsWith("index:")) query.delete("code");
    else if (values.code !== undefined) {
      if (values.code) query.set("object", `etf:${values.code}`);
      else query.delete("object");
    }
    const navigation = Object.keys(values).some((key) =>
      ["code", "object", "detail", "tab", "manage", "task", "dimension", "view", "stage", "edit"].includes(key),
    );
    const mode = options?.history ?? (navigation ? "push" : "replace");
    if (`?${query}` !== location.search) history[mode === "push" ? "pushState" : "replaceState"](null, "", `?${query}`);
    setState((old) => ({ ...old, ...values }));
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  return [state, update] as const;
}
export const number = (value: unknown, digits = 2) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("zh-CN", {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
export const metrics: Record<string, { name: string; unit: string }> = {
  pe: { name: "市盈率", unit: "倍" },
  pb: { name: "市净率", unit: "倍" },
  xilv: { name: "股息率", unit: "%" },
  roe: { name: "净资产收益率", unit: "%" },
  premium_diff: { name: "风险溢价", unit: "百分点" },
};
