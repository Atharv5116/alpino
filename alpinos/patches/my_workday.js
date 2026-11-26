const root = root_element;
const q = (s) => root.querySelector(s);
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const PIN = '<svg class="i" viewBox="0 0 24 24"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/></svg>';
// half days: the first half's colour fades into the second half's
const HALF_TINT = { present: "#d6efdd", leave: "#d3e8fb", wfh: "#e7defa", absent: "#fbdcdc", open: "#f1f1f1" };
const HALF_INK = { present: "var(--green)", leave: "var(--blue)", wfh: "var(--purple)", absent: "var(--red)", open: "var(--muted)" };

const todayKey = frappe.datetime.get_today();
let workday = null;
const monthData = {};

function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function pad2(n) { return (n < 10 ? "0" : "") + n; }
function hm(min) {
  if (min == null || isNaN(min)) return "";
  min = Math.round(min);
  const h = Math.floor(min / 60), m = min % 60;
  return h ? (m ? h + "h " + pad2(m) + "m" : h + "h") : m + "m";
}
function hhmm(t) {
  if (!t) return "";
  let s = String(t).trim();
  if (s.indexOf("T") !== -1) s = s.split("T")[1];
  if (s.indexOf(" ") !== -1) s = s.split(" ").pop();
  const p = s.split(":");
  return p.length >= 2 ? pad2(parseInt(p[0], 10)) + ":" + p[1] : s;
}
function ampm(t) {
  const v = hhmm(t);
  if (!v) return "";
  let [h, m] = v.split(":").map((x) => parseInt(x, 10));
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return pad2(h) + ":" + pad2(m) + " " + ap;
}
function keyOf(y, m, d) { return y + "-" + pad2(m) + "-" + pad2(d); }
function dayLabel(key) { const p = key.split("-"); return parseInt(p[2], 10) + " " + MON[parseInt(p[1], 10) - 1]; }
function initials(name) { return (name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join(""); }
function shiftText(o) { return o && o.shift ? o.shift + " Shift" + (o.shift_start ? ", " + ampm(o.shift_start) + " to " + ampm(o.shift_end) : "") : ""; }
function leaveName(t) { return /leave|off/i.test(t || "") ? t : (t || "") + " Leave"; }

/* ------------------------------------------------------------------ check in / out
   Carried over from the "Employee Check In / Out" widget: the same server calls, camera
   capture for no-biometric companies, geo-fence rule, check-in type, WFH task update and the
   outside-office checkout reason. */
let startTime = null, timer = null, latitude = null, longitude = null;
let noBiometric = false, capturedImage = null, webCheckinRules = false, approvedWFH = false;
let checkinType = null, checkinReason = null;
const stateEl = q("#mw-state"), timerEl = q("#mw-timer");
q("#mw-btn-in").addEventListener("click", checkIn);
q("#mw-btn-out").addEventListener("click", checkOut);

function setState(text, kind) {
  stateEl.textContent = text;
  stateEl.className = "mw-pill dot " + ({ in: "green", out: "", none: "", error: "orange", leave: "blue", wfh: "purple" }[kind] || "");
}
function btn(which, disabled) {
  const el = q(which === "btn-in" ? "#mw-btn-in" : "#mw-btn-out");
  el.disabled = !!disabled;
  el.classList.toggle("go", !disabled);   // the action you can take now is the green one
}
function formatDuration(ms) {
  ms = Math.max(ms || 0, 0);
  const h = String(Math.floor(ms / 3600000)).padStart(2, "0");
  const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
  const s = String(Math.floor((ms % 60000) / 1000)).padStart(2, "0");
  return `${h}:${m}:${s}`;
}
function startTimer(t) {
  startTime = t;
  if (timer) clearInterval(timer);
  timer = setInterval(() => { timerEl.textContent = formatDuration(new Date() - startTime); }, 1000);
}
function stopTimer() { if (timer) clearInterval(timer); }
function setPausedTimer(seconds) { timerEl.textContent = formatDuration((seconds || 0) * 1000); }
function resetUI() {
  const lv = workday && workday.today && workday.today.leave;
  if (lv && !lv.half) setState("On leave", "leave"); else setState("Not checked in", "none");
  btn("btn-in", false); btn("btn-out", true); timerEl.textContent = "00:00:00";
}
function showError(err) {
  let msg = err;
  try { msg = JSON.parse(err).message || err; } catch (e) {}
  setState(String(msg).slice(0, 60), "error");
  btn("btn-in", true); btn("btn-out", true); stopTimer(); timerEl.textContent = "00:00:00";
}

function loadStatus() {
  frappe.call({
    method: "alpinos.attendance_widget.get_status",
    silent: true,
    callback(r) {
      if (r.exc) { resetUI(); return; }
      const m = r.message || {};
      noBiometric = !!m.no_biometric; webCheckinRules = !!m.web_checkin_rules; approvedWFH = !!m.approved_wfh;
      if (m.status === "IN") {
        setState("On duty", "in"); btn("btn-in", true); btn("btn-out", false);
        if (m.last_time) startTimer(new Date(m.last_time));
        return;
      }
      if (m.status === "OUT") {
        stopTimer(); setState("Checked out", "out"); btn("btn-in", true); btn("btn-out", true);
        setPausedTimer(m.elapsed_seconds);
        return;
      }
      resetUI();
    },
  });
}

function fetchLocation(callback) {
  if (!navigator.geolocation) {
    frappe.msgprint({ message: "Geolocation is not supported by your current browser", title: "Geolocation Error", indicator: "red" });
    if (callback) callback();
    return;
  }
  frappe.dom.freeze("Fetching your geolocation...");
  navigator.geolocation.getCurrentPosition(
    function (position) {
      latitude = position.coords.latitude; longitude = position.coords.longitude;
      frappe.dom.unfreeze();
      if (callback) callback();
    },
    function (error) {
      frappe.dom.unfreeze();
      let msg = "Unable to retrieve your location";
      if (error) msg += `<br><br>ERROR(${error.code}): ${error.message}`;
      frappe.msgprint({ message: msg, title: "Geolocation Error", indicator: "red" });
      if (callback) callback();
    }
  );
}

// Live camera only: gallery upload is intentionally not offered. Needs HTTPS (or localhost).
function openCameraDialog(onCapture, onCancel) {
  let stream = null;
  function stopStream() { if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; } }
  const d = new frappe.ui.Dialog({
    title: "Capture Live Photo",
    primary_action_label: "Capture",
    primary_action() {
      const video = d.$body.find("video.cam-video")[0];
      const canvas = d.$body.find("canvas.cam-canvas")[0];
      if (!video || !video.videoWidth) { frappe.msgprint("Camera is not ready yet. Please wait a moment and try again."); return; }
      canvas.width = video.videoWidth; canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", 0.8);
      stopStream(); d.hide(); onCapture(dataUrl);
    },
    secondary_action_label: "Cancel",
    secondary_action() { stopStream(); d.hide(); if (onCancel) onCancel(); },
  });
  d.$body.html(`
    <p style="color:#64748b;font-size:13px;margin-bottom:8px;">Position your face in the frame and click <b>Capture</b>. Live camera only, uploading from the gallery is not allowed.</p>
    <video class="cam-video" autoplay playsinline muted style="width:100%;border-radius:8px;background:#000;max-height:340px;object-fit:contain;"></video>
    <canvas class="cam-canvas" style="display:none;"></canvas>
    <div class="cam-error" style="color:#b91c1c;font-size:13px;margin-top:8px;display:none;"></div>`);
  d.onhide = function () { stopStream(); };
  d.show();
  const video = d.$body.find("video.cam-video")[0];
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    d.$body.find(".cam-error").text("Live camera is not supported by this browser/device.").show();
    return;
  }
  navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false })
    .then((s) => { stream = s; video.srcObject = s; })
    .catch((err) => {
      d.$body.find(".cam-error").text("Unable to access the camera: " + ((err && err.message) || err) + ". The camera needs permission and an HTTPS (or localhost) connection.").show();
    });
}

