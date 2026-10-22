"use client";

/* eslint react-hooks/set-state-in-effect: off -- These effects initiate external HTTP reads; state changes occur in async response/error handlers. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAdmin, type AttendanceRecord, type ListPayload } from "@/components/admin-provider";

export default function AttendancePage() {
  const { isConnected, requestJson } = useAdmin();
  const [events, setEvents] = useState<AttendanceRecord[]>([]);
  const [filter, setFilter] = useState("");
  const [sessionFilter, setSessionFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Correction Modal State
  const [correctionTarget, setCorrectionTarget] = useState<AttendanceRecord | null>(null);
  const [corrPunchType, setCorrPunchType] = useState<string>("CHECK_IN");
  const [corrRevoke, setCorrRevoke] = useState(false);
  const [corrReasonCode, setCorrReasonCode] = useState("FACULTY_CORRECTION");
  const [corrJustification, setCorrJustification] = useState("");
  const [corrSubmitting, setCorrSubmitting] = useState(false);

  // Manual Entry Modal State
  const [manualEntryOpen, setManualEntryOpen] = useState(false);
  const [manualStudentId, setManualStudentId] = useState("");
  const [manualSessionId, setManualSessionId] = useState("");
  const [manualPunchType, setManualPunchType] = useState<string>("CHECK_IN");
  const [manualReasonCode, setManualReasonCode] = useState("MANUAL_FACULTY_OVERRIDE");
  const [manualJustification, setManualJustification] = useState("");
  const [manualSubmitting, setManualSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = sessionFilter.trim()
        ? `/api/v1/admin/attendance?limit=200&attendance_session_id=${encodeURIComponent(sessionFilter.trim())}`
        : "/api/v1/admin/attendance?limit=200";
      const payload = await requestJson<ListPayload<AttendanceRecord>>(url);
      setEvents(payload.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load attendance events.");
    } finally {
      setLoading(false);
    }
  }, [requestJson, sessionFilter]);

  useEffect(() => {
    if (isConnected) void refresh();
  }, [isConnected, refresh]);

  const visibleEvents = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return events;
    return events.filter((event) =>
      [event.employee_id, event.punch_type, event.client_device_id, event.evidence_id, event.attendance_session_id || ""].some(
        (value) => value.toLowerCase().includes(query),
      ),
    );
  }, [events, filter]);

  function exportCsv() {
    if (visibleEvents.length === 0) return;
    const headers = [
      "Attendance ID",
      "Student / Employee ID",
      "Punch Type",
      "Timestamp UTC",
      "Similarity Score",
      "Threshold",
      "Evidence Type",
      "Device ID",
      "Session ID",
      "Audit Evidence ID",
    ];
    const rows = visibleEvents.map((e) => [
      e.attendance_id,
      e.employee_id,
      e.punch_type,
      e.timestamp,
      e.similarity_score == null ? "N/A" : Number(e.similarity_score).toFixed(4),
      e.threshold == null ? "N/A" : Number(e.threshold).toFixed(4),
      e.evidence_type ?? "BIOMETRIC",
      e.client_device_id,
      e.attendance_session_id || "",
      e.evidence_id,
    ]);
    const csvContent = [
      headers.join(","),
      ...rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")),
    ].join("\r\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `frs-attendance-report-${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function openCorrection(record: AttendanceRecord) {
    setCorrectionTarget(record);
    setCorrPunchType(record.punch_type === "CHECK_IN" ? "CHECK_OUT" : "CHECK_IN");
    setCorrRevoke(false);
    setCorrReasonCode("FACULTY_CORRECTION");
    setCorrJustification("");
    setError(null);
  }

  async function handleCorrectionSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!correctionTarget) return;
    if (corrJustification.trim().length < 5) {
      setError("Justification must be at least 5 characters.");
      return;
    }
    setCorrSubmitting(true);
    setError(null);
    try {
      await requestJson(`/api/v1/admin/attendance/${encodeURIComponent(correctionTarget.attendance_id)}/correct`, {
        method: "POST",
        body: JSON.stringify({
          punch_type: corrRevoke ? null : corrPunchType,
          revoke: corrRevoke,
          reason_code: corrReasonCode,
          justification: corrJustification.trim(),
        }),
      });
      setSuccessMsg(
        corrRevoke
          ? `Attendance record ${correctionTarget.attendance_id.slice(0, 8)} revoked successfully.`
          : `Attendance record ${correctionTarget.attendance_id.slice(0, 8)} punch updated to ${corrPunchType}.`
      );
      setCorrectionTarget(null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to correct attendance record.");
    } finally {
      setCorrSubmitting(false);
    }
  }

  async function handleManualEntrySubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!manualStudentId.trim() || !manualSessionId.trim()) {
      setError("Student ID and Session ID are both required.");
      return;
    }
    if (manualJustification.trim().length < 5) {
      setError("Justification must be at least 5 characters.");
      return;
    }
    setManualSubmitting(true);
    setError(null);
    try {
      await requestJson("/api/v1/admin/attendance/manual-entry", {
        method: "POST",
        body: JSON.stringify({
          student_id: manualStudentId.trim(),
          attendance_session_id: manualSessionId.trim(),
          punch_type: manualPunchType,
          reason_code: manualReasonCode,
          justification: manualJustification.trim(),
        }),
      });
      setSuccessMsg(`Manual attendance entry recorded for student ${manualStudentId.trim()}.`);
      setManualEntryOpen(false);
      setManualStudentId("");
      setManualSessionId("");
      setManualJustification("");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to record manual attendance entry.");
    } finally {
      setManualSubmitting(false);
    }
  }

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">ATTENDANCE AUDIT &amp; REPORTING</div>
          <h2>Attendance events</h2>
          <p>Review persisted backend events, verify similarity/threshold evidence, correct records, or export approved reports.</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button
            className="button button-primary"
            type="button"
            onClick={() => setManualEntryOpen(true)}
            disabled={!isConnected}
          >
            + Manual attendance
          </button>
          <button
            className="button button-secondary"
            type="button"
            onClick={exportCsv}
            disabled={!isConnected || visibleEvents.length === 0}
          >
            Export report (CSV)
          </button>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => void refresh()}
            disabled={!isConnected || loading}
          >
            {loading ? "Loading…" : "↻ Refresh"}
          </button>
        </div>
      </section>

      {!isConnected ? (
        <div className="notice notice-info">
          <strong>Admin connection required</strong>
          <span>Enter a valid administrator bearer key in the sidebar to load protected attendance events.</span>
        </div>
      ) : null}

      {error ? (
        <div className="notice notice-error" role="alert">
          <strong>Notice</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {successMsg ? (
        <div className="notice notice-success" role="status">
          <strong>Action completed</strong>
          <span>{successMsg}</span>
        </div>
      ) : null}

      <section className="panel table-panel">
        <div className="table-toolbar">
          <div>
            <h3>Recorded events</h3>
            <p>{visibleEvents.length} records shown · latest response capped at 200</p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <label className="search-field">
              <span>Filter by session ID</span>
              <input
                value={sessionFilter}
                onChange={(event) => setSessionFilter(event.target.value)}
                placeholder="Session UUID"
              />
            </label>
            <label className="search-field">
              <span>Search</span>
              <input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Student, punch or device"
              />
            </label>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Person / ID</th>
                <th>Event</th>
                <th>Timestamp</th>
                <th>Similarity</th>
                <th>Threshold</th>
                <th>Device</th>
                <th>Session</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {visibleEvents.map((event) => (
                <tr key={event.attendance_id}>
                  <td>
                    <strong>{event.employee_id}</strong>
                    <small className="cell-subtext">{event.attendance_id.slice(0, 8)}</small>
                  </td>
                  <td>
                    <span className="event-pill">{event.punch_type}</span>
                  </td>
                  <td>{new Date(event.timestamp).toLocaleString()}</td>
                  <td className="numeric-cell">{event.similarity_score == null ? "N/A" : Number(event.similarity_score).toFixed(4)}</td>
                  <td className="numeric-cell">{event.threshold == null ? "N/A" : Number(event.threshold).toFixed(4)}</td>
                  <td><span className="event-pill">{event.evidence_type ?? "BIOMETRIC"}</span></td>
                  <td>{event.client_device_id}</td>
                  <td>
                    {event.attendance_session_id ? (
                      <code>{event.attendance_session_id.slice(0, 8)}</code>
                    ) : (
                      <span className="cell-subtext">Legacy (Unscoped)</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="button button-small button-secondary"
                      type="button"
                      onClick={() => openCorrection(event)}
                    >
                      Correct / Revoke
                    </button>
                  </td>
                </tr>
              ))}
              {visibleEvents.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <div className="empty-state">
                      <strong>{loading ? "Loading attendance…" : filter ? "No matching events" : "No attendance events to display"}</strong>
                      <span>{isConnected ? "The backend returned no matching attendance events." : "Connect to the admin API to load real records."}</span>
                    </div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {/* Correction Modal */}
      {correctionTarget ? (
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
          onClick={() => setCorrectionTarget(null)}
        >
          <div
            style={{
              background: "var(--bg-panel, #ffffff)",
              color: "var(--text-primary, #0f172a)",
              borderRadius: "10px",
              padding: "1.5rem",
              maxWidth: "520px",
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <div>
                <h3 style={{ margin: 0 }}>Correct Attendance Record</h3>
                <small style={{ color: "var(--text-secondary)" }}>
                  ID: <code>{correctionTarget.attendance_id}</code> · Student: <strong>{correctionTarget.employee_id}</strong>
                </small>
              </div>
              <button
                type="button"
                className="button button-small button-secondary"
                onClick={() => setCorrectionTarget(null)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCorrectionSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={corrRevoke}
                    onChange={(e) => setCorrRevoke(e.target.checked)}
                  />
                  <strong style={{ color: corrRevoke ? "var(--color-danger, #ef4444)" : "inherit" }}>
                    Revoke attendance (delete record)
                  </strong>
                </label>
                <small style={{ color: "var(--text-secondary)", display: "block", marginTop: "0.25rem" }}>
                  If checked, the record will be completely removed with a permanent audit entry.
                </small>
              </div>

              {!corrRevoke ? (
                <div>
                  <label htmlFor="corr-punch-type" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                    Adjust Punch Type
                  </label>
                  <select
                    id="corr-punch-type"
                    value={corrPunchType}
                    onChange={(e) => setCorrPunchType(e.target.value)}
                    style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                  >
                    <option value="CHECK_IN">CHECK_IN</option>
                    <option value="CHECK_OUT">CHECK_OUT</option>
                  </select>
                </div>
              ) : null}

              <div>
                <label htmlFor="corr-reason" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Reason Code
                </label>
                <select
                  id="corr-reason"
                  value={corrReasonCode}
                  onChange={(e) => setCorrReasonCode(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                >
                  <option value="FACULTY_CORRECTION">FACULTY_CORRECTION</option>
                  <option value="DUPLICATE_PUNCH">DUPLICATE_PUNCH</option>
                  <option value="WRONG_SESSION_RECONCILED">WRONG_SESSION_RECONCILED</option>
                  <option value="ADMIN_REVOCATION">ADMIN_REVOCATION</option>
                </select>
              </div>

              <div>
                <label htmlFor="corr-justification" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Justification (mandatory audit trail)
                </label>
                <textarea
                  id="corr-justification"
                  value={corrJustification}
                  onChange={(e) => setCorrJustification(e.target.value)}
                  placeholder="Explain why this correction or revocation is needed..."
                  required
                  rows={3}
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                />
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setCorrectionTarget(null)}
                  disabled={corrSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className={corrRevoke ? "button button-danger" : "button button-primary"}
                  disabled={corrSubmitting}
                >
                  {corrSubmitting ? "Submitting…" : corrRevoke ? "Revoke Record" : "Save Correction"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {/* Manual Entry Modal */}
      {manualEntryOpen ? (
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
          onClick={() => setManualEntryOpen(false)}
        >
          <div
            style={{
              background: "var(--bg-panel, #ffffff)",
              color: "var(--text-primary, #0f172a)",
              borderRadius: "10px",
              padding: "1.5rem",
              maxWidth: "520px",
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <div>
                <h3 style={{ margin: 0 }}>Record Manual Attendance</h3>
                <small style={{ color: "var(--text-secondary)" }}>
                  Administrative faculty override for an enrolled student
                </small>
              </div>
              <button
                type="button"
                className="button button-small button-secondary"
                onClick={() => setManualEntryOpen(false)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleManualEntrySubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div>
                <label htmlFor="manual-session-id" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Attendance Session ID (UUID)
                </label>
                <input
                  id="manual-session-id"
                  value={manualSessionId}
                  onChange={(e) => setManualSessionId(e.target.value)}
                  placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
                  required
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                />
              </div>

              <div>
                <label htmlFor="manual-student-id" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Student ID (UUID)
                </label>
                <input
                  id="manual-student-id"
                  value={manualStudentId}
                  onChange={(e) => setManualStudentId(e.target.value)}
                  placeholder="Enrolled Student UUID"
                  required
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                />
                <small style={{ color: "var(--text-secondary)" }}>
                  The student must have an active class enrollment for the selected session.
                </small>
              </div>

              <div>
                <label htmlFor="manual-punch-type" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Punch Type
                </label>
                <select
                  id="manual-punch-type"
                  value={manualPunchType}
                  onChange={(e) => setManualPunchType(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                >
                  <option value="CHECK_IN">CHECK_IN</option>
                  <option value="CHECK_OUT">CHECK_OUT</option>
                </select>
              </div>

              <div>
                <label htmlFor="manual-reason" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Reason Code
                </label>
                <select
                  id="manual-reason"
                  value={manualReasonCode}
                  onChange={(e) => setManualReasonCode(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                >
                  <option value="MANUAL_FACULTY_OVERRIDE">MANUAL_FACULTY_OVERRIDE</option>
                  <option value="KIOSK_TEMPORARILY_OFFLINE">KIOSK_TEMPORARILY_OFFLINE</option>
                  <option value="CAMERA_MALFUNCTION_OVERRIDE">CAMERA_MALFUNCTION_OVERRIDE</option>
                  <option value="STUDENT_LATE_ADMITTED">STUDENT_LATE_ADMITTED</option>
                </select>
              </div>

              <div>
                <label htmlFor="manual-justification" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Justification (mandatory audit trail)
                </label>
                <textarea
                  id="manual-justification"
                  value={manualJustification}
                  onChange={(e) => setManualJustification(e.target.value)}
                  placeholder="Provide explanation for manual entry..."
                  required
                  rows={3}
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                />
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setManualEntryOpen(false)}
                  disabled={manualSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="button button-primary"
                  disabled={manualSubmitting}
                >
                  {manualSubmitting ? "Recording…" : "Record Attendance"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      <p className="compliance-note">
        This page displays attendance events verified and persisted by the backend pipeline. All accepted events carry immutable similarity evidence and audit references.
      </p>
    </>
  );
}
