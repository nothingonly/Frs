"use client";

/* eslint react-hooks/set-state-in-effect: off -- Effects initiate external HTTP reads; state changes occur in async response handlers. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAdmin } from "@/components/admin-provider";

type AuditRecord = {
  audit_id: string;
  session_id: string;
  occurred_at: string;
  actor_type: string;
  actor_id: string;
  action: string;
  decision_state: string;
  reason_codes: string[];
  evidence: Record<string, unknown>;
};

type Items<T> = { items: T[] };

export default function AuditLogPage() {
  const { isConnected, requestJson } = useAdmin();
  const [events, setEvents] = useState<AuditRecord[]>([]);
  const [filter, setFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [selectedAudit, setSelectedAudit] = useState<AuditRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isConnected) return;
    setLoading(true);
    setError(null);
    try {
      const url = actionFilter.trim()
        ? `/api/v1/admin/audit?limit=200&action=${encodeURIComponent(actionFilter.trim())}`
        : "/api/v1/admin/audit?limit=200";
      const payload = await requestJson<Items<AuditRecord>>(url);
      setEvents(payload.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load audit log.");
    } finally {
      setLoading(false);
    }
  }, [isConnected, requestJson, actionFilter]);

  useEffect(() => {
    if (isConnected) void refresh();
  }, [isConnected, refresh]);

  const visibleEvents = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return events;
    return events.filter((event) =>
      [event.audit_id, event.session_id, event.actor_id, event.action, event.decision_state, ...event.reason_codes].some(
        (val) => val.toLowerCase().includes(query),
      ),
    );
  }, [events, filter]);

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">SECURITY &amp; COMPLIANCE</div>
          <h2>Immutable audit log</h2>
          <p>
            Cryptographically controlled records of administrative changes, enrollment events, biometric decisions, and session state transitions.
          </p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => void refresh()}
          disabled={!isConnected || loading}
        >
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </section>

      {!isConnected ? (
        <div className="notice notice-info">
          <strong>Admin connection required</strong>
          <span>Connect using an administrator bearer key in the sidebar to inspect protected audit events.</span>
        </div>
      ) : null}

      {error ? (
        <div className="notice notice-error" role="alert">
          <strong>Request failed</strong>
          <span>{error}</span>
        </div>
      ) : null}

      <section className="panel table-panel">
        <div className="table-toolbar">
          <div>
            <h3>Audit records</h3>
            <p>{visibleEvents.length} records shown · logs contain no raw face imagery or embeddings</p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <label className="search-field">
              <span>Action type</span>
              <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
                <option value="">All actions</option>
                <option value="biometrics.enroll">biometrics.enroll</option>
                <option value="attendance.identify">attendance.identify</option>
                <option value="attendance.verify">attendance.verify</option>
                <option value="attendance_session.create">attendance_session.create</option>
                <option value="attendance_session.close">attendance_session.close</option>
                <option value="student.create">student.create</option>
                <option value="department.create">department.create</option>
              </select>
            </label>
            <label className="search-field">
              <span>Search</span>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="ID, actor, reason code"
              />
            </label>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Action</th>
                <th>Decision / State</th>
                <th>Actor</th>
                <th>Reason codes</th>
                <th>Audit ID</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {visibleEvents.map((event) => (
                <tr key={event.audit_id}>
                  <td>
                    <small>{new Date(event.occurred_at).toLocaleString()}</small>
                  </td>
                  <td>
                    <strong><code>{event.action}</code></strong>
                  </td>
                  <td>
                    <span
                      className={
                        event.decision_state === "ACCEPT" ||
                        event.decision_state === "ENROLLED" ||
                        event.decision_state === "CREATED" ||
                        event.decision_state === "OPEN"
                          ? "pill pill-success"
                          : event.decision_state.includes("REJECT") || event.decision_state === "REVOKED"
                            ? "pill pill-warning"
                            : "pill pill-muted"
                      }
                    >
                      {event.decision_state}
                    </span>
                  </td>
                  <td>
                    <small>
                      {event.actor_type}: <strong>{event.actor_id}</strong>
                    </small>
                  </td>
                  <td>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "2px" }}>
                      {event.reason_codes.map((rc, i) => (
                        <span key={i} className="class-chip" style={{ fontSize: "10px" }}>
                          {rc}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <code>{event.audit_id.slice(0, 8)}</code>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button button-small button-secondary"
                      onClick={() => setSelectedAudit(event)}
                    >
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
              {visibleEvents.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-state">
                      <strong>{loading ? "Loading audit events…" : "No matching audit records"}</strong>
                      <span>Audit events are written on every state transition, enrollment, and attendance decision.</span>
                    </div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {selectedAudit ? (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "1rem",
          }}
          onClick={() => setSelectedAudit(null)}
        >
          <div
            style={{
              background: "var(--bg-panel, #ffffff)",
              color: "var(--text-primary, #0f172a)",
              borderRadius: "10px",
              padding: "1.5rem",
              maxWidth: "680px",
              width: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <div>
                <h3 style={{ margin: 0 }}>Audit Evidence Details</h3>
                <small style={{ color: "var(--text-secondary)" }}>
                  ID: <code>{selectedAudit.audit_id}</code> · Session: <code>{selectedAudit.session_id}</code>
                </small>
              </div>
              <button
                type="button"
                className="button button-small button-secondary"
                onClick={() => setSelectedAudit(null)}
              >
                ✕ Close
              </button>
            </div>

            <div style={{ marginBottom: "1rem" }}>
              <strong>Action:</strong> <code>{selectedAudit.action}</code> · <strong>Decision State:</strong>{" "}
              <code>{selectedAudit.decision_state}</code> · <strong>Actor:</strong> {selectedAudit.actor_type}:{" "}
              <code>{selectedAudit.actor_id}</code>
            </div>

            <div style={{ marginBottom: "1rem" }}>
              <strong>Reason Codes:</strong>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginTop: "4px" }}>
                {selectedAudit.reason_codes.map((rc, i) => (
                  <span key={i} className="pill pill-success" style={{ fontSize: "11px" }}>
                    {rc}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <strong>Structured Evidence (sanitized):</strong>
              <pre
                style={{
                  background: "var(--code-bg, #0f172a)",
                  color: "#e2e8f0",
                  padding: "1rem",
                  borderRadius: "6px",
                  fontSize: "12px",
                  overflowX: "auto",
                  marginTop: "0.5rem",
                }}
              >
                {JSON.stringify(selectedAudit.evidence, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      ) : null}

      <p className="compliance-note">
        Audit records provide non-repudiation and evidence trails for all administrative actions and biometric attendance decisions. Raw face images, biometric embeddings, and secrets are permanently excluded from audit logs.
      </p>
    </>
  );
}
