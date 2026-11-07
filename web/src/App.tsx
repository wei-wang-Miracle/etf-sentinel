import { useEffect, useState } from "react";
import Instruments from "./pages/Instruments";
import Jobs from "./pages/Jobs";
import Backtests from "./pages/Backtests";
import Review from "./pages/Review";
import Compare from "./pages/Compare";
import ResearchObject from "./pages/ResearchObject";

const pages = [
  { key: "research", label: "研究对象", icon: "⌕" },
  { key: "backtests", label: "策略回测", icon: "⌁" },
  { key: "review", label: "投资复盘", icon: "▦" },
  { key: "compare", label: "横向对比", icon: "≋" },
  { key: "instruments", label: "标的配置", icon: "≡" },
  { key: "jobs", label: "定时任务", icon: "◷" },
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
        >
          {collapsed ? "»" : "«"}
        </button>
        {!collapsed && <div className="nav-label">研究工作台</div>}
        <nav aria-label="主导航">
          {pages.map((p) => (
            <button
              key={p.key}
              className={`nav-item ${page === p.key ? "active" : ""}`}
              aria-current={page === p.key ? "page" : undefined}
              title={p.label}
              onClick={() => navigate(p.key)}
            >
              <span aria-hidden="true">{p.icon}</span>
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
