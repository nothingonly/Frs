"use client";

/* eslint react-hooks/set-state-in-effect: off -- The effect initiates an external HTTP read; state updates occur in async response handlers. */

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useAdmin } from "@/components/admin-provider";

type Items<T> = { items: T[] };
type ClassGroup = {
  class_group_id: string;
  department_code: string;
  department_name: string;
  year_of_study: number;
  section: string;
  academic_year: string;
  is_active: boolean;
};
type AttendanceSession = {
  session_id: string;
  class_group_id: string;
  subject_code: string | null;
  subject_name: string;
  starts_at: string;
  ends_at: string | null;
  status: "OPEN" | "CLOSED" | "CANCELLED" | string;
  idempotency_key: string | null;
};
type CaptureBatch = {
  batch_id: string;
  attendance_session_id: string;
  class_group_id: string;
  status: "QUEUED" | "PROCESSING" | "SUCCEEDED" | "REJECTED" | "FAILED" | string;
  frame_count: number;
  attempts: number;
  max_attempts: number;
  created_at: string;
  completed_at: string | null;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
};

function sessionLabel(group: ClassGroup | undefined, session: AttendanceSession) {
  const groupLabel = group
    ? group.department_code + " · Year " + group.year_of_study + "-" + group.section + " · " + group.academic_year
    : session.class_group_id.slice(0, 8);
  return groupLabel + " · " + session.subject_name + (session.subject_code ? " (" + session.subject_code + ")" : "");
}

function batchMessage(batch: CaptureBatch) {
  const detail = batch.error?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return batch.status === "SUCCEEDED" ? "Attendance decision was persisted." : "";
}

