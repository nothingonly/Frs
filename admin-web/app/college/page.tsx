"use client";

/* eslint react-hooks/set-state-in-effect: off -- These effects initiate external HTTP reads; state updates occur in async handlers. */

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useAdmin } from "@/components/admin-provider";

type DepartmentRecord = { department_id: string; code: string; name: string; is_active: boolean };
type ClassGroupRecord = {
  class_group_id: string; department_id: string; department_code: string; department_name: string;
  year_of_study: number; section: string; academic_year: string; is_active: boolean; active_enrollments: number;
};
type Membership = {
  class_group_id: string; department_code: string; year_of_study: number; section: string; academic_year: string;
};
type StudentRecord = {
  student_id: string; student_number: string; full_name: string; email: string | null;
  person_id: string | null; is_active: boolean; class_groups: Membership[];
};
type Items<T> = { items: T[] };

export default function CollegeSetupPage() {
  const { isConnected, requestJson } = useAdmin();
  const [departments, setDepartments] = useState<DepartmentRecord[]>([]);
  const [groups, setGroups] = useState<ClassGroupRecord[]>([]);
  const [students, setStudents] = useState<StudentRecord[]>([]);
  const [departmentCode, setDepartmentCode] = useState("");
  const [departmentName, setDepartmentName] = useState("");
  const [groupDepartment, setGroupDepartment] = useState("");
  const [yearOfStudy, setYearOfStudy] = useState("1");
  const [section, setSection] = useState("A");
  const [academicYear, setAcademicYear] = useState("");
  const [studentNumber, setStudentNumber] = useState("");
  const [studentName, setStudentName] = useState("");
  const [studentEmail, setStudentEmail] = useState("");
  const [studentGroup, setStudentGroup] = useState("");
  const [filterGroup, setFilterGroup] = useState("");
  const [filterText, setFilterText] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isConnected) return;
    setLoading(true);
    setError(null);
    try {
      const result = await Promise.all([
        requestJson<Items<DepartmentRecord>>("/api/v1/admin/college/departments?active_only=false"),
        requestJson<Items<ClassGroupRecord>>("/api/v1/admin/college/class-groups?active_only=false"),
        requestJson<Items<StudentRecord>>("/api/v1/admin/college/students?active_only=false&limit=200"),
      ]);
      setDepartments(result[0].items);
      setGroups(result[1].items);
      setStudents(result[2].items);
      setGroupDepartment((current) => current || result[0].items[0]?.department_id || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load college records.");
    } finally {
      setLoading(false);
    }
  }, [isConnected, requestJson]);

  useEffect(() => { if (isConnected) void refresh(); }, [isConnected, refresh]);

  const visibleStudents = useMemo(() => {
    const query = filterText.trim().toLowerCase();
    return students.filter((student) => {
      const matchesQuery = !query || [student.student_number, student.full_name, student.email || ""]
        .some((value) => value.toLowerCase().includes(query));
      const matchesGroup = !filterGroup || student.class_groups.some((group) => group.class_group_id === filterGroup);
      return matchesQuery && matchesGroup;
    });
  }, [students, filterText, filterGroup]);

  async function submitDepartment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving("department"); setError(null); setNotice(null);
    try {
      const created = await requestJson<DepartmentRecord>("/api/v1/admin/college/departments", {
        method: "POST", body: JSON.stringify({ code: departmentCode, name: departmentName }),
      });
      setDepartmentCode(""); setDepartmentName(""); setNotice("Department " + created.code + " created.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create department.");
    } finally { setSaving(null); }
  }

  async function submitClassGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving("class"); setError(null); setNotice(null);
    try {
      const created = await requestJson<ClassGroupRecord>("/api/v1/admin/college/class-groups", {
        method: "POST",
        body: JSON.stringify({
          department_id: groupDepartment, year_of_study: Number(yearOfStudy),
          section, academic_year: academicYear,
        }),
      });
      setNotice(created.department_code + " year " + created.year_of_study + ", section " + created.section + " created for " + created.academic_year + ".");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create class group.");
    } finally { setSaving(null); }
  }

  async function submitStudent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving("student"); setError(null); setNotice(null);
    try {
      const created = await requestJson<StudentRecord>("/api/v1/admin/college/students", {
        method: "POST",
        body: JSON.stringify({
          student_number: studentNumber, full_name: studentName,
          email: studentEmail || null, class_group_id: studentGroup || null,
        }),
      });
      setStudentNumber(""); setStudentName(""); setStudentEmail("");
      setNotice("Student " + created.student_number + " created. Biometric identity " + (created.person_id ? "linked." : "pending."));
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create student.");
    } finally { setSaving(null); }
  }

  async function withdraw(student: StudentRecord, groupId: string) {
    if (!window.confirm("Withdraw " + student.student_number + " from this class group? An audit/history record is kept.")) return;
    setSaving(student.student_id); setError(null); setNotice(null);
    try {
      await requestJson("/api/v1/admin/college/class-groups/" + encodeURIComponent(groupId) + "/students/" + encodeURIComponent(student.student_id), { method: "DELETE" });
      setNotice("Student " + student.student_number + " withdrawn from the class group.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not withdraw student.");
    } finally { setSaving(null); }
  }

  async function enrollInClass(student: StudentRecord, groupId: string) {
    if (!groupId) return;
    setSaving(student.student_id); setError(null); setNotice(null);
    try {
      await requestJson("/api/v1/admin/college/class-groups/" + encodeURIComponent(groupId) + "/students/" + encodeURIComponent(student.student_id), { method: "POST" });
      setNotice("Student " + student.student_number + " enrolled in class group.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not enroll student in class group.");
    } finally { setSaving(null); }
  }

  return (
    <>
      <section className="welcome-row">
        <div><div className="eyebrow">INSTITUTION SETUP</div><h2>College hierarchy</h2><p>Manage departments, academic year cohorts, sections and student enrollment using persisted backend records.</p></div>
        <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={!isConnected || loading}>{loading ? "Loading…" : "↻ Refresh"}</button>
      </section>
      {!isConnected ? <div className="notice notice-info"><strong>Administrator connection required</strong><span>Connect to FastAPI using the sidebar. No example departments or students are inserted automatically.</span></div> : null}
      {error ? <div className="notice notice-error" role="alert"><strong>Request failed</strong><span>{error}</span></div> : null}
      {notice ? <div className="notice notice-success" role="status"><strong>Saved</strong><span>{notice}</span></div> : null}

      <section className="college-forms">
        <article className="panel form-panel">
          <div className="form-index">01 / DEPARTMENT</div><h3>Create department</h3><p className="panel-description">Use a unique code, for example CSE, CSD, IT, MECH, CIVIL, EEE or ECE.</p>
          <form className="stack-form" onSubmit={(event) => void submitDepartment(event)}>
            <label>Department code<input required minLength={2} maxLength={12} value={departmentCode} onChange={(event) => setDepartmentCode(event.target.value.toUpperCase())} placeholder="CSE" /></label>
            <label>Department name<input required minLength={2} maxLength={160} value={departmentName} onChange={(event) => setDepartmentName(event.target.value)} placeholder="Computer Science and Engineering" /></label>
            <button className="button button-primary" disabled={!isConnected || saving !== null}>{saving === "department" ? "Saving…" : "Create department"}</button>
          </form>
        </article>

        <article className="panel form-panel">
          <div className="form-index">02 / CLASS GROUP</div><h3>Create class group</h3><p className="panel-description">Year of study is 1–4; academic year is a range such as 2026-2027.</p>
          <form className="stack-form" onSubmit={(event) => void submitClassGroup(event)}>
            <label>Department<select required value={groupDepartment} onChange={(event) => setGroupDepartment(event.target.value)}><option value="">Select department</option>{departments.map((dept) => <option key={dept.department_id} value={dept.department_id}>{dept.code} · {dept.name}</option>)}</select></label>
            <div className="split-fields">
              <label>Year<select value={yearOfStudy} onChange={(event) => setYearOfStudy(event.target.value)}>{[1, 2, 3, 4].map((year) => <option key={year} value={year}>{year}{year === 1 ? "st" : year === 2 ? "nd" : year === 3 ? "rd" : "th"} year</option>)}</select></label>
              <label>Section<input required maxLength={20} value={section} onChange={(event) => setSection(event.target.value.toUpperCase())} placeholder="A" /></label>
            </div>
            <label>Academic year<input required minLength={9} maxLength={9} pattern="[0-9]{4}-[0-9]{4}" value={academicYear} onChange={(event) => setAcademicYear(event.target.value)} placeholder="2026-2027" /></label>
            <button className="button button-primary" disabled={!isConnected || departments.length === 0 || saving !== null}>{saving === "class" ? "Saving…" : "Create class group"}</button>
            {departments.length === 0 ? <small>Create a department first.</small> : null}
          </form>
        </article>

        <article className="panel form-panel">
          <div className="form-index">03 / STUDENT</div><h3>Add student</h3><p className="panel-description">Creates a student record and linked biometric identity. Enrollment images and embeddings are a separate step.</p>
          <form className="stack-form" onSubmit={(event) => void submitStudent(event)}>
            <label>Student number<input required minLength={1} maxLength={80} value={studentNumber} onChange={(event) => setStudentNumber(event.target.value.toUpperCase())} placeholder="CSE23001" /></label>
            <label>Full name<input required minLength={1} maxLength={200} value={studentName} onChange={(event) => setStudentName(event.target.value)} placeholder="Student full name" /></label>
            <label>Email (optional)<input type="email" maxLength={254} value={studentEmail} onChange={(event) => setStudentEmail(event.target.value)} placeholder="student@college.edu" /></label>
            <label>Assign to class (optional)<select value={studentGroup} onChange={(event) => setStudentGroup(event.target.value)}><option value="">Unassigned</option>{groups.filter((group) => group.is_active).map((group) => <option key={group.class_group_id} value={group.class_group_id}>{group.department_code} · Year {group.year_of_study} · {group.section} · {group.academic_year}</option>)}</select></label>
            <button className="button button-primary" disabled={!isConnected || saving !== null}>{saving === "student" ? "Saving…" : "Add student"}</button>
          </form>
        </article>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">PERSISTED STRUCTURE</span><h3>Departments and class groups</h3></div><span className="panel-note">{departments.length} departments · {groups.length} class groups</span></div>
        {departments.length === 0 ? <div className="empty-state"><strong>No departments configured</strong><span>Create your first department above. Nothing is pre-seeded.</span></div> : <div className="department-list">{departments.map((dept) => {
          const deptGroups = groups.filter((group) => group.department_id === dept.department_id);
          return <div className="department-item" key={dept.department_id}>
            <div className="department-icon">{dept.code.slice(0, 3)}</div>
            <div className="department-main"><strong>{dept.code} <span>{dept.name}</span></strong><small>{deptGroups.length} class groups</small>
              {deptGroups.length > 0 ? <div className="class-chip-list">{deptGroups.map((group) => <span className="class-chip" key={group.class_group_id}>Year {group.year_of_study} · Section {group.section} · {group.academic_year} <b>{group.active_enrollments} students</b></span>)}</div> : null}
            </div>
          </div>;
        })}</div>}
      </section>

      <section className="panel table-panel">
        <div className="table-toolbar"><div><h3>Student roster</h3><p>{students.length} students loaded · latest response capped at 200</p></div>
          <div className="roster-filters">
            <label className="search-field"><span>Search</span><input value={filterText} onChange={(event) => setFilterText(event.target.value)} placeholder="Student number or name" /></label>
            <label className="search-field"><span>Class</span><select value={filterGroup} onChange={(event) => setFilterGroup(event.target.value)}><option value="">All classes</option>{groups.map((group) => <option key={group.class_group_id} value={group.class_group_id}>{group.department_code} · Y{group.year_of_study}-{group.section} · {group.academic_year}</option>)}</select></label>
          </div>
        </div>
        <div className="table-wrap"><table><thead><tr><th>Student</th><th>Class enrollment</th><th>Biometric record</th><th>Status</th><th>Action</th></tr></thead><tbody>
          {visibleStudents.map((student) => <tr key={student.student_id}>
            <td><div className="person-cell"><span className="avatar">{student.full_name.charAt(0).toUpperCase()}</span><span><strong>{student.full_name}</strong><small>{student.student_number}{student.email ? " · " + student.email : ""}</small></span></div></td>
            <td>{student.class_groups.length ? student.class_groups.map((group) => <span className="class-chip class-chip-inline" key={group.class_group_id}>{group.department_code} · Y{group.year_of_study}-{group.section} · {group.academic_year}<button type="button" aria-label={"Withdraw " + student.student_number + " from " + group.department_code + " year " + group.year_of_study + " section " + group.section} onClick={() => void withdraw(student, group.class_group_id)} disabled={saving !== null}>×</button></span>) : <span className="cell-subtext">Unassigned</span>}</td>
            <td>{student.person_id ? <span className="pill pill-success">Linked</span> : <span className="pill pill-warning">Unlinked</span>}<small className="cell-subtext">{student.person_id ? student.person_id.slice(0, 8) : "Enrollment pending"}</small></td>
            <td><span className={student.is_active ? "pill pill-success" : "pill pill-muted"}>{student.is_active ? "Active" : "Inactive"}</span></td>
            <td>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <Link
                  href={"/enrollment?student_number=" + encodeURIComponent(student.student_number) + "&full_name=" + encodeURIComponent(student.full_name)}
                  className="button button-small button-secondary"
                  style={{ textDecoration: "none", whiteSpace: "nowrap" }}
                >
                  {student.person_id ? "Biometrics" : "Enroll"}
                </Link>
                {student.class_groups.length === 0 ? (
                  <select
                    style={{ fontSize: "0.75rem", padding: "2px 4px", maxWidth: "140px" }}
                    defaultValue=""
                    disabled={saving === student.student_id}
                    onChange={(e) => {
                      if (e.target.value) void enrollInClass(student, e.target.value);
                    }}
                  >
                    <option value="">+ Assign class</option>
                    {groups.filter((g) => g.is_active).map((g) => (
                      <option key={g.class_group_id} value={g.class_group_id}>
                        {g.department_code} Y{g.year_of_study}-{g.section}
                      </option>
                    ))}
                  </select>
                ) : null}
              </div>
            </td>
          </tr>)}
          {visibleStudents.length === 0 ? <tr><td colSpan={5}><div className="empty-state"><strong>{loading ? "Loading students…" : "No matching students"}</strong><span>Records appear here after creation through this page or API.</span></div></td></tr> : null}
        </tbody></table></div>
      </section>
      <p className="compliance-note">Student creation adds a roster identity but does not enroll a face image or produce an embedding. Handle student biometric data only under the institution approved notice, access and retention policy.</p>
    </>
  );
}
