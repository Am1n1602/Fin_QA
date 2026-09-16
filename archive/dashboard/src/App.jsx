import React, { Fragment } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Home from "./pages/Home.jsx";
import CompanyPage from "./pages/CompanyPage.jsx";
import RankingsPage from "./pages/RankingsPage.jsx";
import QaPage from "./pages/QaPage.jsx";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true },
  { to: "/rankings", label: "Rankings" },
  { to: "/qa", label: "Research Desk" },
];

export default function App() {
  return (
    <div className="app-shell">
      {/* WCAG 2.1 SC 2.4.1 (Bypass Blocks, A) -- lets keyboard/screen-reader
          users jump straight past the masthead + nav to the page content
          instead of tabbing through both on every single page. */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <header className="app-header">
        <div className="masthead-row">
          <div className="brand-block">
            <span className="brand">FIN&middot;QA</span>
            <span className="brand-tagline">Equity Research Terminal &mdash; NIFTY 50</span>
          </div>
        </div>
        <nav className="app-nav" aria-label="Primary">
          {NAV_ITEMS.map((item, i) => (
            <Fragment key={item.to}>
              {i > 0 && <span className="nav-divider" aria-hidden="true">&middot;</span>}
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) => "nav-link" + (isActive ? " nav-link-active" : "")}
              >
                {item.label}
              </NavLink>
            </Fragment>
          ))}
        </nav>
      </header>
      
      <main className="app-main" id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/companies/:symbol" element={<CompanyPage />} />
          <Route path="/rankings" element={<RankingsPage />} />
          <Route path="/qa" element={<QaPage />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}