function afterPunch() { loadStatus(); loadWorkday(); delete monthData[monthKey(new Date())]; loadMonth(view.y, view.m, true); loadDays(); }

function checkIn() {
  frappe.call({ method: "alpinos.attendance_widget.log_frontend_action", args: { action: "WIDGET_CHECKIN_CLICK", log_type: "IN", details: "User clicked Check In button on My Workday." }, silent: true });
  btn("btn-in", true);
  const submitCheckin = function () {
    frappe.call({
      method: "alpinos.attendance_widget.check_in",
      args: { latitude: latitude, longitude: longitude, image: capturedImage, checkin_type: checkinType, checkin_reason: checkinReason },
      callback(r) {
        capturedImage = null; checkinType = null; checkinReason = null;
        if (r.exc) { showError(r.exc); btn("btn-in", false); return; }
        frappe.show_alert({ message: "Checked In", indicator: "green" });
        afterPunch();
      },
    });
  };
  fetchLocation(function () {
    if (!latitude || !longitude) { btn("btn-in", false); return; }
    if (noBiometric) {
      openCameraDialog(function (img) { capturedImage = img; submitCheckin(); }, function () { btn("btn-in", false); });
    } else if (webCheckinRules && !approvedWFH) {
      frappe.call({
        method: "alpinos.attendance_widget.is_within_shift_location",
        args: { latitude: latitude, longitude: longitude },
        callback(r) {
          if (r.message && r.message.within_location) {
            frappe.dom.unfreeze();
            btn("btn-in", false);
            frappe.throw("Please use biometric device to checkin");
          } else {
            showCheckinTypeDialog(function (sel) { checkinType = sel.type; checkinReason = sel.reason; submitCheckin(); }, function () { btn("btn-in", false); });
          }
        },
      });
    } else {
      submitCheckin();
    }
  });
}

