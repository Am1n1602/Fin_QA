import React, { Fragment } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Home from "./pages/Home.jsx";
import CompaniesPage from "./pages/CompaniesPage.jsx";
import CompanyPage from "./pages/CompanyPage.jsx";
import RankingsPage from "./pages/RankingsPage.jsx";
import ResearchPage from "./pages/ResearchPage.jsx";
import QaPage from "./pages/QaPage.jsx";
import WakeGate from "./components/WakeGate.jsx";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true },
  { to: "/companies", label: "Companies" },
  { to: "/rankings", label: "Rankings" },
  { to: "/research", label: "Research" },
  { to: "/qa", label: "Financial QA" },
];

export default function App() {
  return (
    <WakeGate>
      <div className="app-shell">
        {/* WCAG 2.1 SC 2.4.1 (Bypass Blocks) */}
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        <header className="app-header">
          <div className="masthead-row">
            <div className="brand-block">
              <span className="brand">FIN&middot;QA v2</span>
              <span className="brand-tagline">Evidence Desk &mdash; NIFTY 50, every claim cited</span>
            </div>
          </div>
          <nav className="app-nav" aria-label="Primary">
            {NAV_ITEMS.map((item, i) => (
              <Fragment key={item.to}>
                {i > 0 && (
                  <span className="nav-divider" aria-hidden="true">
                    &middot;
                  </span>
                )}
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
