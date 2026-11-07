import { useEffect, useState } from "react";
import Instruments from "./pages/Instruments";
import Jobs from "./pages/Jobs";
import Backtests from "./pages/Backtests";
import Review from "./pages/Review";
import Compare from "./pages/Compare";
import ResearchObject from "./pages/ResearchObject";

const pages = [
  { key: "research", label: "研究对象", icon: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 6 6" },
  { key: "backtests", label: "策略回测", icon: "M3 3v18h18M6 15l4-5 4 3 6-8" },
  { key: "review", label: "投资复盘", icon: "M4 3h16v18H4ZM8 7h8M8 12h8M8 17h5" },
  { key: "compare", label: "横向对比", icon: "M12 3v18M4 7h4v10H4ZM16 5h4v14h-4Z" },
  { key: "instruments", label: "标的配置", icon: "M3 6h18M3 12h18M3 18h18M8 4v4M16 10v4M10 16v4" },
  { key: "jobs", label: "定时任务", icon: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM12 6v6l4 2" },
];
function pageFromUrl() {
  const query = new URLSearchParams(location.search);
  const old = query.get("page");
  const routes: Record<string, { page: string; object?: string; tab?: string; dimension?: string }> = {
    market: { page: "research", object: `etf:${query.get("code") ?? "510500"}`, tab: "price" },
    "national-team": { page: "research", object: `etf:${query.get("code") ?? "510500"}`, tab: "funds" },
    "index-valuations": { page: "research", object: `index:${query.get("code") ?? "000905.SH"}`, tab: "valuation" },
    sentiment: { page: "compare", dimension: "sentiment" },
  };
  if (old && routes[old]) {
    Object.entries(routes[old]).forEach(([key, value]) => query.set(key, value));
    if (old === "sentiment" && query.get("category")) query.set("codes", query.get("category")!);
    history.replaceState(null, "", `?${query}`);
  }
  return pages.some((item) => item.key === query.get("page")) ? query.get("page")! : "research";
}
export default function App() {
  const [page, setPage] = useState(pageFromUrl);
  useEffect(() => { const changed = () => setPage(pageFromUrl()); window.addEventListener("popstate", changed); return () => window.removeEventListener("popstate", changed); }, []);
  function navigate(next: string) { const query = new URLSearchParams(location.search); query.set("page", next); history.pushState(null, "", `?${query}`); setPage(next); }
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
          {page === "backtests" ? (
            <Backtests theme={theme} />
          ) : page === "review" ? (
            <Review theme={theme} />
          ) : page === "compare" ? (
            <Compare theme={theme} />
          ) : page === "research" ? (
            <ResearchObject theme={theme} />
          ) : page === "instruments" ? (
            <Instruments />
          ) : (
            <Jobs initialTask="etf" />
          )}
        </main>
        <div className="workspace-footer">
          <span>投研工作台</span>
          <span>数据有来源，研究可追溯</span>
        </div>
      </div>
    </div>
  );
}