// HRMS #14: three reasons only, no free text on check-in.
function showCheckinTypeDialog(onConfirm, onCancel) {
  const d = new frappe.ui.Dialog({
    title: "Check In",
    primary_action_label: "Check In",
    primary_action() {
      const type = (d.$body.find(".checkin-type-select").val() || "").trim();
      if (!type) { frappe.msgprint("Please select a check-in type."); return; }
      d.hide(); onConfirm({ type: type, reason: null });
    },
    secondary_action_label: "Cancel",
    secondary_action() { d.hide(); if (onCancel) onCancel(); },
  });
  d.$body.html(`
    <p style="color:#64748b;margin-bottom:12px;font-size:13px;">Select the reason for check-in.</p>
    <select class="form-control checkin-type-select" style="margin-bottom:10px;">
      <option value="">Select the reason</option><option value="Client/Vendor">Client/Vendor</option><option value="Shoot">Shoot</option><option value="Meeting">Meeting</option>
    </select>`);
  d.show();
}

function checkOut() {
  frappe.call({ method: "alpinos.attendance_widget.log_frontend_action", args: { action: "WIDGET_CHECKOUT_CLICK", log_type: "OUT", details: "User clicked Check Out button on My Workday before any confirm dialogs." }, silent: true });
  frappe.confirm("Are you sure you want to check out?", function () {
    btn("btn-out", true);
    const afterCapture = function () {
      fetchLocation(function () {
        const proceedCheckout = function () {
          frappe.call({
            method: "alpinos.attendance_widget.get_today_wfh_request",
            silent: true,
            callback(r) {
              if (r.message) {
                showWFHTaskDialog(r.message, function (tasks) {
                  frappe.call({
                    method: "alpinos.attendance_widget.save_wfh_tasks",
                    args: { wfh_request: r.message.name, tasks: JSON.stringify(tasks) },
                    callback(sr) {
                      if (sr.exc) { frappe.msgprint("Could not save tasks. Please try again."); btn("btn-out", false); return; }
                      doCheckOut();
                    },
                  });
                }, function () { btn("btn-out", false); });
              } else {
                doCheckOut();
              }
            },
          });
        };
        // Biometric employees inside the office radius check out on the device.
        if (webCheckinRules && !noBiometric && !approvedWFH) {
          frappe.call({
            method: "alpinos.attendance_widget.is_within_shift_location",
            args: { latitude: latitude, longitude: longitude },
            callback(res) {
              if (res.message && res.message.within_location) { frappe.msgprint("Please use biometric device to check out"); btn("btn-out", false); return; }
              proceedCheckout();
            },
          });
        } else {
          proceedCheckout();
        }
      });
    };
    if (noBiometric) openCameraDialog(function (img) { capturedImage = img; afterCapture(); }, function () { btn("btn-out", false); });
    else afterCapture();
  }, function () { btn("btn-out", false); });
}

