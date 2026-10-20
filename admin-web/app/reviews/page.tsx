"use client";

/* eslint react-hooks/set-state-in-effect: off -- Async external HTTP reads in handlers. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAdmin } from "@/components/admin-provider";

export type ReviewItem = {
  batch_id: string;
  session_id: string;
  subject_name: string;
  class_group_id: string;
  section: string;
  academic_year: string;
  status: "REJECTED" | "FAILED";
  punch_type: string;
  frame_count: number;
  created_at: string;
  client_device_id: string;
  error_detail: Record<string, unknown>;
};

export default function ReviewQueuePage() {
  const { isConnected, requestJson } = useAdmin();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Modal State
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [resolveAction, setResolveAction] = useState<"APPROVE_MANUAL" | "DISMISS">("APPROVE_MANUAL");
  const [studentId, setStudentId] = useState("");
  const [reasonCode, setReasonCode] = useState("FACULTY_CONFIRMED_IDENTITY");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await requestJson<{ items: ReviewItem[] }>("/api/v1/admin/review-queue?limit=100");
      setItems(payload.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load review queue.");
    } finally {
      setLoading(false);
    }
  }, [requestJson]);

  useEffect(() => {
    if (isConnected) void refresh();
  }, [isConnected, refresh]);

  const visibleItems = useMemo(() => {
    return items.filter((item) => {
      if (statusFilter !== "ALL" && item.status !== statusFilter) return false;
      const query = filter.trim().toLowerCase();
      if (!query) return true;
      return [
        item.batch_id,
        item.session_id,
        item.subject_name,
        item.client_device_id,
        item.section,
        item.academic_year,
      ].some((v) => v.toLowerCase().includes(query));
    });
  }, [items, filter, statusFilter]);

  function openResolveModal(item: ReviewItem) {
    setSelectedItem(item);
    setResolveAction("APPROVE_MANUAL");
    setStudentId("");
    setReasonCode("FACULTY_CONFIRMED_IDENTITY");
    setNotes("");
    setError(null);
  }

  async function handleResolveSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedItem) return;

    if (resolveAction === "APPROVE_MANUAL" && !studentId.trim()) {
      setError("Please enter the enrolled Student ID to approve attendance.");
      return;
    }
    if (!notes.trim()) {
      setError("A brief note/justification is required for the audit trail.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await requestJson(`/api/v1/admin/review-queue/${encodeURIComponent(selectedItem.batch_id)}/resolve`, {
        method: "POST",
        body: JSON.stringify({
          action: resolveAction,
          student_id: resolveAction === "APPROVE_MANUAL" ? studentId.trim() : null,
          reason_code: reasonCode,
          notes: notes.trim(),
        }),
      });

      setSuccessMsg(
        resolveAction === "APPROVE_MANUAL"
          ? `Batch ${selectedItem.batch_id.slice(0, 8)} manually approved for student ${studentId}.`
          : `Batch ${selectedItem.batch_id.slice(0, 8)} dismissed.`
      );
      setSelectedItem(null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to resolve review item.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">CAPTURE REVIEWS &amp; EXCEPTIONS</div>
          <h2>Review queue</h2>
          <p>
            Inspect ambiguous, low-confidence, or failed capture batches. Authorized administrators can manually approve
            verified students or dismiss unauthorized submissions with mandatory audit logging.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
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
          <span>Enter a valid administrator bearer key in the sidebar to inspect the capture review queue.</span>
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
          <strong>Action recorded</strong>
          <span>{successMsg}</span>
        </div>
      ) : null}

      <section className="panel table-panel">
        <div className="table-toolbar">
          <div>
            <h3>Pending exceptions ({visibleItems.length})</h3>
            <p>Failed recognition runs and low-confidence capture batches requiring verification</p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <label className="search-field">
              <span>Filter Status</span>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="ALL">All Statuses</option>
                <option value="REJECTED">REJECTED (No Match / Low Confidence)</option>
                <option value="FAILED">FAILED (Pipeline / Processing Error)</option>
              </select>
            </label>
            <label className="search-field">
              <span>Search</span>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Batch, session, or device"
              />
            </label>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Batch / Created</th>
                <th>Session &amp; Class</th>
                <th>Status</th>
                <th>Frames / Punch</th>
                <th>Device</th>
                <th>Failure Details</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((item) => (
                <tr key={item.batch_id}>
                  <td>
                    <strong><code>{item.batch_id.slice(0, 8)}</code></strong>
                    <br />
                    <small className="cell-subtext">{new Date(item.created_at).toLocaleString()}</small>
                  </td>
                  <td>
                    <strong>{item.subject_name}</strong>
                    <br />
                    <small className="cell-subtext">Sec {item.section} · {item.academic_year}</small>
                  </td>
                  <td>
                    <span className={item.status === "REJECTED" ? "pill pill-warning" : "pill pill-muted"}>
                      {item.status}
                    </span>
                  </td>
                  <td>
                    <span>{item.frame_count} frames</span>
                    <br />
                    <small className="cell-subtext">{item.punch_type}</small>
                  </td>
                  <td>
                    <code>{item.client_device_id}</code>
                  </td>
                  <td>
                    <small>
                      {item.error_detail?.message
                        ? String(item.error_detail.message).slice(0, 80)
                        : item.error_detail?.code
                        ? String(item.error_detail.code)
                        : "Threshold not met or face unverified"}
                    </small>
                  </td>
                  <td>
                    <button
                      className="button button-small button-primary"
                      type="button"
                      onClick={() => openResolveModal(item)}
                    >
                      Resolve
                    </button>
                  </td>
                </tr>
              ))}
              {visibleItems.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-state">
                      <strong>{loading ? "Loading review queue…" : "No pending review items"}</strong>
                      <span>
                        {isConnected
                          ? "All capture batches are processed and resolved. No exceptions requiring intervention."
                          : "Connect to the admin API to inspect review items."}
                      </span>
                    </div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {/* Resolution Modal */}
      {selectedItem ? (
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
          onClick={() => setSelectedItem(null)}
        >
          <div
            style={{
              background: "var(--bg-panel, #ffffff)",
              color: "var(--text-primary, #0f172a)",
              borderRadius: "10px",
              padding: "1.5rem",
              maxWidth: "600px",
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <div>
                <h3 style={{ margin: 0 }}>Resolve Capture Exception</h3>
                <small style={{ color: "var(--text-secondary)" }}>
                  Batch: <code>{selectedItem.batch_id}</code>
                </small>
              </div>
              <button
                type="button"
                className="button button-small button-secondary"
                onClick={() => setSelectedItem(null)}
              >
                ✕
              </button>
            </div>

            <div style={{ background: "var(--bg-surface, #f8fafc)", padding: "0.75rem", borderRadius: "6px", marginBottom: "1rem" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem", fontSize: "0.875rem" }}>
                <div><strong>Subject:</strong> {selectedItem.subject_name}</div>
                <div><strong>Section:</strong> {selectedItem.section} ({selectedItem.academic_year})</div>
                <div><strong>Device:</strong> {selectedItem.client_device_id}</div>
                <div><strong>Captured:</strong> {selectedItem.frame_count} frames ({selectedItem.punch_type})</div>
              </div>
              <div style={{ marginTop: "0.5rem", fontSize: "0.85rem", color: "var(--text-secondary)" }}>
                <strong>Error / Rejection:</strong>{" "}
                {JSON.stringify(selectedItem.error_detail)}
              </div>
            </div>

            <form onSubmit={handleResolveSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div>
                <label style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>Decision Action</label>
                <div style={{ display: "flex", gap: "1rem" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.25rem", cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="resolveAction"
                      checked={resolveAction === "APPROVE_MANUAL"}
                      onChange={() => {
                        setResolveAction("APPROVE_MANUAL");
                        setReasonCode("FACULTY_CONFIRMED_IDENTITY");
                      }}
                    />
                    <span>Approve manual attendance</span>
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.25rem", cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="resolveAction"
                      checked={resolveAction === "DISMISS"}
                      onChange={() => {
                        setResolveAction("DISMISS");
                        setReasonCode("DISMISSED_UNAUTHORIZED_INDIVIDUAL");
                      }}
                    />
                    <span>Dismiss exception</span>
                  </label>
                </div>
              </div>

              {resolveAction === "APPROVE_MANUAL" ? (
                <div>
                  <label htmlFor="student-id-input" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                    Student ID (UUID or enrolled identifier)
                  </label>
                  <input
                    id="student-id-input"
                    value={studentId}
                    onChange={(e) => setStudentId(e.target.value)}
                    placeholder="Enter enrolled student UUID"
                    required
                    style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                  />
                  <small style={{ color: "var(--text-secondary)" }}>
                    Must be an active student enrolled in this class session.
                  </small>
                </div>
              ) : null}

              <div>
                <label htmlFor="reason-code-select" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Reason Code
                </label>
                <select
                  id="reason-code-select"
                  value={reasonCode}
                  onChange={(e) => setReasonCode(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                >
                  {resolveAction === "APPROVE_MANUAL" ? (
                    <>
                      <option value="FACULTY_CONFIRMED_IDENTITY">FACULTY_CONFIRMED_IDENTITY</option>
                      <option value="CAMERA_GLARE_VERIFIED">CAMERA_GLARE_VERIFIED</option>
                      <option value="POOR_LIGHTING_OVERRIDDEN">POOR_LIGHTING_OVERRIDDEN</option>
                      <option value="STUDENT_IDENTIFIED_IN_PERSON">STUDENT_IDENTIFIED_IN_PERSON</option>
                      <option value="ADMIN_MANUAL_OVERRIDE">ADMIN_MANUAL_OVERRIDE</option>
                    </>
                  ) : (
                    <>
                      <option value="DISMISSED_UNAUTHORIZED_INDIVIDUAL">DISMISSED_UNAUTHORIZED_INDIVIDUAL</option>
                      <option value="STUDENT_NOT_PRESENT">STUDENT_NOT_PRESENT</option>
                      <option value="UNRECOVERABLE_BLUR">UNRECOVERABLE_BLUR</option>
                      <option value="SPOOF_ATTEMPT_SUSPECTED">SPOOF_ATTEMPT_SUSPECTED</option>
                      <option value="DUPLICATE_FALSE_SUBMISSION">DUPLICATE_FALSE_SUBMISSION</option>
                    </>
                  )}
                </select>
              </div>

              <div>
                <label htmlFor="notes-input" style={{ display: "block", marginBottom: "0.25rem", fontWeight: 600 }}>
                  Justification / Audit Notes
                </label>
                <textarea
                  id="notes-input"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Explain why this decision is justified..."
                  required
                  rows={3}
                  style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid var(--border-color, #cbd5e1)" }}
                />
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setSelectedItem(null)}
                  disabled={submitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="button button-primary"
                  disabled={submitting}
                >
                  {submitting ? "Recording…" : "Submit resolution"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      <p className="compliance-note">
        All review resolutions create immutable AuditEvents with actor identity, timestamp, reason codes, and
        justification. Manual approvals atomically record an attendance punch scoped to the active session.
      </p>
    </>
  );
}
