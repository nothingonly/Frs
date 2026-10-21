"use client";

/* eslint react-hooks/set-state-in-effect: off -- These effects initiate external HTTP reads; state changes occur in async response/error handlers. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAdmin, type HealthPayload, type ModelPayload } from "@/components/admin-provider";

type AdminStats = {
  departments_count: number;
  classes_count: number;
  students_count: number;
  biometrics_enrolled_count: number;
  open_sessions_count: number;
  attendance_today_count: number;
  pending_reviews_count: number;
};

function describe(value: unknown) {
  if (value === null || value === undefined) return "Not reported";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export default function OverviewPage() {
  const { isConnected, requestJson, getHealth } = useAdmin();
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [modelCount, setModelCount] = useState<number | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await getHealth());
      setHealthError(null);
    } catch (error) {
      setHealth(null);
      setHealthError(error instanceof Error ? error.message : "Health check failed.");
    }
  }, [getHealth]);

  const refreshAdminData = useCallback(async () => {
    if (!isConnected) return;
    setLoading(true);
    setDataError(null);
    const results = await Promise.allSettled([
      requestJson<AdminStats>("/api/v1/admin/stats"),
      requestJson<ModelPayload>("/api/v1/admin/models"),
    ]);
    if (results[0].status === "fulfilled") {
      setStats(results[0].value);
    } else {
      setDataError(results[0].reason instanceof Error ? results[0].reason.message : "Could not load stats.");
    }
    if (results[1].status === "fulfilled") {
      setModelCount(results[1].value.registry.length);
    }
    setLoading(false);
  }, [isConnected, requestJson]);

  useEffect(() => { void refreshHealth(); }, [refreshHealth]);
  useEffect(() => { if (isConnected) void refreshAdminData(); }, [isConnected, refreshAdminData]);

  const ready = health?.ready_for_attendance === true;
  const databaseStatus = describe(health?.database);

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">INTEGRATED FRS PLATFORM</div>
          <h2>Administrative Dashboard</h2>
          <p>Real-time metrics, class session tracking, biometric readiness, and attendance exception management.</p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => { void refreshHealth(); void refreshAdminData(); }}
          disabled={loading}
        >
          {loading ? "Loading…" : "↻ Refresh metrics"}
        </button>
      </section>

      {healthError ? (
        <div className="notice notice-error" role="alert">
          <strong>Backend health unavailable</strong>
          <span>{healthError}</span>
        </div>
      ) : null}
      {dataError ? (
        <div className="notice notice-error" role="alert">
          <strong>Some metrics could not be loaded</strong>
          <span>{dataError}</span>
        </div>
      ) : null}

      <section className="stat-grid" aria-label="System metrics">
        <article className="stat-card">
          <div className="stat-top"><span>Active Students</span><span className="stat-icon">01</span></div>
          <strong className="stat-value">{stats ? stats.students_count : "—"}</strong>
          <span className="stat-caption">{stats ? `${stats.biometrics_enrolled_count} biometric enrolled` : "Connect admin API"}</span>
        </article>
        <article className="stat-card">
          <div className="stat-top"><span>Classes &amp; Depts</span><span className="stat-icon">02</span></div>
          <strong className="stat-value">{stats ? `${stats.classes_count} / ${stats.departments_count}` : "—"}</strong>
          <span className="stat-caption">Active class sections &amp; departments</span>
        </article>
        <article className="stat-card">
          <div className="stat-top"><span>Today&apos;s Attendance</span><span className="stat-icon">03</span></div>
          <strong className="stat-value">{stats ? stats.attendance_today_count : "—"}</strong>
          <span className="stat-caption">{stats ? `${stats.open_sessions_count} open sessions` : "Real-time records"}</span>
        </article>
        <article className="stat-card">
          <div className="stat-top"><span>Review Queue</span><span className="stat-icon">04</span></div>
          <strong className="stat-value" style={{ color: stats && stats.pending_reviews_count > 0 ? "var(--color-warning, #f59e0b)" : "inherit" }}>
            {stats ? stats.pending_reviews_count : "—"}
          </strong>
          <span className="stat-caption">Unresolved capture exceptions</span>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="panel-heading">
            <div><span className="eyebrow">RUNTIME GATE</span><h3>Recognition readiness</h3></div>
            <span className={ready ? "pill pill-success" : "pill pill-warning"}>
              {ready ? "Ready by backend policy" : "Not ready"}
            </span>
          </div>
          <p className="panel-description">
            This indicator reflects the backend&apos;s own readiness response. Biometric decisions strictly scope comparisons to the active class roster.
          </p>
          <div className="readiness-row">
            <span>API &amp; Database</span>
            <strong>{databaseStatus}</strong>
          </div>
          <div className="readiness-row">
            <span>Threshold calibration</span>
            <strong>{describe(health?.threshold_status)}</strong>
          </div>
          <div className="readiness-row">
            <span>Model registry entries</span>
            <strong>{modelCount === null ? "Connect admin API" : `${modelCount} registered`}</strong>
          </div>
          <div className="readiness-row">
            <span>Admin connection</span>
            <strong>{isConnected ? "Authenticated (In-Memory)" : "Not connected"}</strong>
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div><span className="eyebrow">SYSTEM ARCHITECTURE</span><h3>Integrated Modules</h3></div>
            <span className="pill pill-success">Operational</span>
          </div>
          <p className="panel-description">All core enterprise capabilities are integrated into the production architecture:</p>
          <div className="roadmap-item">
            <span className="roadmap-number">✓</span>
            <div><strong>College hierarchy</strong><small>Departments, academic years, sections, classes, and student enrollments</small></div>
            <span className="status-label" style={{ color: "var(--color-success, #10b981)" }}>Active</span>
          </div>
          <div className="roadmap-item">
            <span className="roadmap-number">✓</span>
            <div><strong>Biometric enrollment</strong><small>Multi-frame capture, deterministic quality checks, and consent auditing</small></div>
            <span className="status-label" style={{ color: "var(--color-success, #10b981)" }}>Active</span>
          </div>
          <div className="roadmap-item">
            <span className="roadmap-number">✓</span>
            <div><strong>Asynchronous capture jobs</strong><small>Persistent SQLite/PostgreSQL queue, worker timeout recovery, and retry bounds</small></div>
            <span className="status-label" style={{ color: "var(--color-success, #10b981)" }}>Active</span>
          </div>
          <div className="roadmap-item">
            <span className="roadmap-number">✓</span>
            <div><strong>Secure media storage</strong><small>Authenticated private Cloudinary storage with short-lived signed URLs</small></div>
            <span className="status-label" style={{ color: "var(--color-success, #10b981)" }}>Active</span>
          </div>
        </article>
      </section>

      <section className="panel table-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">NAVIGATION</span><h3>Quick management actions</h3></div>
          <span className="panel-note">{isConnected ? "Connected to live API" : "Connect using the sidebar"}</span>
        </div>
        <div className="resource-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
          <Link href="/college" className="resource-card">
            <span className="resource-symbol">CL</span>
            <span><strong>College setup</strong><small>Manage departments, academic years, and classes</small></span>
            <span className="resource-arrow">↗</span>
          </Link>
          <Link href="/enrollment" className="resource-card">
            <span className="resource-symbol">BE</span>
            <span><strong>Biometric enrollment</strong><small>Register student faces with multi-frame consent</small></span>
            <span className="resource-arrow">↗</span>
          </Link>
          <Link href="/sessions" className="resource-card">
            <span className="resource-symbol">SJ</span>
            <span><strong>Sessions &amp; jobs</strong><small>Open/close attendance sessions &amp; track batch jobs</small></span>
            <span className="resource-arrow">↗</span>
          </Link>
          <Link href="/attendance" className="resource-card">
            <span className="resource-symbol">AT</span>
            <span><strong>Attendance records</strong><small>Inspect punches, manual entries, and CSV export</small></span>
            <span className="resource-arrow">↗</span>
          </Link>
          <Link href="/reviews" className="resource-card">
            <span className="resource-symbol">RQ</span>
            <span><strong>Review queue</strong><small>Resolve ambiguous or rejected captures with audit</small></span>
            <span className="resource-arrow">↗</span>
          </Link>
          <Link href="/audit" className="resource-card">
            <span className="resource-symbol">AU</span>
            <span><strong>Audit log</strong><small>Inspect immutable evidence and decision trails</small></span>
            <span className="resource-arrow">↗</span>
          </Link>
        </div>
      </section>
    </>
  );
}
