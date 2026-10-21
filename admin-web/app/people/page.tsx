"use client";

/* eslint react-hooks/set-state-in-effect: off -- These effects initiate external HTTP reads; state changes occur in async response/error handlers. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAdmin, type ListPayload, type PersonRecord } from "@/components/admin-provider";

export default function PeoplePage() {
  const { isConnected, requestJson } = useAdmin();
  const [people, setPeople] = useState<PersonRecord[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await requestJson<ListPayload<PersonRecord>>("/api/v1/admin/people?limit=100&active_only=false");
      setPeople(payload.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the people directory.");
    } finally {
      setLoading(false);
    }
  }, [requestJson]);

  useEffect(() => { if (isConnected) void refresh(); }, [isConnected, refresh]);

  const visiblePeople = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return people;
    return people.filter((person) => [person.employee_id, person.full_name, person.department ?? ""].some((value) => value.toLowerCase().includes(query)));
  }, [people, filter]);

  async function changeStatus(person: PersonRecord) {
    setWorkingId(person.employee_id);
    setError(null);
    setNotice(null);
    try {
      await requestJson(`/api/v1/admin/people/${encodeURIComponent(person.employee_id)}/${person.is_active ? "deactivate" : "reactivate"}`, { method: "POST" });
      setNotice(`${person.employee_id} was ${person.is_active ? "deactivated" : "reactivated"} successfully.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not change person status.");
    } finally {
      setWorkingId(null);
    }
  }

  return (
    <>
      <section className="welcome-row">
        <div><div className="eyebrow">ROSTER OPERATIONS</div><h2>People directory</h2><p>Central identity registry linked with college student enrollments and encrypted biometric credentials.</p></div>
        <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={!isConnected || loading}>{loading ? "Loading…" : "↻ Refresh"}</button>
      </section>
      {!isConnected ? <div className="notice notice-info"><strong>Admin connection required</strong><span>Enter a valid administrator bearer key in the sidebar to load protected roster data.</span></div> : null}
      {error ? <div className="notice notice-error" role="alert"><strong>Request failed</strong><span>{error}</span></div> : null}
      {notice ? <div className="notice notice-success" role="status"><strong>Update complete</strong><span>{notice}</span></div> : null}
      <section className="panel table-panel">
        <div className="table-toolbar"><div><h3>People</h3><p>{people.length} records loaded · maximum 100 per request</p></div><label className="search-field"><span>Search</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Name, ID or department" /></label></div>
        <div className="table-wrap"><table><thead><tr><th>Person</th><th>Department</th><th>Enrollment</th><th>Status</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {visiblePeople.map((person) => <tr key={person.person_id}>
              <td><div className="person-cell"><span className="avatar">{person.full_name.trim().charAt(0).toUpperCase() || "?"}</span><span><strong>{person.full_name}</strong><small>{person.employee_id}</small></span></div></td>
              <td>{person.department || "—"}</td><td>v{person.enrollment_version}</td>
              <td><span className={person.is_active ? "pill pill-success" : "pill pill-muted"}>{person.is_active ? "Active" : "Inactive"}</span></td>
              <td>{new Date(person.updated_at).toLocaleString()}</td>
              <td><button className="button button-small button-secondary" disabled={workingId !== null || !isConnected} onClick={() => void changeStatus(person)}>{workingId === person.employee_id ? "Saving…" : person.is_active ? "Deactivate" : "Reactivate"}</button></td>
            </tr>)}
            {visiblePeople.length === 0 ? <tr><td colSpan={6}><div className="empty-state"><strong>{loading ? "Loading people…" : filter ? "No matching records" : "No records to display"}</strong><span>{isConnected ? "The backend returned no matching person records." : "Connect to the admin API to load real data."}</span></div></td></tr> : null}
          </tbody></table></div>
      </section>
      <p className="compliance-note">Administrative changes create backend audit events. Face images and embeddings are not displayed in this directory.</p>
    </>
  );
}
