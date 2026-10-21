"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useAdmin } from "./admin-provider";

const navigation = [
  { href: "/", label: "Overview", marker: "OV" },
  { href: "/college", label: "College setup", marker: "CL" },
  { href: "/enrollment", label: "Biometric enrollment", marker: "BE" },
  { href: "/sessions", label: "Sessions & jobs", marker: "SJ" },
  { href: "/people", label: "People", marker: "PE" },
  { href: "/attendance", label: "Attendance", marker: "AT" },
  { href: "/reviews", label: "Review queue", marker: "RQ" },
  { href: "/audit", label: "Audit log", marker: "AU" },
  { href: "/models", label: "Models & readiness", marker: "ML" },
];

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [settingsOpen, setSettingsOpen] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const { apiBase, setApiBase, apiKey, setApiKey, isConnected, connectionError, connect } = useAdmin();
  const current = navigation.find((item) => item.href === pathname) ?? navigation[0];

  async function handleConnect() {
    setConnecting(true);
    try {
      await connect();
    } catch {
      // The provider exposes the detailed, user-visible error.
    } finally {
      setConnecting(false);
    }
  }

  return (
    <div className="app-frame">
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="FRS Admin overview">
          <span className="brand-mark">F</span>
          <span><strong>FRS</strong><small>ATTENDANCE PLATFORM</small></span>
        </Link>

        <div className="workspace-label">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <Link key={item.href} href={item.href} className={pathname === item.href ? "nav-link active" : "nav-link"}>
              <span className="nav-marker">{item.marker}</span>
              <span>{item.label}</span>
              {pathname === item.href ? <span className="nav-active-dot" /> : null}
            </Link>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="connection-summary">
            <span className={isConnected ? "status-dot online" : "status-dot"} />
            <span><strong>{isConnected ? "Admin API connected" : "Not connected"}</strong><small>Credential held in memory</small></span>
          </div>
          <button className="settings-toggle" type="button" onClick={() => setSettingsOpen((value) => !value)} aria-expanded={settingsOpen}>
            <span>API connection</span><span>{settingsOpen ? "−" : "+"}</span>
          </button>
          {settingsOpen ? (
            <div className="connection-form">
              <label htmlFor="api-base">Backend URL</label>
              <input id="api-base" value={apiBase} onChange={(event) => setApiBase(event.target.value)} autoComplete="url" spellCheck={false} />
              <label htmlFor="admin-key">Administrator bearer key</label>
              <input id="admin-key" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" />
              <button className="button button-primary connect-button" type="button" disabled={connecting} onClick={() => void handleConnect()}>
                {connecting ? "Connecting…" : isConnected ? "Reconnect" : "Connect"}
              </button>
              {connectionError ? <p className="connection-error" role="alert">{connectionError}</p> : null}
              <p className="field-help">Never use a public environment variable for the key. Reloading this page clears it.</p>
            </div>
          ) : null}
          <div className="sidebar-footnote">FRS · development console<br />Not approved for live attendance</div>
        </div>
      </aside>

      <main className="main-column" id="main-content">
        <header className="topbar">
          <div><div className="eyebrow">FACE RECOGNITION SYSTEM</div><h1>{current.label}</h1></div>
          <div className="topbar-meta"><span className={isConnected ? "pill pill-success" : "pill pill-muted"}><span className="status-dot" />{isConnected ? "API authenticated" : "Read-only health"}</span><span className="version-label">FRS PLATFORM · INTEGRATED</span></div>
        </header>
        <div className="page-content">{children}</div>
        <footer className="main-footer"><span>FRS Admin · Next.js</span><span>Biometric decisions require real models and site validation.</span></footer>
      </main>
    </div>
  );
}
