"use client";

/* eslint react-hooks/set-state-in-effect: off -- These effects initiate external HTTP reads; state changes occur in async response/error handlers. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAdmin, type AttendanceRecord, type ListPayload } from "@/components/admin-provider";

export default function AttendancePage() {
  const { isConnected, requestJson } = useAdmin();
  const [events, setEvents] = useState<AttendanceRecord[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await requestJson<ListPayload<AttendanceRecord>>("/api/v1/admin/attendance?limit=100");
      setEvents(payload.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load attendance events.");
    } finally {
      setLoading(false);
    }
  }, [requestJson]);

  useEffect(() => { if (isConnected) void refresh(); }, [isConnected, refresh]);

  const visibleEvents = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return events;
    return events.filter((event) => [event.employee_id, event.punch_type, event.client_device_id, event.evidence_id].some((value) => value.toLowerCase().includes(query)));
  }, [events, filter]);

  return (
    <>
      <section className="welcome-row"><div><div className="eyebrow">ATTENDANCE AUDIT</div><h2>Attendance events</h2><p>Review persisted backend events and their recorded similarity/threshold evidence.</p></div><button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={!isConnected || loading}>{loading ? "Loading…" : "↻ Refresh"}</button></section>
      {!isConnected ? <div className="notice notice-info"><strong>Admin connection required</strong><span>Enter a valid administrator bearer key in the sidebar to load protected attendance events.</span></div> : null}
      {error ? <div className="notice notice-error" role="alert"><strong>Request failed</strong><span>{error}</span></div> : null}
      <section className="panel table-panel">
        <div className="table-toolbar"><div><h3>Recorded events</h3><p>{events.length} loaded · latest response capped at 100</p></div><label className="search-field"><span>Search</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Person, punch or device" /></label></div>
        <div className="table-wrap"><table><thead><tr><th>Person / ID</th><th>Event</th><th>Timestamp</th><th>Similarity</th><th>Threshold</th><th>Device</th><th>Session</th></tr></thead><tbody>
          {visibleEvents.map((event) => <tr key={event.attendance_id}>
            <td><strong>{event.employee_id}</strong><small className="cell-subtext">{event.attendance_id.slice(0, 8)}</small></td>
            <td><span className="event-pill">{event.punch_type}</span></td>
            <td>{new Date(event.timestamp).toLocaleString()}</td>
            <td className="numeric-cell">{Number(event.similarity_score).toFixed(4)}</td>
            <td className="numeric-cell">{Number(event.threshold).toFixed(4)}</td>
            <td>{event.client_device_id}</td>
          </tr>)}
          {visibleEvents.length === 0 ? <tr><td colSpan={7}><div className="empty-state"><strong>{loading ? "Loading attendance…" : filter ? "No matching events" : "No attendance events to display"}</strong><span>{isConnected ? "The backend returned no matching attendance events." : "Connect to the admin API to load real records."}</span></div></td></tr> : null}
        </tbody></table></div>
      </section>
      <p className="compliance-note">This page shows attendance events already persisted by the backend. It does not calculate or fabricate new attendance decisions.</p>
    </>
  );
}
