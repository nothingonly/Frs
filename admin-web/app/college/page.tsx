"use client";

/* eslint react-hooks/set-state-in-effect: off -- These effects initiate external HTTP reads; state updates occur in async handlers. */

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ChangeEvent } from "react";
import Link from "next/link";
import { useAdmin } from "@/components/admin-provider";

type DepartmentRecord = { department_id: string; code: string; name: string; is_active: boolean };
type ClassGroupRecord = {
  class_group_id: string; department_id: string; department_code: string; department_name: string;
  year_of_study: number; section: string; academic_year: string; is_active: boolean; active_enrollments: number;
  semester?: number | null; is_lab?: boolean; lab_name?: string | null;
};
type Membership = {
  class_group_id: string; department_code: string; year_of_study: number; section: string; academic_year: string;
  semester?: number | null; is_lab?: boolean; lab_name?: string | null;
};
type StudentRecord = {
  student_id: string; student_number: string; full_name: string; email: string | null;
  person_id: string | null; is_active: boolean; class_groups: Membership[];
};
type Items<T> = { items: T[] };

type BulkImportRow = {
  row_number: number;
  student_number: string;
  full_name: string;
  email: string | null;
  department_code: string;
  year_of_study: number;
  section: string;
  semester: number | null;
  academic_year: string;
  is_lab: boolean;
  lab_name: string | null;
  is_valid: boolean;
  error_message: string | null;
};

type BulkImportResult = {
  status: string;
  dry_run: boolean;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  imported_count: number;
  preview: BulkImportRow[];
  errors: string[];
};

type BulkPhotoItemResult = {
  filename: string;
  student_number: string;
  status: "ENROLLED" | "SKIPPED_NO_FACE" | "SKIPPED_MULTIPLE_FACES" | "SKIPPED_NOT_FOUND" | "FAILED";
  message: string;
  sharpness: number;
};

type BulkPhotoResult = {
  status: string;
  total_processed: number;
  enrolled_count: number;
  skipped_count: number;
  ambiguous_count: number;
  results: BulkPhotoItemResult[];
};