function getExcMessage(exc) {
  if (!exc) return "";
  let parsed = exc;
  if (typeof exc === "string") { try { parsed = JSON.parse(exc); } catch (e) { return (exc || "").toLowerCase(); } }
  if (Array.isArray(parsed)) { const last = parsed[parsed.length - 1]; return (typeof last === "string" ? last : (last && last.message) || "").toLowerCase(); }
  return ((parsed && parsed.message) || String(parsed)).toLowerCase();
}
function doCheckOut(outside) {
  const args = { latitude: latitude, longitude: longitude };
  if (capturedImage) args.image = capturedImage;
  if (outside && outside.reason) { args.outside_reason = outside.reason; if (outside.remarks) args.outside_remarks = outside.remarks; }
  frappe.call({
    method: "alpinos.attendance_widget.check_out",
    args: args,
    silent: true,
    callback(r) {
      if (r.exc) { handleCheckoutError(r); return; }
      capturedImage = null;
      frappe.show_alert({ message: "Checked Out", indicator: "green" });
      stopTimer(); setPausedTimer(r.message ? r.message.elapsed_seconds : 0);
      afterPunch();
    },
    error(r) { handleCheckoutError(r); },
  });
}
function handleCheckoutError(r) {
  if (!r) { btn("btn-out", false); return; }
  const errMsg = getExcMessage(r.exc);
  if (errMsg.indexOf("provide a reason") !== -1 || errMsg.indexOf("outside the office location") !== -1) {
    frappe.hide_msgprint();
    showCheckoutReasonDialog(function (outside) { doCheckOut(outside); });
    btn("btn-out", false);
    return;
  }
  showError(r.exc); btn("btn-out", false);
}
function showCheckoutReasonDialog(onConfirm) {
  const d = new frappe.ui.Dialog({
    title: "Reason for Check Out (Outside Office)",
    primary_action_label: "Check Out",
    primary_action() {
      const reason = (d.$body.find(".checkout-reason-select").val() || "").trim();
      const remarks = (d.$body.find(".checkout-remarks-input").val() || "").trim();
      if (!reason) { frappe.msgprint("Please select a reason for checking out from outside the office location."); return; }
      if (reason === "Other" && !remarks) { frappe.msgprint("Please add an explanation for 'Other'."); return; }
      d.hide(); onConfirm({ reason: reason, remarks: remarks });
    },
    secondary_action_label: "Cancel",
    secondary_action() { d.hide(); btn("btn-out", false); },
  });
  d.$body.html(`
    <p style="color:#64748b;margin-bottom:12px;font-size:13px;">You are checking out from outside the office location. Please select a reason.</p>
    <select class="form-control checkout-reason-select" style="margin-bottom:10px;">
      <option value="">Select reason...</option><option value="Client/Vendor">Client/Vendor</option><option value="Shoot">Shoot</option><option value="Meeting">Meeting</option><option value="Other">Other</option>
    </select>
    <textarea class="form-control checkout-remarks-input" rows="2" placeholder="Explanation / remarks (required for 'Other')" style="display:none;"></textarea>`);
  d.$body.find(".checkout-reason-select").on("change", function () { d.$body.find(".checkout-remarks-input").toggle($(this).val() === "Other"); });
  d.show();
}
function showWFHTaskDialog(wfhData, onConfirm, onCancel) {
  const statusOptions = `<option value="">Select...</option><option value="Completed">Completed</option><option value="In Progress">In Progress</option><option value="Pending">Pending</option>`;
  const d = new frappe.ui.Dialog({
    title: "Work From Home: Daily Task Update",
    primary_action_label: "Save & Check Out",
    primary_action() {
      const tasks = []; let valid = true;
      d.$body.find(".wfh-task-row").each(function () {
        const taskName = $(this).find(".wfh-task-name").val().trim();
        const status = $(this).find(".wfh-task-status").val();
        if (!taskName && !status) return;
        if (!taskName) { frappe.msgprint("Task Name is required for all rows."); valid = false; return false; }
        if (!status) { frappe.msgprint("Status is required for all rows."); valid = false; return false; }
        tasks.push({ task_name: taskName, status: status });
      });
      if (!valid) return;
      if (!tasks.length) { frappe.msgprint("Please add at least one task before checking out."); return; }
      d.hide(); onConfirm(tasks);
    },
    secondary_action_label: "Cancel",
    secondary_action() { d.hide(); onCancel(); },
  });
  d.$body.html(`
    <p style="color:#64748b;margin-bottom:14px;font-size:13px;">You have a Work From Home request for today. Please update your task details before checking out.</p>
    <table class="table table-bordered table-condensed" style="margin-bottom:8px;">
      <thead style="background:#f8fafc;"><tr><th style="width:55%">Task Name <span style="color:red">*</span></th><th style="width:35%">Status <span style="color:red">*</span></th><th style="width:10%"></th></tr></thead>
      <tbody class="wfh-task-body"></tbody>
    </table>
    <button class="btn btn-xs btn-default wfh-add-row" style="margin-top:4px;">+ Add Row</button>`);
  function addRow(taskName, status) {
    const $row = $(`<tr class="wfh-task-row"><td><input type="text" class="form-control input-xs wfh-task-name" placeholder="Enter task name"></td><td><select class="form-control input-xs wfh-task-status">${statusOptions}</select></td><td style="text-align:center;vertical-align:middle;"><button class="btn btn-xs btn-danger wfh-remove-row" title="Remove">\xd7</button></td></tr>`);
    if (taskName) $row.find(".wfh-task-name").val(taskName);
    if (status) $row.find(".wfh-task-status").val(status);
    d.$body.find(".wfh-task-body").append($row);
  }
  if (wfhData.tasks && wfhData.tasks.length) wfhData.tasks.forEach((t) => addRow(t.task_name, t.status)); else addRow();
  d.$body.on("click", ".wfh-remove-row", function () { $(this).closest("tr").remove(); if (!d.$body.find(".wfh-task-row").length) addRow(); });
  d.$body.on("click", ".wfh-add-row", function () { addRow(); });
  d.show();
}

/* ---------------------------------------------------------- today, regularization, leave, people */
function loadWorkday() {
  frappe.call({
    method: "alpinos.my_workday.get_workday",
    silent: true,
    callback(r) {
      if (r.exc) return;
      workday = r.message || {};
      renderToday(); renderRegularization(); renderLeaves(); renderMoments(); renderPulse();
    },
  });
}

