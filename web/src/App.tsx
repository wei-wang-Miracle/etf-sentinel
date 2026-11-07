import { useEffect, useState } from "react";
import Compare from "./pages/Compare";
import MyEtfs from "./pages/MyEtfs";
import MyStrategies from "./pages/MyStrategies";
import DataManagement from "./pages/DataManagement";
import "./styles/strategy-journey.css";

const pages = [
  { key: "etfs", label: "我的 ETF", icon: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 6 6" },
  { key: "strategies", label: "我的策略", icon: "M3 3v18h18M6 15l4-5 4 3 6-8" },
  { key: "data", label: "数据管理", icon: "M3 6h18M3 12h18M3 18h18M8 4v4M16 10v4M10 16v4" },
];
function pageFromUrl() {
  const query = new URLSearchParams(location.search);
  const old = query.get("page");
  const routes: Record<string, Record<string, string>> = {
    research: { page: "etfs", detail: "overview" },
    review: { page: "etfs", detail: "operations", code: query.get("code") ?? "510500" },
    backtests: { page: "strategies", view: "legacy" },
    compare: { page: "etfs", auxiliary: "compare" },
    instruments: { page: "data", manage: "instruments" },
    jobs: { page: "data", manage: "jobs" },
    market: { page: "etfs", object: `etf:${query.get("code") ?? "510500"}`, detail: "overview", tab: "price" },
    "national-team": { page: "etfs", object: `etf:${query.get("code") ?? "510500"}`, detail: "overview", tab: "funds" },
    "index-valuations": { page: "etfs", object: `index:${query.get("code") ?? "000905.SH"}`, detail: "overview", tab: "valuation" },
    sentiment: { page: "etfs", auxiliary: "compare", dimension: "sentiment" },
  };
  if (old && routes[old]) {
    Object.entries(routes[old]).forEach(([key, value]) => query.set(key, value));
    if (old === "sentiment" && query.get("category")) query.set("codes", query.get("category")!);
    history.replaceState(null, "", `?${query}`);
  }
  if (query.get("code") && !query.has("object")) {
    query.set("object", `etf:${query.get("code")}`);
    history.replaceState(null, "", `?${query}`);
  } else if (query.get("object")?.startsWith("etf:") && !query.has("code")) {
    query.set("code", query.get("object")!.slice(4));
    history.replaceState(null, "", `?${query}`);
  }
  return pages.some((item) => item.key === query.get("page")) ? query.get("page")! : "etfs";
}
export default function App() {
  const [page, setPage] = useState(pageFromUrl);
  const [, refreshUrl] = useState(0);
  useEffect(() => { const changed = () => { setPage(pageFromUrl()); refreshUrl((old) => old + 1); }; window.addEventListener("popstate", changed); return () => window.removeEventListener("popstate", changed); }, []);
  function navigate(next: string) { history.pushState(null, "", `?page=${next}`); setPage(next); window.dispatchEvent(new PopStateEvent("popstate")); }
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") ?? "dark",
  );
  document.documentElement.dataset.theme = theme;
  const title = pages.find((p) => p.key === page)?.label;
  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("theme", next);
  }
  return (
    <div className={`app-shell ${collapsed ? "collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">研</span>
          {!collapsed && (
            <div>
              <strong>投研工作台</strong>
              <span>基金哨兵</span>
            </div>
          )}
        </div>
        <button
          className="collapse-button"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? "展开导航" : "折叠导航"}
          aria-expanded={!collapsed}
        >
          <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d={collapsed ? "m9 6 6 6-6 6" : "m15 6-6 6 6 6"} />
          </svg>
        </button>
        {!collapsed && <div className="nav-label">研究工作台</div>}
        <nav aria-label="主导航">
          {pages.map((p) => (
            <button
              key={p.key}
              className={`nav-item ${page === p.key ? "active" : ""}`}
              aria-current={page === p.key ? "page" : undefined}
              title={p.label}
              aria-label={p.label}
              onClick={() => navigate(p.key)}
            >
              <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path d={p.icon} />
              </svg>
              {!collapsed && p.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          {!collapsed && (
            <>
              <strong>个人基金投研</strong>
              <span>历史数据 · 日频研究</span>
            </>
          )}
          <span className="mono">版本 0.3</span>
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar">
          <span>
            <span className="muted">研究工作台</span>
            <span className="separator">/</span>
            {title}
          </span>
          <div>
            <span className="muted mono">
              {new Date().toLocaleDateString("sv-SE", {
                timeZone: "Asia/Shanghai",
              })}
            </span>
            <button onClick={toggleTheme} aria-label="切换主题">
              {theme === "dark" ? "亮色" : "暗色"}
            </button>
          </div>
        </div>
        <main>
          {page === "strategies" ? <MyStrategies theme={theme} /> : page === "data" ? <DataManagement key={new URLSearchParams(location.search).get("manage") ?? "instruments"} initialTab={new URLSearchParams(location.search).get("manage") ?? "instruments"} /> : new URLSearchParams(location.search).get("auxiliary") === "compare" ? <><a href="?page=etfs">← 返回我的 ETF</a><Compare theme={theme} /></> : <MyEtfs theme={theme} />}
        </main>
        <div className="workspace-footer">
          <span>投研工作台</span>
          <span>数据有来源，研究可追溯</span>
        </div>
      </div>
    </div>
  );
}
