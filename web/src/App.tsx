import { useState } from "react";
import Instruments from "./pages/Instruments";
import Jobs from "./pages/Jobs";
import Sentiment from "./pages/Sentiment";
import Market from "./pages/Market";
import NationalTeam from "./pages/NationalTeam";

const pages = [
  { key: "market", label: "行情展示", icon: "▥" },
  { key: "sentiment", label: "行业恐贪", icon: "∿" },
  { key: "national-team", label: "国家队持仓", icon: "▤" },
  { key: "instruments", label: "标的配置", icon: "≡" },
  { key: "jobs", label: "定时任务", icon: "◷" },
];
export default function App() {
  const [jobTask, setJobTask] = useState("etf");
  const [page, setPage] = useState("market");
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
          <span className="brand-mark">L</span>
          {!collapsed && (
            <div>
              <strong>Ledger Terminal</strong>
              <span>ETF Sentinel</span>
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
              onClick={() => setPage(p.key)}
            >
              <span aria-hidden="true">{p.icon}</span>
              {!collapsed && p.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          {!collapsed && (
            <>
              <strong>个人 ETF 投研</strong>
              <span>历史数据 · 日频研究</span>
            </>
          )}
          <span className="mono">v0.3</span>
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
          {page === "market" ? (
            <Market
              theme={theme}
              goJobs={() => {
                setJobTask("etf");
                setPage("jobs");
              }}
            />
          ) : page === "sentiment" ? (
            <Sentiment
              theme={theme}
              goJobs={() => {
                setJobTask("sentiment");
                setPage("jobs");
              }}
            />
          ) : page === "national-team" ? (
            <NationalTeam theme={theme} goJobs={() => {
              setJobTask("national-team");
              setPage("jobs");
            }} />
          ) : page === "instruments" ? (
            <Instruments />
          ) : (
            <Jobs initialTask={jobTask} />
          )}
        </main>
        <div className="workspace-footer">
          <span>Ledger Terminal</span>
          <span>数据有来源，研究可追溯</span>
        </div>
      </div>
    </div>
  );
}
