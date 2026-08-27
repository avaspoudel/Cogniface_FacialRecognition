// Minimal vanilla-JS client for the Facial Recognition Attendance API.

const apiBaseInput = document.getElementById("apiBase");
const healthDot = document.getElementById("healthDot");

function apiBase() {
  return apiBaseInput.value.replace(/\/+$/, "");
}

async function api(path, options = {}) {
  const res = await fetch(apiBase() + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try {
    body = await res.json();
  } catch (_) {
    /* no body */
  }
  if (!res.ok) {
    const detail = body && (body.detail || body.message) ? (body.detail || body.message) : res.statusText;
    throw new Error(`${res.status}: ${JSON.stringify(detail)}`);
  }
  return body;
}

function showMsg(el, text, ok) {
  el.textContent = typeof text === "string" ? text : JSON.stringify(text, null, 2);
  el.className = "msg " + (ok ? "ok" : "err");
}

async function checkHealth() {
  try {
    await api("/api/health");
    healthDot.className = "dot ok";
    healthDot.title = "API reachable";
  } catch (e) {
    healthDot.className = "dot err";
    healthDot.title = "API unreachable: " + e.message;
  }
}
checkHealth();
setInterval(checkHealth, 8000);
apiBaseInput.addEventListener("change", checkHealth);

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

// ---------------------------------------------------------------------------
// Students & Classes
// ---------------------------------------------------------------------------
function formToObject(form) {
  const data = new FormData(form);
  const obj = {};
  for (const [k, v] of data.entries()) obj[k] = v;
  form.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    obj[cb.name] = cb.checked;
  });
  return obj;
}

document.getElementById("studentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("studentMsg");
  const payload = formToObject(e.target);
  if (!payload.email) delete payload.email;
  try {
    const res = await api("/api/students", { method: "POST", body: JSON.stringify(payload) });
    showMsg(msg, `Created student ${res.student_id}`, true);
    e.target.reset();
    loadStudents();
  } catch (err) {
    showMsg(msg, err.message, false);
  }
});

document.getElementById("classForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("classMsg");
  const payload = formToObject(e.target);
  try {
    const res = await api("/api/classes", { method: "POST", body: JSON.stringify(payload) });
    showMsg(msg, `Created class ${res.class_id}`, true);
    e.target.reset();
  } catch (err) {
    showMsg(msg, err.message, false);
  }
});

document.getElementById("enrollForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("enrollMsg");
  const payload = formToObject(e.target);
  try {
    await api("/api/classes/enroll", { method: "POST", body: JSON.stringify(payload) });
    showMsg(msg, `Enrolled ${payload.student_id} in ${payload.class_id}`, true);
    e.target.reset();
    loadStudents();
  } catch (err) {
    showMsg(msg, err.message, false);
  }
});

async function loadStudents() {
  const tbody = document.querySelector("#studentsTable tbody");
  try {
    const students = await api("/api/students");
    tbody.innerHTML = students
      .map(
        (s) =>
          `<tr><td>${s.student_id}</td><td>${s.name}</td><td>${s.email || ""}</td><td>${
            s.face_registered ? "Yes" : "No"
          }</td></tr>`
      )
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4">${err.message}</td></tr>`;
  }
}
document.getElementById("refreshStudents").addEventListener("click", loadStudents);
loadStudents();

// ---------------------------------------------------------------------------
// Face Registration
// ---------------------------------------------------------------------------
const regVideo = document.getElementById("regVideo");
const regCanvas = document.getElementById("regCanvas");
const regStartCam = document.getElementById("regStartCam");
const regCapture = document.getElementById("regCapture");
const regClear = document.getElementById("regClear");
const regSubmit = document.getElementById("regSubmit");
const regCount = document.getElementById("regCount");
const regThumbs = document.getElementById("regThumbs");
const regMsg = document.getElementById("regMsg");

let regStream = null;
let capturedImages = []; // base64 data URLs

async function startCamera(videoEl, startBtn) {
  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 480, height: 360 }, audio: false });
  videoEl.srcObject = stream;
  startBtn.disabled = true;
  return stream;
}