export default function AttendanceSessionsPage() {
  const { isConnected, requestJson } = useAdmin();
  const [groups, setGroups] = useState<ClassGroup[]>([]);
  const [sessions, setSessions] = useState<AttendanceSession[]>([]);
  const [batches, setBatches] = useState<CaptureBatch[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [subjectName, setSubjectName] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [batchStatus, setBatchStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyJob, setBusyJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const groupsById = useMemo(
    () => new Map(groups.map((group) => [group.class_group_id, group])),
    [groups],
  );

  const refresh = useCallback(async () => {
    if (!isConnected) return;
    setLoading(true);
    setError(null);
    try {
      const [groupPayload, sessionPayload] = await Promise.all([
        requestJson<Items<ClassGroup>>("/api/v1/admin/college/class-groups?active_only=true&limit=500"),
        requestJson<Items<AttendanceSession>>("/api/v1/admin/college/attendance-sessions?limit=300"),
      ]);
      setGroups(groupPayload.items);
      setSessions(sessionPayload.items);
      setGroupId((current) =>
        groupPayload.items.some((item) => item.class_group_id === current)
          ? current
          : groupPayload.items[0]?.class_group_id ?? "",
      );

      const chosen = sessionPayload.items.find((item) => item.session_id === selectedSessionId)
        ?? sessionPayload.items.find((item) => item.status === "OPEN")
        ?? sessionPayload.items[0];
      const nextSelectedId = chosen?.session_id ?? "";
      setSelectedSessionId(nextSelectedId);
      if (nextSelectedId) {
        const query = new URLSearchParams({ attendance_session_id: nextSelectedId, limit: "200" });
        const batchPayload = await requestJson<Items<CaptureBatch>>(
          "/api/v1/admin/attendance-batches?" + query.toString(),
        );
        setBatches(batchPayload.items);
      } else {
        setBatches([]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load sessions and capture jobs.");
    } finally {
      setLoading(false);
    }
  }, [isConnected, requestJson, selectedSessionId]);

  useEffect(() => {
    if (isConnected) void refresh();
  }, [isConnected, refresh]);

  async function selectSession(nextId: string) {
    setSelectedSessionId(nextId);
    setError(null);
    if (!nextId) {
      setBatches([]);
      return;
    }
    try {
      const query = new URLSearchParams({ attendance_session_id: nextId, limit: "200" });
      const payload = await requestJson<Items<CaptureBatch>>(
        "/api/v1/admin/attendance-batches?" + query.toString(),
      );
      setBatches(payload.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load capture jobs.");
    }
  }

  async function createSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload: Record<string, unknown> = {
        class_group_id: groupId,
        subject_code: subjectCode.trim() || null,
        subject_name: subjectName.trim(),
        idempotency_key: crypto.randomUUID(),
      };
      if (startsAt) payload.starts_at = new Date(startsAt).toISOString();
      const created = await requestJson<AttendanceSession>("/api/v1/admin/college/attendance-sessions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setNotice("Attendance session created for " + created.subject_name + ". It is OPEN and ready for authenticated kiosks.");
      setSubjectCode("");
      setSubjectName("");
      setStartsAt("");
      setSelectedSessionId(created.session_id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create attendance session.");
    } finally {
      setSaving(false);
    }
  }

  async function closeSession(session: AttendanceSession) {
    setBusyJob(session.session_id);
    setError(null);
    setNotice(null);
    try {
      await requestJson<AttendanceSession>(
        "/api/v1/admin/college/attendance-sessions/" + encodeURIComponent(session.session_id) + "/close",
        { method: "POST" },
      );
      setNotice("Session " + session.subject_name + " is now CLOSED. New capture batches are no longer accepted.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not close session.");
    } finally {
      setBusyJob(null);
    }
  }

  async function retryBatch(batch: CaptureBatch) {
    setBusyJob(batch.batch_id);
    setError(null);
    setNotice(null);
    try {
      await requestJson<CaptureBatch>(
        "/api/v1/admin/attendance-batches/" + encodeURIComponent(batch.batch_id) + "/retry",
        { method: "POST" },
      );
      setNotice("Capture batch " + batch.batch_id.slice(0, 8) + " returned to the queue.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retry capture batch.");
    } finally {
      setBusyJob(null);
    }
  }

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">SESSION OPERATIONS</div>
          <h2>Attendance sessions & capture jobs</h2>
          <p>Create a session for one class group, then inspect real kiosk capture jobs and their server-persisted outcomes.</p>
        </div>
        <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={!isConnected || loading}>
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </section>

      {!isConnected ? (
        <div className="notice notice-info">
          <strong>Administrator connection required</strong>
          <span>Connect to the FastAPI admin API in the sidebar to load class groups, sessions and capture-job status.</span>
        </div>
      ) : null}
      {error ? <div className="notice notice-error" role="alert"><strong>Request failed</strong><span>{error}</span></div> : null}
      {notice ? <div className="notice notice-success" role="status"><strong>Saved</strong><span>{notice}</span></div> : null}

      <section className="panel form-panel">
        <div className="form-index">01 / OPEN A SESSION</div>
        <h3>Create attendance session</h3>
        <p className="panel-description">Only active class groups can receive a new session. The kiosk lists OPEN sessions for authenticated devices.</p>
        <form className="stack-form" onSubmit={(event) => void createSession(event)}>
          <label>
            Class group
            <select required value={groupId} onChange={(event) => setGroupId(event.target.value)}>
              <option value="">Select class group</option>
              {groups.filter((group) => group.is_active).map((group) => (
                <option key={group.class_group_id} value={group.class_group_id}>
                  {group.department_code} · Year {group.year_of_study}-{group.section} · {group.academic_year}
                </option>
              ))}
            </select>
          </label>
          <div className="split-fields">
            <label>Subject code (optional)<input maxLength={40} value={subjectCode} onChange={(event) => setSubjectCode(event.target.value.toUpperCase())} placeholder="CS301" /></label>
            <label>Subject name<input required maxLength={160} value={subjectName} onChange={(event) => setSubjectName(event.target.value)} placeholder="Computer Networks" /></label>
          </div>
          <label>Scheduled start (optional)<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /></label>
          <button className="button button-primary" disabled={!isConnected || !groupId || groups.filter((group) => group.is_active).length === 0 || saving}>
            {saving ? "Creating…" : "Open attendance session"}
          </button>
          {groups.length === 0 ? <small>Create departments and class groups in College Setup first.</small> : null}
        </form>
      </section>

      <section className="panel table-panel">
        <div className="table-toolbar">
          <div><h3>Persisted attendance sessions</h3><p>{sessions.length} sessions returned from the API · no sample sessions are inserted</p></div>
          <label className="search-field">
            <span>Capture queue for</span>
            <select value={selectedSessionId} onChange={(event) => void selectSession(event.target.value)}>
              <option value="">Select session</option>
              {sessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.subject_name} · {groupsById.get(session.class_group_id)?.department_code ?? session.class_group_id.slice(0, 8)} · {session.status}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Class / subject</th><th>Start time</th><th>Status</th><th>Session ID</th><th>Action</th></tr></thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.session_id}>
                  <td>
                    <strong>{session.subject_name}</strong>
                    <small className="cell-subtext">{sessionLabel(groupsById.get(session.class_group_id), session)}</small>
                  </td>
                  <td>{new Date(session.starts_at).toLocaleString()}</td>
                  <td><span className={session.status === "OPEN" ? "pill pill-success" : "pill pill-muted"}>{session.status}</span></td>
                  <td><code>{session.session_id.slice(0, 12)}</code></td>
                  <td>
                    {session.status === "OPEN" ? (
                      <button className="button button-secondary button-small" disabled={busyJob !== null || !isConnected} onClick={() => void closeSession(session)}>
                        {busyJob === session.session_id ? "Closing…" : "Close session"}
                      </button>
                    ) : "—"}
                  </td>
                </tr>
              ))}
              {sessions.length === 0 ? <tr><td colSpan={5}><div className="empty-state"><strong>No sessions yet</strong><span>Create a session above after configuring a class group.</span></div></td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel table-panel">
        <div className="table-toolbar">
          <div><h3>Capture-job queue</h3><p>{batches.length} persisted jobs for the selected session · frame payloads are not exposed in this view</p></div>
          <label className="search-field">
            <span>Status</span>
            <select value={batchStatus} onChange={(event) => setBatchStatus(event.target.value)}>
              <option value="">All states</option>
              {["QUEUED", "PROCESSING", "SUCCEEDED", "REJECTED", "FAILED"].map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Batch / timestamp</th><th>Frames</th><th>State</th><th>Worker attempts</th><th>Outcome / error</th><th>Action</th></tr></thead>
            <tbody>
              {batches.filter((batch) => !batchStatus || batch.status === batchStatus).map((batch) => (
                <tr key={batch.batch_id}>
                  <td><strong><code>{batch.batch_id.slice(0, 12)}</code></strong><small className="cell-subtext">{new Date(batch.created_at).toLocaleString()}</small></td>
                  <td>{batch.frame_count}</td>
                  <td><span className={batch.status === "SUCCEEDED" ? "pill pill-success" : batch.status === "FAILED" || batch.status === "REJECTED" ? "pill pill-warning" : "pill pill-muted"}>{batch.status}</span></td>
                  <td>{batch.attempts} / {batch.max_attempts}</td>
                  <td><small>{batchMessage(batch) || (batch.result ? "Attendance ID: " + String(batch.result.attendance_id ?? "persisted") : "Awaiting worker result")}</small></td>
                  <td>
                    {batch.status === "FAILED" ? (
                      <button className="button button-secondary button-small" disabled={busyJob !== null || !isConnected} onClick={() => void retryBatch(batch)}>
                        {busyJob === batch.batch_id ? "Retrying…" : "Retry"}
                      </button>
                    ) : "—"}
                  </td>
                </tr>
              ))}
              {batches.filter((batch) => !batchStatus || batch.status === batchStatus).length === 0 ? (
                <tr><td colSpan={6}><div className="empty-state"><strong>No capture jobs</strong><span>Jobs appear here after authenticated kiosks submit a frame burst for this session.</span></div></td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <p className="compliance-note">Recognition is performed by the configured backend model pipeline. This console only displays stored job states; it cannot mark a job successful. Use only with institution-approved biometric notice, enrollment, retention and access controls.</p>
    </>
  );
}