export default function CollegeSetupPage() {
  const { isConnected, requestJson } = useAdmin();
  const [activeTab, setActiveTab] = useState<"hierarchy" | "bulk-import" | "bulk-photos">("hierarchy");

  // Data states
  const [departments, setDepartments] = useState<DepartmentRecord[]>([]);
  const [groups, setGroups] = useState<ClassGroupRecord[]>([]);
  const [students, setStudents] = useState<StudentRecord[]>([]);

  // Hierarchy form states
  const [departmentCode, setDepartmentCode] = useState("");
  const [departmentName, setDepartmentName] = useState("");
  const [groupDepartment, setGroupDepartment] = useState("");
  const [yearOfStudy, setYearOfStudy] = useState("1");
  const [section, setSection] = useState("A");
  const [semester, setSemester] = useState("1");
  const [isLab, setIsLab] = useState(false);
  const [labName, setLabName] = useState("");
  const [academicYear, setAcademicYear] = useState("2026-2027");

  // Single student form
  const [studentNumber, setStudentNumber] = useState("");
  const [studentName, setStudentName] = useState("");
  const [studentEmail, setStudentEmail] = useState("");
  const [studentGroup, setStudentGroup] = useState("");

  // Filtering
  const [filterGroup, setFilterGroup] = useState("");
  const [filterText, setFilterText] = useState("");

  // Bulk CSV import states
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [bulkImportResult, setBulkImportResult] = useState<BulkImportResult | null>(null);
  const [isDryRun, setIsDryRun] = useState(true);
  const [isImporting, setIsImporting] = useState(false);

  // Bulk photo enrollment states
  const [photoFiles, setPhotoFiles] = useState<File[]>([]);
  const [bulkPhotoResult, setBulkPhotoResult] = useState<BulkPhotoResult | null>(null);
  const [isEnrollingPhotos, setIsEnrollingPhotos] = useState(false);

  // Status / Loading
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
        requestJson<Items<StudentRecord>>("/api/v1/admin/college/students?active_only=false&limit=300"),
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

  async function seedDefaultDepartments() {
    setSaving("seed"); setError(null); setNotice(null);
    try {
      const result = await requestJson<{ message: string; departments: DepartmentRecord[] }>(
        "/api/v1/admin/college/departments/seed-defaults",
        { method: "POST" }
      );
      setNotice(result.message);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not seed default departments.");
    } finally { setSaving(null); }
  }

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
          department_id: groupDepartment,
          year_of_study: Number(yearOfStudy),
          section,
          semester: Number(semester),
          is_lab: isLab,
          lab_name: isLab ? labName.trim() : null,
          academic_year: academicYear,
        }),
      });
      setNotice(created.department_code + " Year " + created.year_of_study + ", Section " + created.section + (created.is_lab ? " (Lab: " + created.lab_name + ")" : "") + " created.");
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

  // Bulk CSV Import handlers
  function handleCsvFileSelect(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      setCsvFile(e.target.files[0]);
      setBulkImportResult(null);
    }
  }

  async function submitBulkImport(dryRun: boolean) {
    if (!csvFile) return;
    setIsImporting(true);
    setError(null);
    setNotice(null);
    try {
      const formData = new FormData();
      formData.append("file", csvFile);
      const result = await requestJson<BulkImportResult>(
        `/api/v1/admin/college/students/bulk-import?dry_run=${dryRun}`,
        { method: "POST", body: formData }
      );
      setBulkImportResult(result);
      if (!dryRun) {
        setNotice(`Bulk import successful: ${result.imported_count} students enrolled.`);
        await refresh();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bulk import failed.");
    } finally {
      setIsImporting(false);
    }
  }

  // Bulk Photo Enrollment handlers
  function handlePhotoFilesSelect(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      setPhotoFiles(Array.from(e.target.files));
      setBulkPhotoResult(null);
    }
  }

  async function submitBulkPhotoEnrollment() {
    if (photoFiles.length === 0) return;
    setIsEnrollingPhotos(true);
    setError(null);
    setNotice(null);
    try {
      const formData = new FormData();
      for (const file of photoFiles) {
        formData.append("photos", file);
      }
      const result = await requestJson<BulkPhotoResult>(
        "/api/v1/admin/college/students/bulk-enroll-photos",
        { method: "POST", body: formData }
      );
      setBulkPhotoResult(result);
      setNotice(`Biometric enrollment complete: ${result.enrolled_count} faces enrolled, ${result.skipped_count} skipped.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bulk photo enrollment failed.");
    } finally {
      setIsEnrollingPhotos(false);
    }
  }

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">INSTITUTION SETUP & ENROLLMENT</div>
          <h2>College Academic Architecture</h2>
          <p>Configure 7 engineering departments (CSE, CSD, MECH, CIVIL, IT, ECE, EEE), B.Tech years (1–4), semesters (1–8), sections (A–D), labs, and bulk enrollment.</p>
        </div>
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => void seedDefaultDepartments()}
            disabled={!isConnected || saving !== null}
          >
            {saving === "seed" ? "Seeding…" : "⚡ Seed 7 Engineering Departments"}
          </button>
          <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={!isConnected || loading}>
            {loading ? "Loading…" : "↻ Refresh"}
          </button>
        </div>
      </section>

      {!isConnected ? (
        <div className="notice notice-info">
          <strong>Administrator connection required</strong>
          <span>Connect to FastAPI in the sidebar to configure academic hierarchy and enroll students.</span>
        </div>
      ) : null}
      {error ? <div className="notice notice-error" role="alert"><strong>Request failed</strong><span>{error}</span></div> : null}
      {notice ? <div className="notice notice-success" role="status"><strong>Saved</strong><span>{notice}</span></div> : null}

      {/* Tabs */}
      <div className="tab-bar">
        <button
          className={`tab-btn ${activeTab === "hierarchy" ? "active" : ""}`}
          onClick={() => setActiveTab("hierarchy")}
        >
          🏛️ Structure & Cohorts
        </button>
        <button
          className={`tab-btn ${activeTab === "bulk-import" ? "active" : ""}`}
          onClick={() => setActiveTab("bulk-import")}
        >
          📑 Bulk CSV Student Import
        </button>
        <button
          className={`tab-btn ${activeTab === "bulk-photos" ? "active" : ""}`}
          onClick={() => setActiveTab("bulk-photos")}
        >
          📸 Bulk Biometric Photo Enrollment
        </button>
      </div>

      {/* TAB 1: ACADEMIC HIERARCHY */}
      {activeTab === "hierarchy" && (
        <>
          <section className="college-forms">
            <article className="panel form-panel">
              <div className="form-index">01 / DEPARTMENT</div>
              <h3>Create department</h3>
              <p className="panel-description">Standard B.Tech departments: CSE, CSD, MECH, CIVIL, IT, ECE, EEE.</p>
              <form className="stack-form" onSubmit={(event) => void submitDepartment(event)}>
                <label>Department code<input required minLength={2} maxLength={12} value={departmentCode} onChange={(event) => setDepartmentCode(event.target.value.toUpperCase())} placeholder="CSD" /></label>
                <label>Department name<input required minLength={2} maxLength={160} value={departmentName} onChange={(event) => setDepartmentName(event.target.value)} placeholder="Computer Science and Design" /></label>
                <button className="button button-primary" disabled={!isConnected || saving !== null}>{saving === "department" ? "Saving…" : "Create department"}</button>
              </form>
            </article>

            <article className="panel form-panel">
              <div className="form-index">02 / CLASS OR LAB COHORT</div>
              <h3>Create class or lab group</h3>
              <p className="panel-description">Year 1–4, Semesters 1–8, Sections A–D, and configured laboratory sessions.</p>
              <form className="stack-form" onSubmit={(event) => void submitClassGroup(event)}>
                <label>Department<select required value={groupDepartment} onChange={(event) => setGroupDepartment(event.target.value)}><option value="">Select department</option>{departments.map((dept) => <option key={dept.department_id} value={dept.department_id}>{dept.code} · {dept.name}</option>)}</select></label>
                <div className="split-fields">
                  <label>Academic Year<select value={yearOfStudy} onChange={(event) => setYearOfStudy(event.target.value)}>{[1, 2, 3, 4].map((year) => <option key={year} value={year}>{year}{year === 1 ? "st" : year === 2 ? "nd" : year === 3 ? "rd" : "th"} Year</option>)}</select></label>
                  <label>Semester<select value={semester} onChange={(event) => setSemester(event.target.value)}>{[1, 2, 3, 4, 5, 6, 7, 8].map((s) => <option key={s} value={s}>Semester {s}</option>)}</select></label>
                </div>
                <div className="split-fields">
                  <label>Section<input required maxLength={20} value={section} onChange={(event) => setSection(event.target.value.toUpperCase())} placeholder="A" /></label>
                  <label>Year Range<input required minLength={9} maxLength={9} pattern="[0-9]{4}-[0-9]{4}" value={academicYear} onChange={(event) => setAcademicYear(event.target.value)} placeholder="2026-2027" /></label>
                </div>
                <div style={{ padding: "8px 0" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                    <input type="checkbox" checked={isLab} onChange={(e) => setIsLab(e.target.checked)} />
                    <span>This cohort is a Laboratory Session</span>
                  </label>
                  {isLab && (
                    <div style={{ marginTop: "8px" }}>
                      <input
                        required
                        value={labName}
                        onChange={(e) => setLabName(e.target.value)}
                        placeholder="e.g. Computer Networks Lab (Batch B1)"
                      />
                    </div>
                  )}
                </div>
                <button className="button button-primary" disabled={!isConnected || departments.length === 0 || saving !== null}>{saving === "class" ? "Saving…" : "Create Cohort"}</button>
              </form>
            </article>

            <article className="panel form-panel">
              <div className="form-index">03 / STUDENT ENROLLMENT</div>
              <h3>Add individual student</h3>
              <p className="panel-description">Creates student roster record. Face photos can be enrolled individually or in bulk.</p>
              <form className="stack-form" onSubmit={(event) => void submitStudent(event)}>
                <label>Roll number / Student number<input required minLength={1} maxLength={80} value={studentNumber} onChange={(event) => setStudentNumber(event.target.value.toUpperCase())} placeholder="21A91A0501" /></label>
                <label>Full name<input required minLength={1} maxLength={200} value={studentName} onChange={(event) => setStudentName(event.target.value)} placeholder="Student full name" /></label>
                <label>Email (optional)<input type="email" maxLength={254} value={studentEmail} onChange={(event) => setStudentEmail(event.target.value)} placeholder="student@college.edu" /></label>
                <label>Class cohort (optional)<select value={studentGroup} onChange={(event) => setStudentGroup(event.target.value)}><option value="">Unassigned</option>{groups.filter((group) => group.is_active).map((group) => <option key={group.class_group_id} value={group.class_group_id}>{group.department_code} · Year {group.year_of_study} · Sec {group.section} {group.is_lab ? "· Lab: " + group.lab_name : ""}</option>)}</select></label>
                <button className="button button-primary" disabled={!isConnected || saving !== null}>{saving === "student" ? "Saving…" : "Add student"}</button>
              </form>
            </article>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">PERSISTED HIERARCHY</span>
                <h3>Departments and Class/Lab Cohorts</h3>
              </div>
              <span className="panel-note">{departments.length} departments · {groups.length} class groups</span>
            </div>
            {departments.length === 0 ? (
              <div className="empty-state">
                <strong>No departments configured</strong>
                <span>Click "Seed 7 Engineering Departments" above or create your first department.</span>
              </div>
            ) : (
              <div className="department-list">
                {departments.map((dept) => {
                  const deptGroups = groups.filter((group) => group.department_id === dept.department_id);
                  return (
                    <div className="department-item" key={dept.department_id}>
                      <div className="department-icon">{dept.code.slice(0, 3)}</div>
                      <div className="department-main">
                        <strong>{dept.code} <span>{dept.name}</span></strong>
                        <small>{deptGroups.length} cohorts</small>
                        {deptGroups.length > 0 ? (
                          <div className="class-chip-list">
                            {deptGroups.map((group) => (
                              <span
                                className={`class-chip ${group.is_lab ? "badge-lab" : "badge-class"}`}
                                key={group.class_group_id}
                              >
                                {group.is_lab ? "🔬 " + group.lab_name : `Year ${group.year_of_study} · Sec ${group.section} · Sem ${group.semester ?? 1}`}
                                <b>{group.active_enrollments} students</b>
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <section className="panel table-panel">
            <div className="table-toolbar">
              <div><h3>Student Roster</h3><p>{students.length} students enrolled in college database</p></div>
              <div className="roster-filters">
                <label className="search-field"><span>Search</span><input value={filterText} onChange={(event) => setFilterText(event.target.value)} placeholder="Roll number or name" /></label>
                <label className="search-field"><span>Cohort</span><select value={filterGroup} onChange={(event) => setFilterGroup(event.target.value)}><option value="">All cohorts</option>{groups.map((group) => <option key={group.class_group_id} value={group.class_group_id}>{group.department_code} · Y{group.year_of_study}-{group.section} {group.is_lab ? "· Lab" : ""}</option>)}</select></label>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Student</th>
                    <th>Class & Lab Enrollments</th>
                    <th>Biometric Record</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleStudents.map((student) => (
                    <tr key={student.student_id}>
                      <td>
                        <div className="person-cell">
                          <span className="avatar">{student.full_name.charAt(0).toUpperCase()}</span>
                          <span><strong>{student.full_name}</strong><small>{student.student_number}{student.email ? " · " + student.email : ""}</small></span>
                        </div>
                      </td>
                      <td>
                        {student.class_groups.length ? (
                          student.class_groups.map((group) => (
                            <span
                              className={`class-chip class-chip-inline ${group.is_lab ? "badge-lab" : "badge-class"}`}
                              key={group.class_group_id}
                            >
                              {group.department_code} · Y{group.year_of_study}-{group.section}
                              {group.is_lab ? " (Lab)" : ""}
                              <button
                                type="button"
                                title="Withdraw from class"
                                onClick={() => void withdraw(student, group.class_group_id)}
                                disabled={saving !== null}
                              >
                                ×
                              </button>
                            </span>
                          ))
                        ) : (
                          <span className="cell-subtext">Unassigned</span>
                        )}
                      </td>
                      <td>
                        {student.person_id ? <span className="pill pill-success">Biometric Enrolled</span> : <span className="pill pill-warning">Pending Photo</span>}
                      </td>
                      <td><span className={student.is_active ? "pill pill-success" : "pill pill-muted"}>{student.is_active ? "Active" : "Inactive"}</span></td>
                      <td>
                        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                          <Link
                            href={"/enrollment?student_number=" + encodeURIComponent(student.student_number) + "&full_name=" + encodeURIComponent(student.full_name)}
                            className="button button-small button-secondary"
                            style={{ textDecoration: "none", whiteSpace: "nowrap" }}
                          >
                            {student.person_id ? "Re-enroll" : "Enroll Face"}
                          </Link>
                          {student.class_groups.length < 2 ? (
                            <select
                              style={{ fontSize: "0.75rem", padding: "2px 4px", maxWidth: "140px" }}
                              defaultValue=""
                              disabled={saving === student.student_id}
                              onChange={(e) => {
                                if (e.target.value) void enrollInClass(student, e.target.value);
                              }}
                            >
                              <option value="">+ Assign Cohort</option>
                              {groups.filter((g) => g.is_active).map((g) => (
                                <option key={g.class_group_id} value={g.class_group_id}>
                                  {g.department_code} Y{g.year_of_study}-{g.section} {g.is_lab ? "(Lab)" : ""}
                                </option>
                              ))}
                            </select>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {visibleStudents.length === 0 ? (
                    <tr><td colSpan={5}><div className="empty-state"><strong>{loading ? "Loading students…" : "No matching students found"}</strong></div></td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {/* TAB 2: BULK CSV STUDENT IMPORT */}
      {activeTab === "bulk-import" && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">HIGH-VOLUME ONBOARDING</span>
              <h3>Bulk Student CSV / Excel Import</h3>
            </div>
          </div>
          <p className="panel-description">
            Upload student records in CSV format. The system automatically creates student profiles and assigns them to their
            specified department, academic year, section, semester, and lab groups.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginBottom: "20px" }}>
            <div className="dropzone" onClick={() => document.getElementById("csv-file-input")?.click()}>
              <input
                id="csv-file-input"
                type="file"
                accept=".csv,.xlsx"
                style={{ display: "none" }}
                onChange={handleCsvFileSelect}
              />
              <div style={{ fontSize: "32px", marginBottom: "8px" }}>📄</div>
              <strong>{csvFile ? csvFile.name : "Click to select or drop CSV file"}</strong>
              <small>{csvFile ? `${(csvFile.size / 1024).toFixed(1)} KB` : "Supports columns: roll_number, full_name, email, department, year, section, semester, is_lab, lab_name"}</small>
            </div>

            <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: "12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <input
                  type="checkbox"
                  id="dry-run-checkbox"
                  checked={isDryRun}
                  onChange={(e) => setIsDryRun(e.target.checked)}
                />
                <label htmlFor="dry-run-checkbox" style={{ cursor: "pointer", fontWeight: "600", fontSize: "13px" }}>
                  Dry-Run Preview Mode (validate data without persisting)
                </label>
              </div>

              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  className="button button-secondary"
                  disabled={!csvFile || isImporting}
                  onClick={() => void submitBulkImport(true)}
                >
                  {isImporting && isDryRun ? "Validating…" : "🔍 Validate & Preview CSV"}
                </button>
                <button
                  className="button button-primary"
                  disabled={!csvFile || isImporting}
                  onClick={() => void submitBulkImport(false)}
                >
                  {isImporting && !isDryRun ? "Importing…" : "🚀 Confirm & Import Students"}
                </button>
              </div>

              {csvFile && (
                <small style={{ color: "#0d9488" }}>
                  Ready to process <strong>{csvFile.name}</strong>
                </small>
              )}
            </div>
          </div>

          {/* Import Results / Validation Preview */}
          {bulkImportResult && (
            <div style={{ marginTop: "24px" }}>
              <div style={{ display: "flex", gap: "16px", marginBottom: "16px" }}>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">TOTAL ROWS</div>
                  <span className="stat-value">{bulkImportResult.total_rows}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">VALID ROWS</div>
                  <span className="stat-value" style={{ color: "#10b981" }}>{bulkImportResult.valid_rows}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">INVALID ROWS</div>
                  <span className="stat-value" style={{ color: bulkImportResult.invalid_rows > 0 ? "#ef4444" : "#64748b" }}>
                    {bulkImportResult.invalid_rows}
                  </span>
                </div>
                {!bulkImportResult.dry_run && (
                  <div className="stat-card" style={{ flex: 1 }}>
                    <div className="stat-top">IMPORTED</div>
                    <span className="stat-value" style={{ color: "#0d9488" }}>{bulkImportResult.imported_count}</span>
                  </div>
                )}
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Roll Number</th>
                      <th>Full Name</th>
                      <th>Department</th>
                      <th>Year / Sec</th>
                      <th>Semester</th>
                      <th>Cohort Type</th>
                      <th>Validation Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bulkImportResult.preview.map((row) => (
                      <tr key={row.row_number}>
                        <td>{row.row_number}</td>
                        <td><strong>{row.student_number}</strong></td>
                        <td>{row.full_name}</td>
                        <td>{row.department_code}</td>
                        <td>Year {row.year_of_study} - {row.section}</td>
                        <td>{row.semester ? `Sem ${row.semester}` : "—"}</td>
                        <td>
                          <span className={`pill ${row.is_lab ? "badge-lab" : "badge-class"}`}>
                            {row.is_lab ? `Lab: ${row.lab_name}` : "Theory Class"}
                          </span>
                        </td>
                        <td>
                          {row.is_valid ? (
                            <span className="pill pill-success">Valid</span>
                          ) : (
                            <span className="pill pill-warning" title={row.error_message || ""}>
                              {row.error_message || "Validation Error"}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {/* TAB 3: BULK BIOMETRIC PHOTO ENROLLMENT */}
      {activeTab === "bulk-photos" && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">BIOMETRIC ENROLLMENT</span>
              <h3>Bulk Student Photo Enrollment</h3>
            </div>
          </div>
          <p className="panel-description">
            Upload facial photos of students named after their roll number (e.g. <code>21A91A0501.jpg</code>, <code>21A91A0502.png</code>).
            The vision pipeline extracts single-face SCRFD bounding boxes, generates 512-d ArcFace embeddings, and securely encrypts them.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginBottom: "20px" }}>
            <div className="dropzone" onClick={() => document.getElementById("photo-files-input")?.click()}>
              <input
                id="photo-files-input"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                style={{ display: "none" }}
                onChange={handlePhotoFilesSelect}
              />
              <div style={{ fontSize: "32px", marginBottom: "8px" }}>📷</div>
              <strong>{photoFiles.length > 0 ? `${photoFiles.length} photos selected` : "Select or Drop Student Photos"}</strong>
              <small>File names must correspond to student roll numbers (e.g. 21A91A0501.jpg)</small>
            </div>

            <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: "12px" }}>
              <div style={{ fontSize: "13px", color: "var(--ink-soft)" }}>
                Selected: <strong>{photoFiles.length}</strong> photo files
              </div>
              <button
                className="button button-primary"
                disabled={photoFiles.length === 0 || isEnrollingPhotos}
                onClick={() => void submitBulkPhotoEnrollment()}
              >
                {isEnrollingPhotos ? "Enrolling Faces & Extracting Embeddings…" : "⚡ Process & Enroll Biometrics"}
              </button>
            </div>
          </div>

          {/* Results Dashboard */}
          {bulkPhotoResult && (
            <div style={{ marginTop: "24px" }}>
              <div style={{ display: "flex", gap: "16px", marginBottom: "16px" }}>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">PROCESSED</div>
                  <span className="stat-value">{bulkPhotoResult.total_processed}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">ENROLLED</div>
                  <span className="stat-value" style={{ color: "#10b981" }}>{bulkPhotoResult.enrolled_count}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">AMBIGUOUS (MULTI-FACE)</div>
                  <span className="stat-value" style={{ color: "#f59e0b" }}>{bulkPhotoResult.ambiguous_count}</span>
                </div>
                <div className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-top">SKIPPED / NOT FOUND</div>
                  <span className="stat-value" style={{ color: "#64748b" }}>{bulkPhotoResult.skipped_count}</span>
                </div>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Filename</th>
                      <th>Mapped Roll Number</th>
                      <th>Enrollment Status</th>
                      <th>Face Sharpness</th>
                      <th>Message / Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bulkPhotoResult.results.map((item, idx) => (
                      <tr key={idx}>
                        <td><code>{item.filename}</code></td>
                        <td><strong>{item.student_number}</strong></td>
                        <td>
                          {item.status === "ENROLLED" ? (
                            <span className="pill pill-success">Enrolled</span>
                          ) : item.status === "SKIPPED_MULTIPLE_FACES" ? (
                            <span className="pill pill-warning">Multiple Faces</span>
                          ) : (
                            <span className="pill pill-muted">{item.status}</span>
                          )}
                        </td>
                        <td>{item.sharpness > 0 ? `${item.sharpness.toFixed(1)} var` : "—"}</td>
                        <td><small>{item.message}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}
    </>
  );
}
