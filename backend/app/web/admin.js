(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { stream: null, frames: [], busy: false };

  function baseUrl() {
    const raw = byId("apiBase").value.trim();
    return (raw || window.location.origin).replace(/\/+$/, "");
  }
  function key() { return byId("adminKey").value.trim(); }
  function setStatus(id, message, type = "") {
    const target = byId(id);
    target.textContent = message || "";
    target.className = "status" + (type ? " " + type : "");
  }
  function setBadge(message, ok = false) {
    byId("connectionBadge").textContent = message;
    byId("connectionBadge").className = "chip" + (ok ? " badge ok" : "");
  }
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
    }[ch]));
  }
  function authHeaders() {
    if (!key()) throw new Error("Administrator API credential is required.");
    return { Authorization: "Bearer " + key() };
  }
  async function jsonRequest(path, options = {}) {
    const response = await fetch(baseUrl() + path, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
      cache: "no-store",
    });
    let payload;
    try { payload = await response.json(); }
    catch (_) { payload = { detail: "Server returned a non-JSON response." }; }
    if (!response.ok) {
      let detail = payload.detail ?? response.statusText;
      if (typeof detail !== "string") detail = JSON.stringify(detail);
      throw new Error("HTTP " + response.status + ": " + detail);
    }
    return payload;
  }
  function createCell(value) { return "<td>" + esc(value) + "</td>"; }
  function clearTable(bodyId, rows) { byId(bodyId).innerHTML = rows.join(""); }

  async function checkHealth() {
    setStatus("healthStatus", "Checking live backend health…");
    try {
      // /health is intentionally operational and does not require an admin secret.
      const response = await fetch(baseUrl() + "/health", { cache: "no-store" });
      const health = await response.json();
      if (!response.ok) throw new Error("HTTP " + response.status + ": " + JSON.stringify(health));
      const ready = health.ready_for_attendance === true;
      setBadge(ready ? "Runtime ready" : "Runtime not ready", ready);
      setStatus(
        "healthStatus",
        JSON.stringify({
          status: health.status,
          database: health.database,
          threshold_status: health.threshold_status,
          ready_for_attendance: health.ready_for_attendance,
          model_components: health.model_components,
          liveness_required: health.liveness_required,
        }, null, 2),
        ready ? "success" : "error",
      );
      return health;
    } catch (error) {
      setBadge("Backend unavailable");
      setStatus("healthStatus", error.message, "error");
      throw error;
    }
  }

  function renderFrames() {
    const container = byId("framesList");
    container.replaceChildren();
    state.frames.forEach((blob, index) => {
      const img = document.createElement("img");
      img.className = "frame-thumb";
      img.alt = "Captured frame " + (index + 1);
      img.src = URL.createObjectURL(blob);
      img.onload = () => URL.revokeObjectURL(img.src);
      container.appendChild(img);
    });
    byId("enrollBtn").disabled = state.frames.length < 3 || state.busy;
    byId("captureBurstBtn").disabled = !state.stream || state.busy;
  }
  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera API is unavailable. Use HTTPS or a trusted localhost origin.");
    await stopCamera();
    state.frames = [];
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } },
    });
    byId("camera").srcObject = state.stream;
    await byId("camera").play();
    byId("startCameraBtn").disabled = true;
    byId("stopCameraBtn").disabled = false;
    byId("captureBurstBtn").disabled = false;
    renderFrames();
  }
  async function stopCamera() {
    if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
    byId("camera").srcObject = null;
    byId("startCameraBtn").disabled = false;
    byId("stopCameraBtn").disabled = true;
    byId("captureBurstBtn").disabled = true;
  }
  async function captureBurst() {
    const video = byId("camera");
    if (!state.stream || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      throw new Error("Wait until the camera preview is ready.");
    }
    state.frames = [];
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    if (!canvas.width || !canvas.height) throw new Error("Camera has no ready video frame.");
    const context = canvas.getContext("2d", { alpha: false });
    for (let i = 0; i < 3; i++) {
      if (i) await new Promise((resolve) => setTimeout(resolve, 250));
      if (!state.stream || !video.srcObject) throw new Error("Camera stopped during burst capture.");
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve, reject) => canvas.toBlob(
        (result) => result ? resolve(result) : reject(new Error("JPEG encoding failed.")),
        "image/jpeg",
        0.92,
      ));
      if (!blob || blob.size === 0) throw new Error("Camera produced an empty frame.");
      state.frames.push(blob);
    }
    if (new Set(state.frames.map((frame) => frame.size)).size === 1 &&
        state.frames.every((frame, index) => index === 0 || frame === state.frames[0])) {
      throw new Error("Repeated frame object detected; recapture a real burst.");
    }
    renderFrames();
    setStatus("enrollStatus", "Captured " + state.frames.length + " separate video frames. Enrollment will validate each one.");
  }

  async function submitEnrollment(event) {
    event.preventDefault();
    if (state.busy) return;
    const employeeId = byId("employeeId").value.trim();
    const fullName = byId("employeeName").value.trim();
    const department = byId("department").value.trim();
    if (!employeeId || !fullName) throw new Error("Employee ID and full name are required.");
    if (state.frames.length < 3) throw new Error("Capture three separate camera frames before enrollment.");
    const body = new FormData();
    body.append("employee_id", employeeId);
    body.append("full_name", fullName);
    if (department) body.append("department", department);
    state.frames.forEach((blob, index) => body.append("images", blob, "enrollment_" + (index + 1) + ".jpg"));
    state.busy = true;
    byId("enrollBtn").disabled = true;
    setStatus("enrollStatus", "Submitting real enrollment frames to the configured backend…");
    try {
      const result = await jsonRequest("/api/v1/biometrics/enroll/admin", {
        method: "POST", body,
      });
      setStatus("enrollStatus", JSON.stringify(result, null, 2), "success");
      await refreshPeople();
      await refreshModels();
    } catch (error) {
      setStatus("enrollStatus", error.message, "error");
      throw error;
    } finally {
      state.busy = false;
      renderFrames();
    }
  }

  async function refreshPeople() {
    setStatus("peopleStatus", "Fetching the live roster…");
    try {
      const activeOnly = byId("peopleActiveOnly").value;
      const result = await jsonRequest("/api/v1/admin/people?active_only=" + activeOnly + "&limit=500");
      clearTable("peopleBody", result.items.map((person) => {
        const action = person.is_active
          ? '<button class="danger" data-person-action="deactivate" data-id="' + esc(person.employee_id) + '">Deactivate</button>'
          : '<button class="secondary" data-person-action="reactivate" data-id="' + esc(person.employee_id) + '">Reactivate</button>';
        return "<tr>" +
          createCell(person.employee_id) + createCell(person.full_name) + createCell(person.department || "—") +
          '<td><span class="badge ' + (person.is_active ? "ok" : "warn") + '">' + (person.is_active ? "ACTIVE" : "INACTIVE") + "</span></td>" +
          createCell(person.enrollment_version) + createCell(person.created_at) + '<td>' + action + "</td></tr>";
      }));
      setStatus("peopleStatus", result.items.length + " live roster records loaded.", "success");
    } catch (error) {
      setStatus("peopleStatus", error.message, "error");
      throw error;
    }
  }

  async function personAction(employeeId, action) {
    if (!window.confirm("Confirm " + action + " for employee " + employeeId + "?")) return;
    const result = await jsonRequest(
      "/api/v1/admin/people/" + encodeURIComponent(employeeId) + "/" + action,
      { method: "POST" },
    );
    setStatus("peopleStatus", JSON.stringify(result), "success");
    await refreshPeople();
  }

  async function refreshAttendance() {
    setStatus("attendanceStatus", "Fetching attendance records…");
    try {
      const employeeId = byId("attendanceFilter").value.trim();
      const query = new URLSearchParams({ limit: "500" });
      if (employeeId) query.set("employee_id", employeeId);
      const result = await jsonRequest("/api/v1/admin/attendance?" + query.toString());
      clearTable("attendanceBody", result.items.map((row) =>
        "<tr>" + createCell(row.timestamp) + createCell(row.employee_id) + createCell(row.punch_type) +
        createCell(Number(row.similarity_score).toFixed(4)) + createCell(Number(row.threshold).toFixed(4)) +
        createCell(row.client_device_id) + createCell(row.pipeline_version) +
        '<td><button class="secondary" data-audit-id="' + esc(row.evidence_id) + '">Inspect evidence</button></td></tr>'
      ));
      setStatus("attendanceStatus", result.items.length + " records loaded from the database.", "success");
    } catch (error) {
      setStatus("attendanceStatus", error.message, "error");
      throw error;
    }
  }

  async function refreshModels() {
    setStatus("modelsStatus", "Reading the real model registry and runtime components…");
    try {
      const result = await jsonRequest("/api/v1/admin/models");
      const rows = [];
      for (const [name, status] of Object.entries(result.runtime_components || {})) {
        rows.push("<tr>" + createCell(name) + createCell(status) + createCell("—") +
          createCell("runtime component") + createCell("—") +
          '<td><span class="badge ' + (String(status).startsWith("READY") ? "ok" : "warn") + '">' + esc(status) + "</span></td></tr>");
      }
      for (const model of (result.registry || [])) {
        rows.push("<tr>" + createCell(model.model_id) + createCell(model.model_version) +
          createCell(model.artifact_sha256) + createCell(model.license_name) +
          createCell(model.preprocessing_id) + createCell(model.active ? "ACTIVE" : "INACTIVE") + "</tr>");
      }
      clearTable("modelsBody", rows);
      setStatus("modelsStatus", (result.registry || []).length + " registered model versions; readiness is independently reported by /health.", "success");
    } catch (error) {
      setStatus("modelsStatus", error.message, "error");
      throw error;
    }
  }

  async function lookupAudit(id) {
    const auditId = (id || byId("auditId").value).trim();
    if (!auditId) throw new Error("Provide an audit identifier.");
    byId("auditId").value = auditId;
    setStatus("auditStatus", "Fetching audit evidence…");
    try {
      const result = await jsonRequest("/api/v1/admin/audit/" + encodeURIComponent(auditId));
      byId("auditPayload").textContent = JSON.stringify(result, null, 2);
      setStatus("auditStatus", "Audit evidence fetched from database.", "success");
    } catch (error) {
      setStatus("auditStatus", error.message, "error");
      throw error;
    }
  }

  function reportError(targetId, promise) {
    promise.catch((error) => {
      const target = byId(targetId);
      if (!target.textContent.includes(error.message)) setStatus(targetId, error.message, "error");
    });
  }

  byId("connectBtn").addEventListener("click", () => reportError("healthStatus", checkHealth()));
  byId("clearKeyBtn").addEventListener("click", () => {
    byId("adminKey").value = "";
    setBadge("Not authenticated");
  });
  byId("startCameraBtn").addEventListener("click", () => reportError("enrollStatus", startCamera()));
  byId("stopCameraBtn").addEventListener("click", () => reportError("enrollStatus", stopCamera()));
  byId("captureBurstBtn").addEventListener("click", () => reportError("enrollStatus", captureBurst()));
  byId("enrollBtn").addEventListener("click", (event) => reportError("enrollStatus", submitEnrollment(event)));
  byId("refreshPeopleBtn").addEventListener("click", () => reportError("peopleStatus", refreshPeople()));
  byId("peopleActiveOnly").addEventListener("change", () => reportError("peopleStatus", refreshPeople()));
  byId("refreshAttendanceBtn").addEventListener("click", () => reportError("attendanceStatus", refreshAttendance()));
  byId("refreshModelsBtn").addEventListener("click", () => reportError("modelsStatus", refreshModels()));
  byId("lookupAuditBtn").addEventListener("click", () => reportError("auditStatus", lookupAudit()));

  document.addEventListener("click", (event) => {
    const actionButton = event.target.closest("[data-person-action]");
    const auditButton = event.target.closest("[data-audit-id]");
    if (actionButton) {
      reportError("peopleStatus", personAction(actionButton.dataset.id, actionButton.dataset.personAction));
    } else if (auditButton) {
      reportError("auditStatus", lookupAudit(auditButton.dataset.auditId));
    }
  });
  window.addEventListener("beforeunload", () => {
    if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
    byId("adminKey").value = "";
  });
})();