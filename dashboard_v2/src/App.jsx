import React from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Home from "./pages/Home.jsx";
import CompaniesPage from "./pages/CompaniesPage.jsx";
import CompanyPage from "./pages/CompanyPage.jsx";
import RankingsPage from "./pages/RankingsPage.jsx";
import ResearchPage from "./pages/ResearchPage.jsx";
import QaPage from "./pages/QaPage.jsx";
import WakeGate from "./components/WakeGate.jsx";
import { useTheme } from "./hooks/useTheme.js";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true },
  { to: "/companies", label: "Companies" },
  { to: "/rankings", label: "Rankings" },
  { to: "/research", label: "Research" },
  { to: "/qa", label: "Financial QA" },
];

export default function App() {
  const { theme, toggleTheme } = useTheme();
  return (
    <WakeGate>
      <div className="app-shell">
        {/* WCAG 2.1 SC 2.4.1 (Bypass Blocks) */}
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        <aside className="app-sidebar">
          <div className="brand-block">
            <span className="brand">
              FIN&middot;<em>QA</em> v2
            </span>
            <span className="brand-tagline">Evidence Desk &mdash; NIFTY 50, every claim cited</span>
          </div>
          <nav className="app-nav" aria-label="Primary">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => "nav-link" + (isActive ? " nav-link-active" : "")}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">
            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              {theme === "dark" ? "☀️ Light" : "\u{1F319} Dark"}
            </button>
          </div>
        </aside>

        <main className="app-main" id="main-content" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/companies" element={<CompaniesPage />} />
            <Route path="/companies/:ticker" element={<CompanyPage />} />
            <Route path="/rankings" element={<RankingsPage />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="/research/:ticker" element={<ResearchPage />} />
            <Route path="/qa" element={<QaPage />} />
            <Route path="*" element={<p>Page not found.</p>} />
          </Routes>
        </main>
      </div>
    </WakeGate>
  );
}
