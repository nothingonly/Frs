"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAdmin, type AttendanceRecord, type HealthPayload, type ListPayload, type ModelPayload, type PersonRecord } from "@/components/admin-provider";

function describe(value: unknown) {
  if (value === null || value === undefined) return "Not reported";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export default function OverviewPage() {
  const { isConnected, requestJson, getHealth } = useAdmin();
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [peopleCount, setPeopleCount] = useState<number | null>(null);
  const [attendanceCount, setAttendanceCount] = useState<number | null>(null);
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
      requestJson<ListPayload<PersonRecord>>("/api/v1/admin/people?limit=100"),
      requestJson<ListPayload<AttendanceRecord>>("/api/v1/admin/attendance?limit=100"),
      requestJson<ModelPayload>("/api/v1/admin/models"),
    ]);
    if (results[0].status === "fulfilled") setPeopleCount(results[0].value.items.length);
    else setDataError(results[0].reason instanceof Error ? results[0].reason.message : "Could not load people.");
    if (results[1].status === "fulfilled") setAttendanceCount(results[1].value.items.length);
    else setDataError(results[1].reason instanceof Error ? results[1].reason.message : "Could not load attendance.");
    if (results[2].status === "fulfilled") setModelCount(results[2].value.registry.length);
    else setDataError(results[2].reason instanceof Error ? results[2].reason.message : "Could not load models.");
    setLoading(false);
  }, [isConnected, requestJson]);

  useEffect(() => { void refreshHealth(); }, [refreshHealth]);
  useEffect(() => { if (isConnected) void refreshAdminData(); }, [isConnected, refreshAdminData]);

  const ready = health?.ready_for_attendance === true;
  const databaseStatus = describe(health?.database);

  return (
    <>
      <section className="welcome-row">
        <div><div className="eyebrow">SYSTEM SNAPSHOT</div><h2>Welcome to FRS</h2><p>Monitor the current backend and review records already stored by the service.</p></div>
        <button className="button button-secondary" type="button" onClick={() => { void refreshHealth(); void refreshAdminData(); }} disabled={loading}>↻ Refresh data</button>
      </section>

      {healthError ? <div className="notice notice-error" role="alert"><strong>Backend health unavailable</strong><span>{healthError}</span></div> : null}
      {dataError ? <div className="notice notice-error" role="alert"><strong>Some admin data could not be loaded</strong><span>{dataError}</span></div> : null}

      <section className="stat-grid" aria-label="System metrics">
        <article className="stat-card"><div className="stat-top"><span>API status</span><span className="stat-icon">01</span></div><strong className="stat-value">{health ? describe(health.status ?? "Responding") : "—"}</strong><span className="stat-caption">{health ? "Live health endpoint" : "No response"}</span></article>
        <article className="stat-card"><div className="stat-top"><span>Database health</span><span className="stat-icon">02</span></div><strong className="stat-value stat-value-compact">{health ? databaseStatus : "—"}</strong><span className="stat-caption">Reported by the backend</span></article>
        <article className="stat-card"><div className="stat-top"><span>People returned</span><span className="stat-icon">03</span></div><strong className="stat-value">{peopleCount === null ? "—" : peopleCount}</strong><span className="stat-caption">Latest response, capped at 100</span></article>
        <article className="stat-card"><div className="stat-top"><span>Attendance returned</span><span className="stat-icon">04</span></div><strong className="stat-value">{attendanceCount === null ? "—" : attendanceCount}</strong><span className="stat-caption">Latest response, capped at 100</span></article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="panel-heading"><div><span className="eyebrow">RUNTIME GATE</span><h3>Recognition readiness</h3></div><span className={ready ? "pill pill-success" : "pill pill-warning"}>{ready ? "Ready by backend policy" : "Not ready"}</span></div>
          <p className="panel-description">This indicator reflects the backend's own readiness response. A healthy HTTP process is not proof of accurate or safe biometric decisions.</p>
          <div className="readiness-row"><span>Threshold calibration</span><strong>{describe(health?.threshold_status)}</strong></div>
          <div className="readiness-row"><span>Model registry entries</span><strong>{modelCount === null ? "Connect admin API" : modelCount}</strong></div>
          <div className="readiness-row"><span>Admin API connection</span><strong>{isConnected ? "Authenticated" : "Not connected"}</strong></div>
        </article>
        <article className="panel roadmap-panel">
          <div className="eyebrow">PRODUCT ROADMAP</div><h3>Next product capabilities</h3>
          <p className="panel-description">The current backend is employee/department-oriented. College class management and image storage will be built against a proper data schema—not simulated in this UI.</p>
          <div className="roadmap-item"><span className="roadmap-number">02</span><div><strong>College hierarchy</strong><small>Departments, years, sections, classes and student enrollment</small></div><span className="status-label">Planned</span></div>
          <div className="roadmap-item"><span className="roadmap-number">03</span><div><strong>Image management</strong><small>Private Cloudinary uploads and retention rules</small></div><span className="status-label">Planned</span></div>
          <div className="roadmap-item"><span className="roadmap-number">04</span><div><strong>Attendance jobs</strong><small>Persistent batch queue and worker recovery</small></div><span className="status-label">Planned</span></div>
        </article>
      </section>

      <section className="panel table-panel">
        <div className="panel-heading"><div><span className="eyebrow">QUICK ACCESS</span><h3>Admin resources</h3></div><span className="panel-note">{isConnected ? "Live backend data" : "Connect using the sidebar"}</span></div>
        <div className="resource-grid">
          <Link href="/people" className="resource-card"><span className="resource-symbol">PE</span><span><strong>People directory</strong><small>Review and deactivate/reactivate person records</small></span><span className="resource-arrow">↗</span></Link>
          <Link href="/attendance" className="resource-card"><span className="resource-symbol">AT</span><span><strong>Attendance events</strong><small>Inspect recorded events and decision scores</small></span><span className="resource-arrow">↗</span></Link>
          <Link href="/models" className="resource-card"><span className="resource-symbol">ML</span><span><strong>Model registry</strong><small>Review artifact metadata and runtime status</small></span><span className="resource-arrow">↗</span></Link>
        </div>
      </section>
    </>
  );
}
