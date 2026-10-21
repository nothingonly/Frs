"use client";

/* eslint react-hooks/set-state-in-effect: off -- The effect initiates an external HTTP read; state updates occur in async response handlers. */

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ChangeEvent } from "react";
import Link from "next/link";
import { useAdmin } from "@/components/admin-provider";

type Items<T> = { items: T[] };

type ClassGroup = {
  class_group_id: string;
  department_code: string;
  department_name: string;
  year_of_study: number;
  section: string;
  academic_year: string;
  semester?: number | null;
  is_lab?: boolean;
  lab_name?: string | null;
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
  session_type?: "SPECIFIC" | "LAB" | "MIXED";
  lab_name?: string | null;
  semester?: number | null;
  expected_roster_count?: number;
  class_group_ids?: string[];
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

type RosterStudent = {
  student_id: string;
  student_number: string;
  full_name: string;
  department_code: string;
  year_of_study: number;
  section: string;
  status: "PRESENT" | "PENDING_REVIEW" | "UNRESOLVED" | "MARKED_ABSENT";
  similarity_score: number;
  notes: string | null;
};

type SessionProvisionalState = {
  session_id: string;
  status: string;
  expected_count: number;
  present_count: number;
  pending_review_count: number;
  unresolved_count: number;
  unknown_faces_count: number;
  photos_captured_count: number;
  roster: RosterStudent[];
};

type GroupCaptureResult = {
  capture_id: string;
  photo_index: number;
  faces_detected_count: number;
  faces_matched_count: number;
  faces_uncertain_count: number;
  faces_unknown_count: number;
  duplicates_ignored_count: number;
  summary_message: string;
  cumulative_state: SessionProvisionalState;
};

export default function AttendanceSessionsPage() {
  const { isConnected, requestJson } = useAdmin();
  const [groups, setGroups] = useState<ClassGroup[]>([]);
  const [sessions, setSessions] = useState<AttendanceSession[]>([]);
  const [batches, setBatches] = useState<CaptureBatch[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");

  // Create session form state
  const [sessionType, setSessionType] = useState<"SPECIFIC" | "LAB" | "MIXED">("SPECIFIC");
  const [groupId, setGroupId] = useState("");
  const [selectedMixedGroupIds, setSelectedMixedGroupIds] = useState<string[]>([]);
  const [subjectCode, setSubjectCode] = useState("");
  const [subjectName, setSubjectName] = useState("");
  const [sessionLabName, setSessionLabName] = useState("");
  const [sessionSemester, setSessionSemester] = useState("1");
  const [startsAt, setStartsAt] = useState("");

  // Web group capture & provisional review states
  const [groupPhotoFile, setGroupPhotoFile] = useState<File | null>(null);
  const [provisionalState, setProvisionalState] = useState<SessionProvisionalState | null>(null);
  const [lastCaptureResult, setLastCaptureResult] = useState<GroupCaptureResult | null>(null);
  const [isUploadingGroupPhoto, setIsUploadingGroupPhoto] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [rosterSearch, setRosterSearch] = useState("");
  const [rosterTab, setRosterTab] = useState<"ALL" | "PRESENT" | "FLAGGED" | "ABSENT">("ALL");

  // Status & loading
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

  const selectedSession = useMemo(
    () => sessions.find((s) => s.session_id === selectedSessionId),
    [sessions, selectedSessionId]
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
        await Promise.all([
          loadBatches(nextSelectedId),
          loadProvisional(nextSelectedId),
        ]);
      } else {
        setBatches([]);
        setProvisionalState(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load sessions and records.");
    } finally {
      setLoading(false);
    }
  }, [isConnected, requestJson, selectedSessionId]);

  useEffect(() => {
    if (isConnected) void refresh();
  }, [isConnected, refresh]);

  async function loadBatches(sessionId: string) {
    try {
      const query = new URLSearchParams({ attendance_session_id: sessionId, limit: "200" });
      const batchPayload = await requestJson<Items<CaptureBatch>>(
        "/api/v1/admin/attendance-batches?" + query.toString(),
      );
      setBatches(batchPayload.items);
    } catch {
      setBatches([]);
    }
  }

  async function loadProvisional(sessionId: string) {
    try {
      const state = await requestJson<SessionProvisionalState>(
        `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}/provisional`
      );
      setProvisionalState(state);
    } catch {
      setProvisionalState(null);
    }
  }

  async function selectSession(nextId: string) {
    setSelectedSessionId(nextId);
    setError(null);
    setLastCaptureResult(null);
    if (!nextId) {
      setBatches([]);
      setProvisionalState(null);
      return;
    }
    await Promise.all([
      loadBatches(nextId),
      loadProvisional(nextId),
    ]);
  }

  async function createSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload: Record<string, unknown> = {
        session_type: sessionType,
        class_group_id: groupId,
        class_group_ids: sessionType === "MIXED" ? selectedMixedGroupIds : [groupId],
        subject_code: subjectCode.trim() || null,
        subject_name: subjectName.trim(),
        semester: Number(sessionSemester),
        is_lab: sessionType === "LAB",
        lab_name: sessionType === "LAB" ? sessionLabName.trim() : null,
        idempotency_key: crypto.randomUUID(),
      };
      if (startsAt) payload.starts_at = new Date(startsAt).toISOString();
      const created = await requestJson<AttendanceSession>("/api/v1/admin/college/attendance-sessions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setNotice("Attendance session created for " + created.subject_name + ". Session is OPEN and ready for group photo captures.");
      setSubjectCode("");
      setSubjectName("");
      setSessionLabName("");
      setStartsAt("");
      await refresh();
      await selectSession(created.session_id);
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
      setNotice("Session " + session.subject_name + " is now CLOSED.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not close session.");
    } finally {
      setBusyJob(null);
    }
  }

  // Web group photo capture upload handler
  function handlePhotoFileChange(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      setGroupPhotoFile(e.target.files[0]);
    }
  }

  async function uploadWebGroupPhoto() {
    if (!groupPhotoFile || !selectedSessionId) return;
    setIsUploadingGroupPhoto(true);
    setError(null);
    setNotice(null);
    try {
      const formData = new FormData();
      formData.append("image", groupPhotoFile);
      const result = await requestJson<GroupCaptureResult>(
        `/api/v1/attendance/sessions/${encodeURIComponent(selectedSessionId)}/group-captures`,
        { method: "POST", body: formData }
      );
      setLastCaptureResult(result);
      setProvisionalState(result.cumulative_state);
      setNotice(`Capture #${result.photo_index} processed: ${result.faces_detected_count} faces detected, ${result.faces_matched_count} recognized.`);
      setGroupPhotoFile(null);
      await loadProvisional(selectedSessionId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to process group capture.");
    } finally {
      setIsUploadingGroupPhoto(false);
    }
  }

  async function toggleStudent(student: RosterStudent, newStatus: string) {
    if (!selectedSessionId) return;
    setError(null);
    try {
      await requestJson(
        `/api/v1/attendance/sessions/${encodeURIComponent(selectedSessionId)}/provisional/${encodeURIComponent(student.student_id)}/toggle`,
        {
          method: "POST",
          body: JSON.stringify({ new_status: newStatus, notes: "Web admin manual override" }),
        }
      );
      await loadProvisional(selectedSessionId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to toggle status.");
    }
  }

  async function finalizeSession() {
    if (!selectedSessionId || !provisionalState) return;
    if (!window.confirm(`Finalize attendance for this session?\nPresent: ${provisionalState.present_count} / ${provisionalState.expected_count}.\nThis permanently commits official records.`)) return;

    setIsFinalizing(true);
    setError(null);
    setNotice(null);
    try {
      const result = await requestJson<{ status: string; present_count: number; total_expected: number }>(
        `/api/v1/attendance/sessions/${encodeURIComponent(selectedSessionId)}/finalize`,
        { method: "POST" }
      );
      setNotice(`Attendance finalized successfully! ${result.present_count} of ${result.total_expected} students recorded.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to finalize session.");
    } finally {
      setIsFinalizing(false);
    }
  }

  const filteredRoster = useMemo(() => {
    if (!provisionalState) return [];
    const query = rosterSearch.toLowerCase().trim();
    return provisionalState.roster.filter((s) => {
      if (rosterTab === "PRESENT" && s.status !== "PRESENT") return false;
      if (rosterTab === "FLAGGED" && s.status !== "PENDING_REVIEW") return false;
      if (rosterTab === "ABSENT" && (s.status === "PRESENT" || s.status === "PENDING_REVIEW")) return false;
      if (query && !s.student_number.toLowerCase().includes(query) && !s.full_name.toLowerCase().includes(query)) {
        return false;
      }
      return true;
    });
  }, [provisionalState, rosterSearch, rosterTab]);

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">SESSION OPERATIONS & GROUP CAPTURE</div>
          <h2>Classroom Attendance Sessions</h2>
          <p>Create theory, lab, or mixed class sessions, and process multi-photo group captures with automated ArcFace deduplication.</p>
        </div>
        <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={!isConnected || loading}>
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </section>

      {!isConnected ? (
        <div className="notice notice-info">
          <strong>Administrator connection required</strong>
          <span>Connect to FastAPI in the sidebar to open attendance sessions and review provisional rosters.</span>
        </div>
      ) : null}
      {error ? <div className="notice notice-error" role="alert"><strong>Request failed</strong><span>{error}</span></div> : null}
      {notice ? <div className="notice notice-success" role="status"><strong>Notice</strong><span>{notice}</span></div> : null}

      {/* CREATE SESSION PANEL */}
      <section className="panel form-panel">
        <div className="form-index">01 / OPEN A CLASS SESSION</div>
        <h3>Create Attendance Session</h3>
        <p className="panel-description">Support specific classes, configured lab sessions, or mixed multi-cohort classes.</p>
        <form className="stack-form" onSubmit={(event) => void createSession(event)}>
          <div className="split-fields">
            <label>
              Session Type
              <select value={sessionType} onChange={(e) => setSessionType(e.target.value as "SPECIFIC" | "LAB" | "MIXED")}>
                <option value="SPECIFIC">Theory Class</option>
                <option value="LAB">Laboratory Session</option>
                <option value="MIXED">Mixed Class (Combined Cohorts)</option>
              </select>
            </label>
            <label>
              Semester
              <select value={sessionSemester} onChange={(e) => setSessionSemester(e.target.value)}>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((sem) => (
                  <option key={sem} value={sem}>Semester {sem}</option>
                ))}
              </select>
            </label>
          </div>

          {sessionType === "LAB" && (
            <label>
              Lab Name
              <input
                required
                value={sessionLabName}
                onChange={(e) => setSessionLabName(e.target.value)}
                placeholder="e.g. AI & Machine Learning Lab (Batch 1)"
              />
            </label>
          )}

          {sessionType === "MIXED" ? (
            <label>
              Select Combined Class Cohorts
              <select
                multiple
                style={{ height: "90px" }}
                value={selectedMixedGroupIds}
                onChange={(e) => setSelectedMixedGroupIds(Array.from(e.target.selectedOptions, (opt) => opt.value))}
              >
                {groups.map((group) => (
                  <option key={group.class_group_id} value={group.class_group_id}>
                    {group.department_code} · Y{group.year_of_study}-{group.section} ({group.academic_year})
                  </option>
                ))}
              </select>
              <small>Hold Ctrl (Cmd on Mac) to select multiple cohorts.</small>
            </label>
          ) : (
            <label>
              Class Cohort
              <select required value={groupId} onChange={(event) => setGroupId(event.target.value)}>
                <option value="">Select class group</option>
                {groups.filter((group) => group.is_active).map((group) => (
                  <option key={group.class_group_id} value={group.class_group_id}>
                    {group.department_code} · Year {group.year_of_study}-{group.section} {group.is_lab ? `· Lab: ${group.lab_name}` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="split-fields">
            <label>Subject Code (optional)<input maxLength={40} value={subjectCode} onChange={(event) => setSubjectCode(event.target.value.toUpperCase())} placeholder="CS301" /></label>
            <label>Subject / Class Name<input required maxLength={160} value={subjectName} onChange={(event) => setSubjectName(event.target.value)} placeholder="Computer Networks" /></label>
          </div>
          <label>Scheduled Start (optional)<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /></label>
          <button className="button button-primary" disabled={!isConnected || saving}>
            {saving ? "Opening Session…" : "Open Attendance Session"}
          </button>
        </form>
      </section>

      {/* SESSIONS LIST PANEL */}
      <section className="panel table-panel">
        <div className="table-toolbar">
          <div>
            <h3>Active & Recent Sessions</h3>
            <p>{sessions.length} sessions in database</p>
          </div>
          <label className="search-field">
            <span>Selected Session</span>
            <select value={selectedSessionId} onChange={(event) => void selectSession(event.target.value)}>
              <option value="">Select session</option>
              {sessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.subject_name} · {session.status}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Class / Subject</th>
                <th>Type</th>
                <th>Expected Roster</th>
                <th>Start Time</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.session_id} style={{ background: session.session_id === selectedSessionId ? "rgba(13, 148, 136, 0.04)" : undefined }}>
                  <td>
                    <strong>{session.subject_name}</strong>
                    <small className="cell-subtext">{session.subject_code ? `(${session.subject_code})` : ""}</small>
                  </td>
                  <td>
                    <span className={`pill ${session.session_type === "LAB" ? "badge-lab" : session.session_type === "MIXED" ? "badge-mixed" : "badge-class"}`}>
                      {session.session_type ?? "SPECIFIC"}
                    </span>
                  </td>
                  <td>{session.expected_roster_count ?? "—"} students</td>
                  <td>{new Date(session.starts_at).toLocaleString()}</td>
                  <td>
                    <span className={session.status === "OPEN" ? "pill pill-success" : "pill pill-muted"}>
                      {session.status}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                      <button
                        className="button button-secondary button-small"
                        onClick={() => void selectSession(session.session_id)}
                      >
                        {session.session_id === selectedSessionId ? "✓ Selected" : "Select"}
                      </button>
                      {session.status === "OPEN" && (
                        <button
                          className="button button-secondary button-small"
                          disabled={busyJob !== null || !isConnected}
                          onClick={() => void closeSession(session)}
                        >
                          {busyJob === session.session_id ? "Closing…" : "Close"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {sessions.length === 0 && (
                <tr><td colSpan={6}><div className="empty-state"><strong>No sessions created yet</strong></div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* WEB GROUP CAPTURE & PROVISIONAL ROSTER REVIEW FOR SELECTED SESSION */}
      {selectedSession && selectedSession.status === "OPEN" && (
        <section className="panel" style={{ border: "2px solid #0d9488" }}>
          <div className="panel-heading">
            <div>
              <span className="eyebrow" style={{ color: "#0d9488" }}>ACTIVE WORKFLOW</span>
              <h3>Group Photo Attendance: {selectedSession.subject_name}</h3>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                className="button button-primary"
                disabled={isFinalizing || !provisionalState}
                onClick={() => void finalizeSession()}
              >
                {isFinalizing ? "Finalizing…" : "✅ Confirm & Finalize Attendance"}
              </button>
            </div>
          </div>

          {/* Cumulative Progress Bar */}
          {provisionalState && (
            <div style={{ marginBottom: "20px" }}>
              <div style={{ display: "flex", gap: "16px", marginBottom: "12px" }}>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">EXPECTED ROSTER</div>
                  <span className="stat-value">{provisionalState.expected_count}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">PRESENT</div>
                  <span className="stat-value" style={{ color: "#10b981" }}>{provisionalState.present_count}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">PENDING REVIEW</div>
                  <span className="stat-value" style={{ color: "#f59e0b" }}>{provisionalState.pending_review_count}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">ABSENT</div>
                  <span className="stat-value" style={{ color: "#ef4444" }}>{provisionalState.unresolved_count}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">CAPTURES TAKEN</div>
                  <span className="stat-value">{provisionalState.photos_captured_count}</span>
                </div>
              </div>

              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{
                    width: `${provisionalState.expected_count > 0 ? (provisionalState.present_count / provisionalState.expected_count * 100).toFixed(1) : 0}%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Group Photo Upload Box */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginBottom: "24px" }}>
            <div className="dropzone" onClick={() => document.getElementById("group-photo-input")?.click()}>
              <input
                id="group-photo-input"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                style={{ display: "none" }}
                onChange={handlePhotoFileChange}
              />
              <div style={{ fontSize: "32px", marginBottom: "8px" }}>📸</div>
              <strong>{groupPhotoFile ? groupPhotoFile.name : "Select or Drop Classroom Group Photo"}</strong>
              <small>{groupPhotoFile ? `${(groupPhotoFile.size / 1024).toFixed(1)} KB` : "Supports multi-face photos of student rows"}</small>
            </div>

            <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: "10px" }}>
              <div style={{ fontSize: "12px", color: "var(--ink-soft)" }}>
                Take or upload multiple group photos covering different classroom sections. The system unites them into this session without duplicate records.
              </div>
              <button
                className="button button-primary"
                disabled={!groupPhotoFile || isUploadingGroupPhoto}
                onClick={() => void uploadWebGroupPhoto()}
              >
                {isUploadingGroupPhoto ? "Detecting Faces & Matching Gallery…" : "⚡ Process Group Photo"}
              </button>
            </div>
          </div>

          {/* Latest Capture Summary Banner */}
          {lastCaptureResult && (
            <div style={{ padding: "14px", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: "10px", marginBottom: "20px" }}>
              <strong>Capture #{lastCaptureResult.photo_index} Complete:</strong>{" "}
              {lastCaptureResult.faces_detected_count} faces detected, {lastCaptureResult.faces_matched_count} recognized,{" "}
              {lastCaptureResult.faces_uncertain_count} flagged for review, {lastCaptureResult.duplicates_ignored_count} cross-photo duplicates ignored.
            </div>
          )}

          {/* Provisional Roster Table */}
          {provisionalState && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div style={{ display: "flex", gap: "6px" }}>
                  <button className={`tab-btn ${rosterTab === "ALL" ? "active" : ""}`} onClick={() => setRosterTab("ALL")}>All ({provisionalState.roster.length})</button>
                  <button className={`tab-btn ${rosterTab === "PRESENT" ? "active" : ""}`} onClick={() => setRosterTab("PRESENT")}>Present ({provisionalState.present_count})</button>
                  <button className={`tab-btn ${rosterTab === "FLAGGED" ? "active" : ""}`} onClick={() => setRosterTab("FLAGGED")}>Review ({provisionalState.pending_review_count})</button>
                  <button className={`tab-btn ${rosterTab === "ABSENT" ? "active" : ""}`} onClick={() => setRosterTab("ABSENT")}>Absent ({provisionalState.unresolved_count})</button>
                </div>
                <input
                  style={{ width: "220px", padding: "6px 10px", fontSize: "12px", borderRadius: "6px", border: "1px solid var(--line)" }}
                  placeholder="Filter student or roll #"
                  value={rosterSearch}
                  onChange={(e) => setRosterSearch(e.target.value)}
                />
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Roll Number</th>
                      <th>Student Name</th>
                      <th>Dept & Cohort</th>
                      <th>Status</th>
                      <th>Match Confidence</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRoster.map((student) => (
                      <tr key={student.student_id}>
                        <td><strong>{student.student_number}</strong></td>
                        <td>{student.full_name}</td>
                        <td>{student.department_code} Y{student.year_of_study}-{student.section}</td>
                        <td>
                          <span className={`pill ${student.status === "PRESENT" ? "badge-present" : student.status === "PENDING_REVIEW" ? "badge-review" : "badge-absent"}`}>
                            {student.status}
                          </span>
                        </td>
                        <td>{student.similarity_score > 0 ? `${(student.similarity_score * 100).toFixed(1)}%` : "—"}</td>
                        <td>
                          <div style={{ display: "flex", gap: "6px" }}>
                            {student.status !== "PRESENT" ? (
                              <button
                                className="button button-small button-primary"
                                onClick={() => void toggleStudent(student, "PRESENT")}
                              >
                                Mark Present
                              </button>
                            ) : (
                              <button
                                className="button button-small button-secondary"
                                onClick={() => void toggleStudent(student, "MARKED_ABSENT")}
                              >
                                Mark Absent
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {filteredRoster.length === 0 && (
                      <tr><td colSpan={6}><div className="empty-state">No students found matching current filter</div></td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {/* CAPTURE-JOB QUEUE (FOR ASYNC KIOSK BATCH MONITORING) */}
      <section className="panel table-panel">
        <div className="table-toolbar">
          <div>
            <h3>Kiosk Batch Job History</h3>
            <p>{batches.length} hardware burst jobs for the selected session</p>
          </div>
          <label className="search-field">
            <span>Filter Status</span>
            <select value={batchStatus} onChange={(e) => setBatchStatus(e.target.value)}>
              <option value="">All states</option>
              {["QUEUED", "PROCESSING", "SUCCEEDED", "REJECTED", "FAILED"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Batch ID</th>
                <th>Frames</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {batches.filter((b) => !batchStatus || b.status === batchStatus).map((batch) => (
                <tr key={batch.batch_id}>
                  <td><code>{batch.batch_id.slice(0, 12)}</code></td>
                  <td>{batch.frame_count}</td>
                  <td>
                    <span className={`pill ${batch.status === "SUCCEEDED" ? "pill-success" : batch.status === "FAILED" ? "pill-warning" : "pill-muted"}`}>
                      {batch.status}
                    </span>
                  </td>
                  <td>{batch.attempts} / {batch.max_attempts}</td>
                  <td>{new Date(batch.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {batches.length === 0 && (
                <tr><td colSpan={5}><div className="empty-state">No kiosk batch jobs for this session</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