regStartCam.addEventListener("click", async () => {
  try {
    regStream = await startCamera(regVideo, regStartCam);
    regCapture.disabled = false;
  } catch (err) {
    showMsg(regMsg, "Camera error: " + err.message, false);
  }
});

function grabFrame(videoEl, canvasEl) {
  canvasEl.width = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  const ctx = canvasEl.getContext("2d");
  ctx.drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);
  return canvasEl.toDataURL("image/jpeg", 0.9);
}

regCapture.addEventListener("click", () => {
  const dataUrl = grabFrame(regVideo, regCanvas);
  capturedImages.push(dataUrl);
  const img = document.createElement("img");
  img.src = dataUrl;
  regThumbs.appendChild(img);
  regCount.textContent = capturedImages.length;
  regSubmit.disabled = capturedImages.length < 15 || !document.getElementById("regStudentId").value;
});

regClear.addEventListener("click", () => {
  capturedImages = [];
  regThumbs.innerHTML = "";
  regCount.textContent = "0";
  regSubmit.disabled = true;
  showMsg(regMsg, "", true);
});

document.getElementById("regStudentId").addEventListener("input", () => {
  regSubmit.disabled = capturedImages.length < 15 || !document.getElementById("regStudentId").value;
});

regSubmit.addEventListener("click", async () => {
  const studentId = document.getElementById("regStudentId").value.trim();
  if (!studentId) return;
  regSubmit.disabled = true;
  showMsg(regMsg, "Submitting registration...", true);
  try {
    const res = await api("/api/face/register", {
      method: "POST",
      body: JSON.stringify({ student_id: studentId, images: capturedImages }),
    });
    showMsg(regMsg, res, res.success);
    if (res.success) loadStudents();
  } catch (err) {
    showMsg(regMsg, err.message, false);
  } finally {
    regSubmit.disabled = capturedImages.length < 15;
  }
});

document.getElementById("statusCheck").addEventListener("click", async () => {
  const id = document.getElementById("statusStudentId").value.trim();
  const msg = document.getElementById("statusMsg");
  if (!id) return;
  try {
    const res = await api(`/api/face/status/${encodeURIComponent(id)}`);
    showMsg(msg, res, true);
  } catch (err) {
    showMsg(msg, err.message, false);
  }
});

// ---------------------------------------------------------------------------
// Attendance Session
// ---------------------------------------------------------------------------
let activeSession = null;
const liveCard = document.getElementById("liveCard");
const attVideo = document.getElementById("attVideo");
const attCanvas = document.getElementById("attCanvas");
const attStartCam = document.getElementById("attStartCam");
const attToggleLoop = document.getElementById("attToggleLoop");
const attSendOnce = document.getElementById("attSendOnce");
const recognizedList = document.getElementById("recognizedList");
let attStream = null;
let loopTimer = null;

document.getElementById("sessionForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("sessionMsg");
  const payload = formToObject(e.target);
  try {
    const res = await api("/api/attendance/sessions", { method: "POST", body: JSON.stringify(payload) });
    if (!res.success) {
      showMsg(msg, res.message, false);
      return;
    }
    activeSession = { session_id: res.session_id, class_id: payload.class_id };
    showMsg(msg, `Session started: ${res.session_id} (${res.enrolled_count} enrolled)`, true);
    document.getElementById("activeSessionId").textContent = res.session_id;
    liveCard.style.display = "block";
    recognizedList.innerHTML = "";
    refreshSessionTable();
  } catch (err) {
    showMsg(msg, err.message, false);
  }
});

attStartCam.addEventListener("click", async () => {
  try {
    attStream = await startCamera(attVideo, attStartCam);
    attToggleLoop.disabled = false;
    attSendOnce.disabled = false;
  } catch (err) {
    alert("Camera error: " + err.message);
  }
});

