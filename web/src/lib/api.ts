export type Instrument = {
  code: string;
  name: string;
  enabled: boolean;
  start_date: string;
  count: number;
  first_date: string | null;
  last_date: string | null;
  source: string;
};
export type Log = {
  code?: string;
  start?: string;
  end?: string;
  status: string;
  count?: number;
  message: string;
};
export type Run = {
  id: number;
  status: string;
  trigger: string;
  started_at: string;
  ended_at: string | null;
  logs: Log[];
};
export type Job = {
  enabled: boolean;
  time: string;
  next_run: string | null;
  source_configured: boolean;
  runs: Run[];
};
export type Candle = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  change_pct: number | null;
  source_updated_at: string | null;
  collected_at: string;
};

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    signal,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}），请检查 API 后重试`;
    try {
      const result = await response.json();
      if (typeof result.detail === "string") message = result.detail;
      else if (response.status === 422)
        message = "配置格式无效，请检查日期或时间";
    } catch {
      /* 非 JSON 错误保留 HTTP 摘要。 */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export const stamp = (value: string | null) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—";
export const statusNames: Record<string, string> = {
  running: "运行中",
  success: "成功",
  partial: "部分失败",
  failed: "失败",
  interrupted: "已中断",
};