function renderToday() {
  const t = workday.today;
  const sh = q("#mw-shift"), geo = q("#mw-geo");
  if (!t) { q("#mw-where").textContent = "No Employee is linked to this login."; return; }
  if (t.shift) { sh.textContent = shiftText(t); sh.style.display = ""; } else sh.style.display = "none";
  const fi = t.first_in, lo = t.last_out;
  const inEl = q("#mw-in"), outEl = q("#mw-out");
  inEl.textContent = fi ? ampm(fi.time) : "Not yet"; inEl.classList.toggle("none", !fi);
  outEl.textContent = lo ? ampm(lo.time) : "Not yet"; outEl.classList.toggle("none", !lo);
  let inSub = "";
  if (fi) inSub = fi.source + (t.late ? ", late by " + hm(t.late_minutes) : (t.late_minutes != null ? ", on time" : ""));
  else if (t.leave) inSub = leaveName(t.leave.leave_type) + (t.leave.half ? ", " + (t.leave.period || "half day") : "");
  q("#mw-in-sub").textContent = inSub;
  q("#mw-out-sub").textContent = lo ? lo.source + (lo.outside ? ", outside geo-fence" : "") : (t.shift_end ? "Shift ends " + ampm(t.shift_end) : "");
  if (fi) {
    q("#mw-where").textContent = fi.source === "Biometric" ? "Checked in on the biometric device" : "Web check-in" + (fi.reason ? ": " + fi.reason : "");
    geo.style.display = "";
    if (t.wfh && fi.source === "Web") { geo.textContent = "WFH approved"; geo.className = "mw-pill dot purple"; }
    else if (fi.outside) { geo.textContent = "Outside geo-fence"; geo.className = "mw-pill dot orange"; }
    else { geo.textContent = "Inside geo-fence"; geo.className = "mw-pill dot green"; }
  } else {
    q("#mw-where").textContent = t.wfh ? "Work from home approved for today" + (t.wfh.half ? " (" + (t.wfh.period || "half day") + ")" : "") : "No punch yet today";
    geo.style.display = "none";
  }
}

function renderRegularization() {
  const g = workday.regularization;
  if (!g) { q("#mw-reg-sub").textContent = "No Employee is linked to this login."; return; }
  q("#mw-reg-sub").textContent = "Check-in / check-out edits for " + g.month;
  if (g.exempt) {
    q("#mw-reg-big").innerHTML = "No limit";
    q("#mw-reg-used").textContent = "HR Manager is not capped. " + g.used + " used this month.";
  } else {
    q("#mw-reg-big").innerHTML = g.left + "<small>of " + g.cap + " left</small>";
    q("#mw-reg-used").textContent = g.used + (g.used === 1 ? " edit" : " edits") + " used this month";
  }
  q("#mw-reg-segs").innerHTML = Array.from({ length: g.cap }, (_, i) => "<i" + (i < g.used ? ' class="u"' : "") + "></i>").join("");
}
q("#mw-reg-new").addEventListener("click", () => frappe.new_doc("Attendance Request"));

function renderLeaves() {
  const rows = workday.leave_balances || [];
  const colors = ["var(--blue)", "var(--green)", "var(--yellow)", "var(--purple)", "var(--cyan)"];
  q("#mw-leaves").innerHTML = rows.length ? rows.map((r, i) =>
    `<div class="mw-lb"><div><b>${esc(leaveName(r.leave_type))}</b><span>${esc(r.allocated)} allocated, lapses ${esc(r.to_label)}</span></div><span class="v num" style="color:${colors[i % colors.length]}">${esc(r.left)}<small>d</small></span></div>`
  ).join("") : '<div class="mw-empty">No leave allocated for today.</div>';
}
q("#mw-leave-link").addEventListener("click", () => frappe.set_route("query-report", "Employee Leave Balance", workday && workday.employee ? { employee: workday.employee } : {}));

function personRow(name, sub, pill, det) {
  return `<div class="mw-person"><div class="mw-prow"><span class="av">${esc(initials(name))}</span><div class="nm"><b>${esc(name)}</b><span class="sub">${esc(sub || "")}</span></div>${pill || ""}</div>${det || ""}</div>`;
}
function datePill(key) {
  const tomorrow = frappe.datetime.add_days(todayKey, 1);
  if (key === todayKey) return '<span class="mw-pill red">Today</span>';
  if (key === tomorrow) return '<span class="mw-pill orange">Tomorrow</span>';
  return '<span class="mw-pill">' + esc(dayLabel(key)) + "</span>";
}
function renderMoments() {
  const m = workday.moments || {}, bd = m.birthdays || [], an = m.anniversaries || [];
  q("#mw-mom-count").textContent = (bd.length + an.length) + " Milestones";
  q("#mw-bd-count").textContent = bd.length + " this month";
  q("#mw-an-count").textContent = an.length + " this month";
  q("#mw-bd").innerHTML = bd.length ? bd.map((r) => personRow(r.employee_name, r.designation || r.company, datePill(r.date))).join("") : '<div class="mw-empty">No birthdays this month</div>';
  q("#mw-an").innerHTML = an.length ? an.map((r) => personRow(r.employee_name, (r.designation ? r.designation + ", " : "") + dayLabel(r.date), '<span class="mw-pill yellow">' + r.years + (r.years === 1 ? " Yr" : " Yrs") + "</span>")).join("") : '<div class="mw-empty">No work anniversaries this month</div>';
}
function renderPulse() {
  const p = workday.pulse || {}, lv = p.on_leave || [], wf = p.on_wfh || [];
  q("#mw-pl-lv").textContent = lv.length + " On Leave";
  q("#mw-pl-wf").textContent = wf.length + " WFH";
  const where = (r) => [r.designation, r.branch || r.department].filter(Boolean).join(", ");
  q("#mw-onleave").innerHTML = lv.length ? lv.map((r) => personRow(r.employee_name, where(r), "",
    `<div class="det"><span class="mw-pill blue">${esc(leaveName(r.leave_type))}</span>${esc(r.part)}</div>`)).join("") : '<div class="mw-empty">No one on leave today</div>';
  q("#mw-onwfh").innerHTML = wf.length ? wf.map((r) => personRow(r.employee_name, where(r), "",
    `<div class="det"><span class="mw-pill purple">WFH</span>${esc(r.part)}</div>`)).join("") : '<div class="mw-empty">No one on WFH today</div>';
}