async function sendFrame() {
  if (!activeSession) return;
  const dataUrl = grabFrame(attVideo, attCanvas);
  try {
    const res = await api("/api/attendance/frame", {
      method: "POST",
      body: JSON.stringify({
        session_id: activeSession.session_id,
        class_id: activeSession.class_id,
        image_frame: dataUrl,
      }),
    });
    if (res.success && res.recognizedStudents && res.recognizedStudents.length) {
      res.recognizedStudents.forEach((s) => {
        const chip = document.createElement("span");
        chip.className = "chip" + (s.status === "Late" ? " late" : "");
        chip.textContent = `${s.studentName} (${s.studentId}) - ${s.status} - ${(s.confidence * 100).toFixed(1)}%`;
        recognizedList.prepend(chip);
      });
      refreshSessionTable();
    }
  } catch (err) {
    console.error("frame error", err);
  }
}

attSendOnce.addEventListener("click", sendFrame);

attToggleLoop.addEventListener("click", () => {
  if (loopTimer) {
    clearInterval(loopTimer);
    loopTimer = null;
    attToggleLoop.textContent = "Start Auto-Recognition";
  } else {
    const interval = parseInt(document.getElementById("attInterval").value, 10) || 2000;
    loopTimer = setInterval(sendFrame, interval);
    attToggleLoop.textContent = "Stop Auto-Recognition";
  }
});

async function refreshSessionTable() {
  if (!activeSession) return;
  const tbody = document.querySelector("#sessionTable tbody");
  try {
    const res = await api(`/api/attendance/sessions/${activeSession.session_id}`);
    tbody.innerHTML = res.records
      .map(
        (r) =>
          `<tr><td>${r.student_id}</td><td>${r.attendance_status}</td><td>${r.marking_method || ""}</td><td>${
            r.confidence_score != null ? (r.confidence_score * 100).toFixed(1) + "%" : ""
          }</td><td>${r.timestamp || ""}</td></tr>`
      )
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5">${err.message}</td></tr>`;
  }
}
document.getElementById("refreshSession").addEventListener("click", refreshSessionTable);

document.getElementById("closeSession").addEventListener("click", async () => {
  const msg = document.getElementById("closeMsg");
  if (!activeSession) return;
  const markedBy = document.getElementById("closeMarkedBy").value.trim();
  if (!markedBy) {
    showMsg(msg, "Enter a lecturer ID to close the session", false);
    return;
  }
  try {
    const res = await api(
      `/api/attendance/sessions/${activeSession.session_id}/close?marked_by=${encodeURIComponent(markedBy)}`,
      { method: "POST" }
    );
    showMsg(msg, res, res.success);
    if (loopTimer) {
      clearInterval(loopTimer);
      loopTimer = null;
      attToggleLoop.textContent = "Start Auto-Recognition";
    }
    refreshSessionTable();
  } catch (err) {
    showMsg(msg, err.message, false);
  }
});

document.getElementById("manualForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("manualMsg");
  const payload = formToObject(e.target);
  try {
    const res = await api("/api/attendance/sessions/manual", { method: "PATCH", body: JSON.stringify(payload) });
    showMsg(msg, res, res.success);
    if (activeSession && payload.session_id === activeSession.session_id) refreshSessionTable();
  } catch (err) {
    showMsg(msg, err.message, false);
  }
});

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------
document.getElementById("repStudentBtn").addEventListener("click", async () => {
  const id = document.getElementById("repStudentId").value.trim();
  const out = document.getElementById("repStudentOut");
  if (!id) return;
  try {
    const res = await api(`/api/attendance/students/${encodeURIComponent(id)}`);
    showMsg(out, res, true);
  } catch (err) {
    showMsg(out, err.message, false);
  }
});

document.getElementById("repClassBtn").addEventListener("click", async () => {
  const id = document.getElementById("repClassId").value.trim();
  const out = document.getElementById("repClassOut");
  if (!id) return;
  try {
    const res = await api(`/api/attendance/classes/${encodeURIComponent(id)}/report`);
    showMsg(out, res, true);
  } catch (err) {
    showMsg(out, err.message, false);
  }
});
