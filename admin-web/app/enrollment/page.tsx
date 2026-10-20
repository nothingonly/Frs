"use client";

/* eslint react-hooks/set-state-in-effect: off -- Effects initiate external HTTP reads; state changes occur in async handlers. */

import { Suspense, useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAdmin } from "@/components/admin-provider";

type StudentOption = {
  student_id: string;
  student_number: string;
  full_name: string;
  person_id: string | null;
  is_active: boolean;
  class_groups: Array<{ department_code: string; year_of_study: number; section: string; academic_year: string }>;
};

type EnrollmentResult = {
  status: string;
  person_id: string;
  employee_id: string;
  full_name: string;
  department: string | null;
  enrollment_version: number;
  accepted_sample_count: number;
  embedding_records_created: number;
  models: Record<string, number>;
  quality_metrics: {
    mean_sharpness: number | null;
    minimum_face_size_px: number;
    minimum_arcface_profile_consistency: number;
    mean_arcface_profile_consistency: number;
    model_embedding_counts: Record<string, number>;
  };
  audit_id: string;
};

type Items<T> = { items: T[] };

function BiometricEnrollmentContent() {
  const { isConnected, requestJson } = useAdmin();
  const searchParams = useSearchParams();

  const [students, setStudents] = useState<StudentOption[]>([]);
  const [selectedStudentNumber, setSelectedStudentNumber] = useState(searchParams.get("student_number") || "");
  const [fullName, setFullName] = useState(searchParams.get("full_name") || "");
  const [department, setDepartment] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);
  const [loadingStudents, setLoadingStudents] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EnrollmentResult | null>(null);

  // Load students for quick selection
  const refreshStudents = useCallback(async () => {
    if (!isConnected) return;
    setLoadingStudents(true);
    try {
      const payload = await requestJson<Items<StudentOption>>("/api/v1/admin/college/students?active_only=true&limit=300");
      setStudents(payload.items);
    } catch {
      // Non-fatal if student directory fails; manual input remains available
    } finally {
      setLoadingStudents(false);
    }
  }, [isConnected, requestJson]);

  useEffect(() => {
    if (isConnected) void refreshStudents();
  }, [isConnected, refreshStudents]);

  // Keep preview URLs in sync with selected files
  useEffect(() => {
    const urls = selectedFiles.map((file) => URL.createObjectURL(file));
    setPreviewUrls(urls);
    return () => {
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [selectedFiles]);

  const handleStudentSelect = (studentNumber: string) => {
    setSelectedStudentNumber(studentNumber);
    setError(null);
    setResult(null);
    const match = students.find((s) => s.student_number === studentNumber);
    if (match) {
      setFullName(match.full_name);
      const deptCode = match.class_groups[0]?.department_code;
      if (deptCode) setDepartment(deptCode);
    }
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setResult(null);
    if (!event.target.files) return;
    const newFiles = Array.from(event.target.files);
    // Append or replace
    setSelectedFiles((prev) => {
      const combined = [...prev, ...newFiles];
      if (combined.length > 10) {
        setError("Maximum 10 enrollment frames allowed per submission.");
        return combined.slice(0, 10);
      }
      return combined;
    });
    // Reset file input value so re-selecting same files triggers change
    event.target.value = "";
  };

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
    setError(null);
  };

  const clearFiles = () => {
    setSelectedFiles([]);
    setError(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isConnected) return;

    if (selectedFiles.length < 3) {
      setError("Multi-frame enrollment requires at least 3 distinct image frames.");
      return;
    }

    setEnrolling(true);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("employee_id", selectedStudentNumber.trim().toUpperCase());
      formData.append("full_name", fullName.trim());
      if (department.trim()) {
        formData.append("department", department.trim().toUpperCase());
      }
      for (const file of selectedFiles) {
        formData.append("images", file, file.name);
      }

      const res = await requestJson<EnrollmentResult>("/api/v1/biometrics/enroll/admin", {
        method: "POST",
        body: formData,
      });

      setResult(res);
      setSelectedFiles([]);
      await refreshStudents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enrollment failed.");
    } finally {
      setEnrolling(false);
    }
  };

  const matchedStudent = useMemo(() => {
    return students.find((s) => s.student_number.toUpperCase() === selectedStudentNumber.trim().toUpperCase());
  }, [students, selectedStudentNumber]);

  return (
    <>
      <section className="welcome-row">
        <div>
          <div className="eyebrow">BIOMETRIC PROVISIONING</div>
          <h2>Biometric enrollment</h2>
          <p>
            Capture and enroll multi-frame face templates for authorized students. A student roster row is not proof of biometric enrollment.
          </p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => void refreshStudents()}
          disabled={!isConnected || loadingStudents}
        >
          {loadingStudents ? "Loading…" : "↻ Refresh roster"}
        </button>
      </section>

      {!isConnected ? (
        <div className="notice notice-info">
          <strong>Administrator connection required</strong>
          <span>Connect to the FastAPI admin backend in the sidebar to perform authenticated biometric enrollment.</span>
        </div>
      ) : null}

      {error ? (
        <div className="notice notice-error" role="alert">
          <strong>Enrollment rejected</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {result ? (
        <div className="notice notice-success" role="status">
          <strong>Biometric enrollment successful</strong>
          <span>
            Enrolled <strong>{result.full_name}</strong> ({result.employee_id}) with version v{result.enrollment_version}.{" "}
            {result.accepted_sample_count} sample frames accepted, {result.embedding_records_created} encrypted templates created.
          </span>
          <div style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
            Consistency: {Number(result.quality_metrics.minimum_arcface_profile_consistency).toFixed(4)} (required ≥ 0.82) · Sharpness:{" "}
            {result.quality_metrics.mean_sharpness ? Number(result.quality_metrics.mean_sharpness).toFixed(1) : "N/A"} · Audit ID:{" "}
            <code>{result.audit_id.slice(0, 12)}</code>
          </div>
        </div>
      ) : null}

      <section className="college-forms">
        <article className="panel form-panel" style={{ gridColumn: "1 / -1" }}>
          <div className="form-index">01 / PARTICIPANT DETAILS</div>
          <h3>Select student or enter participant ID</h3>
          <p className="panel-description">
            Biometric templates will be linked to this student number. If the student already exists, enrollment creates a new verified version.
          </p>

          <form className="stack-form" onSubmit={(e) => void handleSubmit(e)}>
            <div className="split-fields">
              <label>
                Quick-select from student roster
                <select
                  value={selectedStudentNumber}
                  onChange={(e) => handleStudentSelect(e.target.value)}
                  disabled={students.length === 0}
                >
                  <option value="">-- Choose student or type below --</option>
                  {students.map((s) => (
                    <option key={s.student_id} value={s.student_number}>
                      {s.student_number} · {s.full_name}{" "}
                      {s.class_groups[0] ? `(${s.class_groups[0].department_code} Y${s.class_groups[0].year_of_study}-${s.class_groups[0].section})` : ""}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Student / Employee number
                <input
                  required
                  minLength={1}
                  maxLength={80}
                  value={selectedStudentNumber}
                  onChange={(e) => setSelectedStudentNumber(e.target.value.toUpperCase())}
                  placeholder="CSE23001"
                />
              </label>
            </div>

            <div className="split-fields">
              <label>
                Full name
                <input
                  required
                  minLength={1}
                  maxLength={200}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Student full name"
                />
              </label>

              <label>
                Department code (optional)
                <input
                  maxLength={160}
                  value={department}
                  onChange={(e) => setDepartment(e.target.value.toUpperCase())}
                  placeholder="CSE"
                />
              </label>
            </div>

            {matchedStudent ? (
              <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)", margin: "-0.5rem 0 0.5rem" }}>
                ✓ Linked to existing roster student: <strong>{matchedStudent.full_name}</strong> (Status:{" "}
                {matchedStudent.person_id ? "Previously linked" : "First-time biometric enrollment"})
              </div>
            ) : null}

            <div style={{ marginTop: "1rem" }}>
              <div className="form-index">02 / MULTI-FRAME FACE EVIDENCE</div>
              <h4>Capture or upload face images (minimum 3 separate frames)</h4>
              <p className="panel-description">
                Upload at least 3 distinct views (slight pose or expression variation). The server checks face detection, sharpness, minimum face size (≥ 80px), and intra-person ArcFace profile consistency.
              </p>

              <div
                style={{
                  border: "2px dashed var(--border-color, #cbd5e1)",
                  borderRadius: "8px",
                  padding: "1.5rem",
                  textAlign: "center",
                  background: "var(--card-bg, #f8fafc)",
                  cursor: "pointer",
                  marginBottom: "1rem",
                }}
                onClick={() => document.getElementById("enrollment-files")?.click()}
              >
                <input
                  id="enrollment-files"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  style={{ display: "none" }}
                  onChange={handleFileChange}
                />
                <p style={{ margin: 0, fontWeight: "bold" }}>Click to select face images (JPEG, PNG, WebP)</p>
                <small style={{ color: "var(--text-secondary)" }}>
                  Select 3 to 10 distinct frames. Repeated identical frames are rejected by the duplicate detector.
                </small>
              </div>

              {selectedFiles.length > 0 ? (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                    <span style={{ fontSize: "0.875rem", fontWeight: "bold" }}>
                      {selectedFiles.length} frame{selectedFiles.length === 1 ? "" : "s"} selected{" "}
                      {selectedFiles.length >= 3 ? (
                        <span className="pill pill-success" style={{ marginLeft: "0.5rem" }}>Ready for upload</span>
                      ) : (
                        <span className="pill pill-warning" style={{ marginLeft: "0.5rem" }}>Need {3 - selectedFiles.length} more</span>
                      )}
                    </span>
                    <button
                      type="button"
                      className="button button-small button-secondary"
                      onClick={clearFiles}
                    >
                      Clear all
                    </button>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))",
                      gap: "0.75rem",
                      marginBottom: "1rem",
                    }}
                  >
                    {previewUrls.map((url, idx) => (
                      <div
                        key={idx}
                        style={{
                          position: "relative",
                          borderRadius: "6px",
                          overflow: "hidden",
                          border: "1px solid var(--border-color, #e2e8f0)",
                          background: "#000",
                          aspectRatio: "1",
                        }}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={url}
                          alt={`Frame ${idx + 1}`}
                          style={{ width: "100%", height: "100%", objectFit: "cover" }}
                        />
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeFile(idx);
                          }}
                          style={{
                            position: "absolute",
                            top: "4px",
                            right: "4px",
                            background: "rgba(0,0,0,0.6)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "50%",
                            width: "22px",
                            height: "22px",
                            cursor: "pointer",
                            fontSize: "12px",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                          aria-label={`Remove frame ${idx + 1}`}
                        >
                          ×
                        </button>
                        <span
                          style={{
                            position: "absolute",
                            bottom: "4px",
                            left: "4px",
                            background: "rgba(0,0,0,0.65)",
                            color: "#fff",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "10px",
                          }}
                        >
                          #{idx + 1}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>

            <div style={{ display: "flex", gap: "1rem", alignItems: "center", marginTop: "1rem" }}>
              <button
                className="button button-primary"
                type="submit"
                disabled={!isConnected || enrolling || selectedFiles.length < 3}
              >
                {enrolling ? "Enrolling & analyzing…" : "Complete biometric enrollment"}
              </button>
              <Link href="/college" className="button button-secondary">
                Back to college roster
              </Link>
            </div>
          </form>
        </article>
      </section>

      <section className="panel" style={{ marginTop: "1.5rem" }}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">ENROLLMENT INVARIANTS</span>
            <h3>Biometric quality and security gates</h3>
          </div>
        </div>
        <ul style={{ paddingLeft: "1.25rem", color: "var(--text-secondary)", fontSize: "0.9rem", lineHeight: "1.6" }}>
          <li>
            <strong>Roster isolation:</strong> Creating a student in College Setup assigns an academic ID only. Biometric templates are only stored upon explicit enrollment.
          </li>
          <li>
            <strong>Minimum distinct frames:</strong> At least 3 separate camera frames are required. Duplicate pixel hashes are rejected.
          </li>
          <li>
            <strong>Deterministic quality checks:</strong> Frames with multiple faces, severe blur, or low face resolution (below 80×80 px) fail closed.
          </li>
          <li>
            <strong>Intra-person consistency:</strong> ArcFace embeddings across all submitted views must achieve pairwise cosine similarity ≥ 0.82 against the centroid.
          </li>
          <li>
            <strong>Template encryption:</strong> Embedding vectors are AES-GCM encrypted before storage; ordinary logs never contain raw images or embeddings.
          </li>
        </ul>
      </section>
    </>
  );
}

export default function BiometricEnrollmentPage() {
  return (
    <Suspense fallback={<div className="empty-state"><strong>Loading enrollment…</strong><span>Initializing biometric form.</span></div>}>
      <BiometricEnrollmentContent />
    </Suspense>
  );
}