/* --------------------------------------------------------------------- the month */
const view = { y: 0, m: 0 };
function monthKey(d) { return d.getFullYear() + "-" + pad2(d.getMonth() + 1); }
function fetchMonth(y, m, cb) {
  const k = y + "-" + pad2(m);
  if (monthData[k]) { cb(monthData[k]); return; }
  frappe.call({
    method: "alpinos.attendance_widget.get_monthly_attendance",
    args: { year: y, month: m },
    silent: true,
    callback(r) { if (r.exc) return; monthData[k] = (r.message && r.message.days) || {}; cb(monthData[k]); },
  });
}

function shortHours(it, key) {
  if (it.worked_minutes == null) return false;
  const need = it.required_minutes != null ? it.required_minutes : (new Date(key + "T00:00:00").getDay() === 6 ? 240 : 480);
  return it.worked_minutes + 1 < need;
}

function dayClass(it, key) {
  if (key === todayKey) return "now";
  if (it.holiday && (!it.status || it.status === "Holiday")) return it.weekly_off ? "off" : "hol";
  if (it.halves && it.halves.length === 2) return "hd";
  const s = it.status;
  const past = key < todayKey;
  if (s === "Present") {
    if (it.regularized) return "r";
    if (it.wfh && !it.wfh_half) return "w";
    if ((it.check_in && !it.check_out && past) || shortHours(it, key)) return "x";
    return "pr";
  }
  if (s === "Work From Home") return "w";
  if (s === "On Leave") return "lv";
  if (s === "Absent") return it.check_in ? "x" : "ab";
  if (s === "Half Day") return "x";
  if (!s && it.wfh && !it.wfh_half) return "w";
  return "";
}

function renderCalendar(days) {
  const cal = q("#mw-cal");
  const first = new Date(view.y, view.m - 1, 1), total = new Date(view.y, view.m, 0).getDate();
  const lead = (first.getDay() + 6) % 7;
  let html = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => '<div class="mw-wd">' + d + "</div>").join("");
  for (let i = 0; i < lead; i++) html += '<div class="mw-day out"></div>';
  for (let d = 1; d <= total; d++) {
    const key = keyOf(view.y, view.m, d), it = days[key] || {};
    const cls = dayClass(it, key);
    let tag = "", body = "", style = "";
    const times = it.check_in ? hhmm(it.check_in) + " → " + (it.check_out ? hhmm(it.check_out) : "--:--") : "";
    const hours = it.worked_minutes != null ? hm(it.worked_minutes) + (it.shift ? ", " + it.shift : "") : (it.shift && it.check_in ? it.shift : "");
    if (cls === "hd") {
      const a = it.halves[0], b = it.halves[1];
      style = ` style="background:linear-gradient(105deg, ${HALF_TINT[a.kind]} 0 38%, ${HALF_TINT[b.kind]} 62% 100%)"`;
      tag = '<span class="tg" style="color:var(--text-2)">½ + ½</span>';
      body = `<span class="hl"><b style="color:${HALF_INK[a.kind]}">1st ½</b> ${esc(a.label)}</span><span class="hl"><b style="color:${HALF_INK[b.kind]}">2nd ½</b> ${esc(b.label)}</span>` +
        (times ? `<span class="h">${esc(times)}</span>` : "");
    } else if (cls === "now") {
      tag = '<span class="tg">Today</span>';
      body = it.check_in ? `<span class="t">In: ${esc(ampm(it.check_in))}</span><span class="h">${it.check_out ? "Out: " + esc(ampm(it.check_out)) : "Active"}${it.shift ? ", " + esc(it.shift) : ""}</span>`
        : `<span class="t">${esc(it.status === "On Leave" ? leaveName(it.leave_type) : it.holiday ? (it.holiday_name || "Holiday") : "Not checked in")}</span>`;
    } else if (cls === "off" || cls === "hol") {
      body = `<span class="t">${esc(it.weekly_off ? "Weekly Off" : (it.holiday_name || "Holiday"))}</span>`;
    } else if (cls === "lv") {
      tag = '<span class="tg">Leave</span>';
      body = `<span class="t">${esc(leaveName(it.leave_type || "Leave"))}</span><span class="h">Full day</span>`;
    } else if (cls === "ab") {
      tag = '<span class="tg">✕</span>';
      body = '<span class="t">Absent</span>';
    } else if (it.status || it.check_in || it.wfh) {
      tag = cls === "w" ? '<span class="tg">WFH</span>' : cls === "x" ? '<span class="tg">!</span>' : cls === "r" ? '<span class="tg">✓</span>' : cls === "pr" ? '<span class="tg">●</span>' : "";
      const first = times || (cls === "w" ? "Remote" : cls === "x" ? (it.status === "Half Day" ? "Half Day" : "Shortage") : (it.status || ""));
      body = `<span class="t">${esc(first)}</span>` + (hours ? `<span class="h">${esc(hours)}</span>` : "");
    }
    if (it.late_coming && cls !== "now" && cls !== "off" && cls !== "hol") tag = `<span class="tg late">Late ${esc(hm(it.late_minutes))}</span>`;
    else if (it.out_of_geo && !tag.includes("late")) tag = tag || `<span class="tg">${PIN}</span>`;
    if (it.out_of_geo) body += `<span class="g" title="Punch outside the geo-fence">${PIN}${esc(it.geo_reason || "Outside geo-fence")}</span>`;
    html += `<div class="mw-day ${cls}" data-key="${key}"${style}><span class="d">${pad2(d)}</span>${tag}${body}</div>`;
  }
  const trail = (7 - ((lead + total) % 7)) % 7;
  for (let i = 0; i < trail; i++) html += '<div class="mw-day out"></div>';
  cal.innerHTML = html;
  cal.querySelectorAll(".mw-day[data-key]").forEach((el) => el.addEventListener("click", () => select(el.dataset.key)));
  const inMonth = todayKey.slice(0, 7) === keyOf(view.y, view.m, 1).slice(0, 7);
  select(inMonth ? todayKey : null);
}

function select(key) {
  const bar = q("#mw-sel");
  q("#mw-cal").querySelectorAll(".mw-day.sel").forEach((e) => e.classList.remove("sel"));
  if (!key) { bar.style.display = "none"; return; }
  const el = q(`#mw-cal .mw-day[data-key="${key}"]`);
  if (el) el.classList.add("sel");
  const it = (monthData[key.slice(0, 7)] || {})[key] || {};
  const dt = new Date(key + "T00:00:00");
  const parts = [];
  if (it.halves && it.halves.length === 2) parts.push("First half: " + it.halves[0].label + ", second half: " + it.halves[1].label);
  else if (it.status === "On Leave") parts.push(leaveName(it.leave_type || "Leave"));
  if (it.shift) parts.push(shiftText(it));
  if (it.check_in) parts.push("Check-In: " + ampm(it.check_in) + (it.late_coming ? " (late by " + hm(it.late_minutes) + ")" : ""));
  if (it.check_in) parts.push("Check-Out: " + (it.check_out ? ampm(it.check_out) : (key === todayKey ? "pending" : "missing")));
  if (it.worked_minutes != null) parts.push(hm(it.worked_minutes) + " worked" + (it.required_minutes ? " of " + hm(it.required_minutes) : ""));
  if (it.out_of_geo) parts.push("Punch outside the geo-fence" + (it.geo_reason ? " (" + it.geo_reason + ")" : ""));
  if (it.wfh) parts.push("Work from home approved" + (it.wfh_half ? " for half the day" : ""));
  if (it.regularized) parts.push("Regularized");
  if (it.holiday) parts.push(it.weekly_off ? "Weekly off" : (it.holiday_name || "Holiday"));
  const status = key === todayKey && it.check_in && !it.check_out ? ["Active Session", "green"]
    : it.halves ? ["Half Day", ""] : it.status === "Present" ? ["Present", "green"] : it.status === "Absent" ? ["Absent", "red"]
    : it.status === "On Leave" ? ["On Leave", "blue"] : it.status === "Work From Home" ? ["WFH", "purple"] : it.status ? [it.status, ""] : null;
  bar.innerHTML = `<span class="dd">${dt.getDate()}</span><b>Selected Date: ${DAYS[dt.getDay()]}, ${MON[dt.getMonth()]} ${dt.getDate()}</b>` +
    (status ? `<span class="mw-pill ${status[1]}">${esc(status[0])}</span>` : "") +
    `<span class="x">${esc(parts.join(", ") || (key > todayKey ? "Upcoming" : "Nothing recorded"))}</span>`;
  bar.style.display = "";
}

function loadMonth(y, m, force) {
  view.y = y; view.m = m;
  q("#mw-month").textContent = MONTHS[m - 1] + " " + y;
  if (force) delete monthData[y + "-" + pad2(m)];
  fetchMonth(y, m, renderCalendar);
}
q("#mw-prev").addEventListener("click", () => { const d = new Date(view.y, view.m - 2, 1); loadMonth(d.getFullYear(), d.getMonth() + 1); });
q("#mw-next").addEventListener("click", () => { const d = new Date(view.y, view.m, 1); loadMonth(d.getFullYear(), d.getMonth() + 1); });

/* --------------------------------------------------------------- days this month */
function loadDays() {
  const y = parseInt(todayKey.slice(0, 4), 10), m = parseInt(todayKey.slice(5, 7), 10);
  fetchMonth(y, m, (days) => renderDays(days, y, m));
}
function renderDays(days, y, m) {
  const total = new Date(y, m, 0).getDate();
  const c = { present: 0, leave: 0, wfh: 0, absent: 0, remaining: 0, unmarked: 0 };
  let workedSum = 0, workedN = 0, late15 = 0, late30 = 0, working = 0;
  const needs = {};
  for (let d = 1; d <= total; d++) {
    const key = keyOf(y, m, d), it = days[key] || {};
    if (it.holiday && (!it.status || it.status === "Holiday")) continue;
    working++;
    if (key > todayKey) {
      // approved leave ahead is leave, not a day still to work
      if (it.status === "On Leave") c.leave++;
      else if (it.halves && it.halves.length === 2) it.halves.forEach((h) => { c[h.kind === "leave" ? "leave" : "remaining"] += 0.5; });
      else c.remaining++;
      continue;
    }
    if (it.halves && it.halves.length === 2) {
      it.halves.forEach((h) => { c[h.kind === "open" ? "remaining" : h.kind] += 0.5; });
    } else if (it.status === "Present") c[it.wfh && !it.wfh_half ? "wfh" : "present"]++;
    else if (it.status === "Work From Home") c.wfh++;
    else if (it.status === "On Leave") c.leave++;
    else if (it.status === "Absent") c.absent++;
    else if (it.status === "Half Day") { c.present += 0.5; c.absent += 0.5; }
    else if (key === todayKey) c[it.check_in ? "present" : "remaining"]++;
    else c.unmarked++;
    // Avg Work / Day: full weekdays only. Saturdays have their own shorter hours and a half day
    // is half a day, so mixing them in would pull the average below what a full day needs.
    const weekday = new Date(key + "T00:00:00").getDay() !== 6;
    const fullDay = !(it.halves && it.halves.length === 2) && (it.status === "Present" || it.status === "Work From Home");
    if (key < todayKey && weekday && fullDay && it.worked_minutes) {
      workedSum += it.worked_minutes; workedN++;
      if (it.required_minutes) needs[it.required_minutes] = (needs[it.required_minutes] || 0) + 1;
    }
    if (it.late_coming) { if ((it.late_minutes || 0) < 30) late15++; else late30++; }
  }
  // the weekday requirement most of the month's full days were measured against
  const need = Object.keys(needs).sort((a, b) => needs[b] - needs[a])[0];
  const parts = [["Present", c.present, "#2e9e5b"], ["Leave", c.leave, "#0e95c9"], ["Work From Home", c.wfh, "#9a52d6"], ["Absent", c.absent, "#cc2929"], ["Remaining", c.remaining, "#d9d9d9"]];
  if (c.unmarked) parts.push(["Not marked", c.unmarked, "#b0b0b0"]);
  q("#mw-days-sub").textContent = MONTHS[m - 1] + " " + y + ", by each day's shift";
  q("#mw-total").textContent = working;
  const svg = q("#mw-donut"), keys = q("#mw-keys"), NS = "http://www.w3.org/2000/svg";
  svg.innerHTML = ""; keys.innerHTML = "";
  const r = 48, C = 2 * Math.PI * r, gap = 1.6;
  let at = 0;
  svg.setAttribute("aria-label", MONTHS[m - 1] + " " + y + " working days: " + parts.map((p) => p[0] + " " + p[1]).join(", ") + " of " + working);
  parts.forEach((p) => {
    const len = working ? (p[1] / working) * C : 0;
    if (len > 0) {
      const el = document.createElementNS(NS, "circle");
      el.setAttribute("class", "s"); el.setAttribute("cx", 60); el.setAttribute("cy", 60); el.setAttribute("r", r);
      el.setAttribute("stroke", p[2]); el.setAttribute("stroke-dasharray", Math.max(len - gap, 0.5) + " " + C); el.setAttribute("stroke-dashoffset", -at);
      const t = document.createElementNS(NS, "title"); t.textContent = p[0] + ": " + p[1] + " of " + working + " days (" + Math.round((p[1] / working) * 100) + "%)";
      el.appendChild(t); svg.appendChild(el);
    }
    at += len;
    const k = document.createElement("div"); k.className = "k";
    k.innerHTML = `<i style="background:${p[2]}"></i>${p[0]}<b>${p[1]}<small>${p[1] === 1 ? "day" : "days"}</small></b><span class="p">${working ? Math.round((p[1] / working) * 100) : 0}%</span>`;
    keys.appendChild(k);
  });
  q("#mw-avg").textContent = workedN ? hm(workedSum / workedN) : "0h";
  q("#mw-avg-sub").textContent = need ? "Full weekdays, shift needs " + hm(+need) : "Full weekdays only";
  q("#mw-late15").innerHTML = late15 + "<small>" + (late15 === 1 ? "day" : "days") + "</small>";
  q("#mw-late30").innerHTML = late30 + "<small>" + (late30 === 1 ? "day" : "days") + "</small>";
}

/* ------------------------------------------------------------------------ start */
loadStatus();
loadWorkday();
loadMonth(parseInt(todayKey.slice(0, 4), 10), parseInt(todayKey.slice(5, 7), 10));
loadDays();
