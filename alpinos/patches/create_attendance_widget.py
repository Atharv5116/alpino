import json

import frappe


def execute():
    workspace = "Home"
    label = "Employee Check In / Out"

    html = """
<div style="padding:24px; border:1px solid #cfe5db; border-radius:12px; width:49.5%; background:#eaf7f1; min-height:210px; transform:scale(0.99); transform-origin: top left;">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
    <h4 style="margin:0; font-size:18px; color:#0f172a;">Attendance</h4>
    <span id="att-status" style="padding:4px 10px; border-radius:999px; font-weight:600; font-size:12px; border:1px solid #cbd5e1; background:#f1f5f9; color:#334155;">Loading</span>
  </div>

  <div style="display:flex; gap:10px; margin-bottom:16px;">
    <button id="btn-in" class="btn btn-success" style="padding:10px 18px; font-size:15px; background:#8fc9a7; border-color:#7dbf99; color:#0f172a;">Check In</button>
    <button id="btn-out" class="btn btn-danger" style="padding:10px 18px; font-size:15px; background:#e7a7a7; border-color:#dc9c9c; color:#4b1d1d;" disabled>Check Out</button>
  </div>

  <div style="height:1px; background:#d6e9df; margin:10px 0 12px 0;"></div>

  <div style="margin-top:6px;">
    <div style="font-size:13px; color:#64748b; margin-bottom:4px; letter-spacing:0.2px;">Working Time</div>
    <div id="att-timer" style="font-size:30px; font-weight:700; color:#0f172a; letter-spacing:0.6px; font-variant-numeric:tabular-nums;">00:00:00</div>
  </div>
</div>
"""

    script = """
const root = root_element;
let emp = null;
let startTime = null;
let timer = null;
let latitude = null;
let longitude = null;

const statusEl = root.querySelector("#att-status");
const timerEl = root.querySelector("#att-timer");
const btnIn = root.querySelector("#btn-in");
const btnOut = root.querySelector("#btn-out");

btnIn.addEventListener("click", checkIn);
btnOut.addEventListener("click", checkOut);

loadStatus();

function loadStatus(){
  frappe.call({
    method:"alpinos.attendance_widget.get_status",
    silent: true,
    callback(r){
      if(r.exc){
        resetUI();
        return;
      }
      const data = r.message || {};
      const status = data.status || "NONE";
      const nextAction = data.next_action || "IN";

      if(status === "IN"){
        setStatusBadge("Checked In", "in");
        btn("btn-in",true);
        btn("btn-out",false);
        if(data.last_time){
          startTimer(new Date(data.last_time));
        }
        return;
      }

      if(status === "OUT"){
        setStatusBadge("Checked Out", "out");
        btn("btn-in",true);
        btn("btn-out",true);
        setPausedTimer(data.elapsed_seconds || 0);
      } else {
        const isPreviousDayOpen = !!data.previous_day_open;
        const noneLabel = isPreviousDayOpen ? "Previous day missed checkout. Check In for today." : "Not Checked In";
        resetUI(noneLabel);
      }

      // Hard guard from backend state: next day must begin with IN.
      if(nextAction === "IN"){
        btn("btn-in",false);
        btn("btn-out",true);
      }
    }
  });
}

function fetchLocation(callback) {
  // Try to fetch browser geolocation similar to Employee Checkin "Fetch Location"
  if (!navigator.geolocation) {
    frappe.msgprint({
      message: "Geolocation is not supported by your current browser",
      title: "Geolocation Error",
      indicator: "red"
    });
    if (callback) callback();
    return;
  }

  frappe.dom.freeze("Fetching your geolocation...");

  navigator.geolocation.getCurrentPosition(
    function (position) {
      latitude = position.coords.latitude;
      longitude = position.coords.longitude;
      frappe.dom.unfreeze();
      if (callback) callback();
    },
    function (error) {
      frappe.dom.unfreeze();

      let msg = "Unable to retrieve your location";
      if (error) {
        msg += `<br><br>ERROR(${error.code}): ${error.message}`;
      }

      frappe.msgprint({
        message: msg,
        title: "Geolocation Error",
        indicator: "red",
      });

      if (callback) callback();
    }
  );
}

function checkIn(){
  btn("btn-in", true);
  fetchLocation(function () {
    frappe.call({
      method:"alpinos.attendance_widget.check_in",
      args: {
        latitude: latitude,
        longitude: longitude,
      },
      callback(r){
        if(r.exc){
          showError(r.exc);
          btn("btn-in", false);
          return;
        }
        frappe.show_alert({message:"Checked In",indicator:"green"});
        loadStatus();
      }
    });
  });
}

function checkOut(){
  frappe.confirm(
    "Are you sure you want to check out?",
    function () {
      btn("btn-out", true);
      fetchLocation(function () {
        frappe.call({
          method: "alpinos.attendance_widget.get_today_wfh_request",
          silent: true,
          callback(r) {
            if (r.message) {
              showWFHTaskDialog(
                r.message,
                function(tasks) {
                  frappe.call({
                    method: "alpinos.attendance_widget.save_wfh_tasks",
                    args: { wfh_request: r.message.name, tasks: JSON.stringify(tasks) },
                    callback(sr) {
                      if (sr.exc) {
                        frappe.msgprint("Could not save tasks. Please try again.");
                        btn("btn-out", false);
                        return;
                      }
                      doCheckOut();
                    }
                  });
                },
                function() {
                  btn("btn-out", false);
                }
              );
            } else {
              doCheckOut();
            }
          }
        });
      });
    },
    function () {
      // user cancelled
      btn("btn-out", false);
    }
  );
}

function getExcMessage(exc) {
  if (!exc) return "";
  let parsed = exc;
  if (typeof exc === "string") {
    try { parsed = JSON.parse(exc); } catch (e) { return (exc || "").toLowerCase(); }
  }
  if (Array.isArray(parsed)) {
    const last = parsed[parsed.length - 1];
    return (typeof last === "string" ? last : (last && last.message) || "").toLowerCase();
  }
  return ((parsed && parsed.message) || String(parsed)).toLowerCase();
}

function doCheckOut(checkoutReason) {
  const args = { latitude: latitude, longitude: longitude };
  if (checkoutReason) args.checkout_reason = checkoutReason;
  frappe.call({
    method: "alpinos.attendance_widget.check_out",
    args: args,
    silent: true,
    callback(r) {
      if (r.exc) {
        handleCheckoutError(r);
        return;
      }
      frappe.show_alert({ message: "Checked Out", indicator: "green" });
      stopTimer();
      setStatusBadge("Checked Out", "out");
      btn("btn-in", true);
      btn("btn-out", true);
      setPausedTimer(r.message ? r.message.elapsed_seconds : 0);
    },
    error(r) {
      handleCheckoutError(r);
    }
  });
}

function handleCheckoutError(r) {
  if (!r) { btn("btn-out", false); return; }
  const errMsg = getExcMessage(r.exc);
  if (errMsg.indexOf("provide a reason") !== -1 || errMsg.indexOf("outside the office location") !== -1) {
    frappe.hide_msgprint();
    showCheckoutReasonDialog(function(reason) { doCheckOut(reason); });
    btn("btn-out", false);
    return;
  }
  showError(r.exc);
  btn("btn-out", false);
}

function showCheckoutReasonDialog(onConfirm) {
  const d = new frappe.ui.Dialog({
    title: "Reason for Check Out (Outside Office)",
    primary_action_label: "Check Out",
    primary_action() {
      const reason = (d.$body.find(".checkout-reason-input").val() || "").trim();
      if (!reason) {
        frappe.msgprint("Please enter a reason for checking out from outside the office location.");
        return;
      }
      d.hide();
      onConfirm(reason);
    },
    secondary_action_label: "Cancel",
    secondary_action() {
      d.hide();
      btn("btn-out", false);
    }
  });
  d.$body.html(`
    <p style="color:#64748b;margin-bottom:12px;font-size:13px;">
      You are checking out from outside the office location. Please provide a reason (e.g. client visit, travel, WFH).
    </p>
    <textarea class="form-control checkout-reason-input" rows="3" placeholder="Enter reason..."></textarea>
  `);
  d.show();
}

function showWFHTaskDialog(wfhData, onConfirm, onCancel) {
  const statusOptions = `
    <option value="">Select...</option>
    <option value="Completed">Completed</option>
    <option value="In Progress">In Progress</option>
    <option value="Pending">Pending</option>
  `;

  const d = new frappe.ui.Dialog({
    title: "Work From Home \u2013 Daily Task Update",
    primary_action_label: "Save & Check Out",
    primary_action() {
      const rows = d.$body.find(".wfh-task-row");
      const tasks = [];
      let valid = true;
      rows.each(function() {
        const taskName = $(this).find(".wfh-task-name").val().trim();
        const status   = $(this).find(".wfh-task-status").val();
        if (!taskName && !status) return;
        if (!taskName) {
          frappe.msgprint("Task Name is required for all rows.");
          valid = false;
          return false;
        }
        if (!status) {
          frappe.msgprint("Status is required for all rows.");
          valid = false;
          return false;
        }
        tasks.push({ task_name: taskName, status: status });
      });
      if (!valid) return;
      if (!tasks.length) {
        frappe.msgprint("Please add at least one task before checking out.");
        return;
      }
      d.hide();
      onConfirm(tasks);
    },
    secondary_action_label: "Cancel",
    secondary_action() {
      d.hide();
      onCancel();
    }
  });

  d.$body.html(`
    <p style="color:#64748b;margin-bottom:14px;font-size:13px;">
      You have a Work From Home request for today. Please update your task details before checking out.
    </p>
    <table class="table table-bordered table-condensed" style="margin-bottom:8px;">
      <thead style="background:#f8fafc;">
        <tr>
          <th style="width:55%">Task Name <span style="color:red">*</span></th>
          <th style="width:35%">Status <span style="color:red">*</span></th>
          <th style="width:10%"></th>
        </tr>
      </thead>
      <tbody class="wfh-task-body"></tbody>
    </table>
    <button class="btn btn-xs btn-default wfh-add-row" style="margin-top:4px;">+ Add Row</button>
  `);

  function addRow(taskName, status) {
    const $row = $(`
      <tr class="wfh-task-row">
        <td><input type="text" class="form-control input-xs wfh-task-name" placeholder="Enter task name"></td>
        <td>
          <select class="form-control input-xs wfh-task-status">${statusOptions}</select>
        </td>
        <td style="text-align:center;vertical-align:middle;">
          <button class="btn btn-xs btn-danger wfh-remove-row" title="Remove">\xd7</button>
        </td>
      </tr>
    `);
    if (taskName) $row.find(".wfh-task-name").val(taskName);
    if (status)   $row.find(".wfh-task-status").val(status);
    d.$body.find(".wfh-task-body").append($row);
  }

  if (wfhData.tasks && wfhData.tasks.length) {
    wfhData.tasks.forEach(t => addRow(t.task_name, t.status));
  } else {
    addRow();
  }

  d.$body.on("click", ".wfh-remove-row", function() {
    $(this).closest("tr").remove();
    if (!d.$body.find(".wfh-task-row").length) addRow();
  });

  d.$body.on("click", ".wfh-add-row", function() {
    addRow();
  });

  d.show();
}

function startTimer(t){
  startTime=t;
  if(timer){ clearInterval(timer); }
  timer=setInterval(()=>{
    let d=new Date()-startTime;
    timerEl.innerText=formatDuration(d);
  },1000);
}

function stopTimer(){ if(timer){ clearInterval(timer); } }
function setPausedTimer(seconds){
  timerEl.innerText = formatDuration(seconds * 1000);
}
function resetUI(labelText){ setStatusBadge(labelText || "Not Checked In", "none"); btn("btn-in",false); btn("btn-out",true); timerEl.innerText="00:00:00"; }
function btn(id,dis){
  let el = root.querySelector("#"+id);
  el.disabled = dis;
  el.style.opacity = dis ? "0.6" : "1";
  el.style.cursor = dis ? "not-allowed" : "pointer";
}
function showError(err){
  let msg = err;
  try { msg = JSON.parse(err).message || err; } catch(e){}
  setStatusBadge(msg, "error");
  btn("btn-in", true);
  btn("btn-out", true);
  stopTimer();
  timerEl.innerText="00:00:00";
}
function setStatusBadge(text, state){
  statusEl.innerText = text;
  let styles = {
    in: { bg:"#d1fae5", border:"#a7f3d0", color:"#065f46" },
    out: { bg:"#fee2e2", border:"#fecaca", color:"#7f1d1d" },
    none: { bg:"#f1f5f9", border:"#cbd5e1", color:"#334155" },
    error: { bg:"#ffe8cc", border:"#ffd2a6", color:"#7c2d12" },
  };
  let s = styles[state] || styles.none;
  statusEl.style.background = s.bg;
  statusEl.style.borderColor = s.border;
  statusEl.style.color = s.color;
}
function formatDuration(ms){
  let h=String(Math.floor(ms/3600000)).padStart(2,"0");
  let m=String(Math.floor((ms%3600000)/60000)).padStart(2,"0");
  let s=String(Math.floor((ms%60000)/1000)).padStart(2,"0");
  return `${h}:${m}:${s}`;
}
"""

    if frappe.db.exists("Custom HTML Block", label):
        custom_block = frappe.get_doc("Custom HTML Block", label)
        custom_block.html = html
        custom_block.script = script
        custom_block.save(ignore_permissions=True)
    else:
        custom_block = frappe.get_doc(
            {
                "doctype": "Custom HTML Block",
                "name": label,
                "html": html,
                "script": script,
            }
        )
        custom_block.insert(ignore_permissions=True)

    # Check if custom block already exists on workspace
    exists = frappe.db.exists(
        "Workspace Custom Block",
        {
            "parent": workspace,
            "custom_block_name": label,
        },
    )

    if not exists:
        workspace_block = frappe.get_doc(
            {
                "doctype": "Workspace Custom Block",
                "parent": workspace,
                "parenttype": "Workspace",
                "parentfield": "custom_blocks",
                "custom_block_name": label,
                "label": label,
            }
        )

        workspace_block.insert(ignore_permissions=True)

    # -----------------------------
    # My Attendance Calendar widget
    # -----------------------------
    cal_label = "My Attendance Calendar"
    cal_html = """
<div id="alp-att-cal-widget" style="padding:22px 22px 18px;border-radius:20px;background:linear-gradient(135deg,#f3f4ff,#ffffff);min-height:340px;width:100%;max-width:980px;margin:0 auto;box-sizing:border-box;border:1px solid #e5e7eb;box-shadow:0 18px 45px rgba(15,23,42,0.06);">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px;">
    <h4 style="margin:0;font-size:17px;font-weight:600;color:#111827;letter-spacing:-0.02em;">My Attendance Calendar</h4>
    <div style="display:flex;align-items:center;gap:8px;">
      <span id="cal-prev-month" style="width:36px;height:36px;min-width:36px;border-radius:10px;border:1px solid #e5e7eb;background:#fafafa;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;font-size:20px;color:#6b7280;line-height:1;">&#8249;</span>
      <span id="cal-month-label" style="font-size:14px;font-weight:500;color:#374151;min-width:140px;text-align:center;">Loading...</span>
      <span id="cal-next-month" style="width:36px;height:36px;min-width:36px;border-radius:10px;border:1px solid #e5e7eb;background:#fafafa;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;font-size:20px;color:#6b7280;line-height:1;">&#8250;</span>
    </div>
  </div>
  <div id="alp-att-cal-weekdays" style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;text-align:center;font-size:10px;font-weight:500;color:#9ca3af;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:10px;max-width:760px;margin-left:auto;margin-right:auto;">
    <div style="padding:4px 2px;">Sun</div><div style="padding:4px 2px;">Mon</div><div style="padding:4px 2px;">Tue</div><div style="padding:4px 2px;">Wed</div><div style="padding:4px 2px;">Thu</div><div style="padding:4px 2px;">Fri</div><div style="padding:4px 2px;">Sat</div>
  </div>
  <div id="alp-att-cal-grid" style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;max-width:760px;margin-left:auto;margin-right:auto;"></div>

  <div style="margin-top:16px;font-size:10px;color:#9ca3af;display:flex;flex-wrap:wrap;gap:12px 16px;padding-top:14px;border-top:1px solid #f3f4f6;">
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#10003;</span> Present</span>
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#127968;</span> WFH</span>
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#10007;</span> Absent</span>
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#189;</span> Half Day</span>
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#127746;</span> Leave</span>
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#9728;</span> Holiday</span>
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#128340;</span> Late</span>
    <span style="display:inline-flex;align-items:center;gap:5px;"><span style="font-size:12px;opacity:0.9;">&#9201;</span> Early out</span>
  </div>

  <div id="alp-people-widget" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:20px;padding:18px 18px 12px;border-radius:18px;background:#f9fafb;border:1px solid #e5e7eb;">
    <div class="alp-dash-card" style="border-radius:12px;border:1px solid #E5E7EB;background:#FFFFFF;padding:16px;min-height:140px;box-sizing:border-box;transition:background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;" onmouseover="this.style.background='#F9FAFB';this.style.transform='translateY(-2px)';this.style.boxShadow='0 6px 14px rgba(0,0,0,0.06)';" onmouseout="this.style.background='#FFFFFF';this.style.transform='translateY(0)';this.style.boxShadow='none';">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
        <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#EC4899;flex-shrink:0;"></span>Upcoming Birthdays</span>
        <span style="font-size:10px;color:#6b7280;">Next 30 days</span>
      </div>
      <div id="alp-birthdays-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
    </div>
    <div class="alp-dash-card" style="border-radius:12px;border:1px solid #E5E7EB;background:#FFFFFF;padding:16px;min-height:140px;box-sizing:border-box;transition:background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;" onmouseover="this.style.background='#F9FAFB';this.style.transform='translateY(-2px)';this.style.boxShadow='0 6px 14px rgba(0,0,0,0.06)';" onmouseout="this.style.background='#FFFFFF';this.style.transform='translateY(0)';this.style.boxShadow='none';">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
        <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#6366F1;flex-shrink:0;"></span>Work Anniversaries</span>
        <span style="font-size:10px;color:#6b7280;">Next 30 days</span>
      </div>
      <div id="alp-anniversaries-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
    </div>
  </div>

  <div id="alp-on-leave-wfh-widget" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:20px;padding:18px 18px 12px;border-radius:18px;background:#f9fafb;border:1px solid #e5e7eb;">
    <div class="alp-dash-card" style="border-radius:12px;border:1px solid #E5E7EB;background:#FFFFFF;padding:16px;min-height:140px;box-sizing:border-box;transition:background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;" onmouseover="this.style.background='#F9FAFB';this.style.transform='translateY(-2px)';this.style.boxShadow='0 6px 14px rgba(0,0,0,0.06)';" onmouseout="this.style.background='#FFFFFF';this.style.transform='translateY(0)';this.style.boxShadow='none';">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
        <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#F59E0B;flex-shrink:0;"></span>Employees on Leave Today</span>
        <span style="font-size:10px;color:#6b7280;">Today</span>
      </div>
      <div id="alp-on-leave-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
    </div>
    <div class="alp-dash-card" style="border-radius:12px;border:1px solid #E5E7EB;background:#FFFFFF;padding:16px;min-height:140px;box-sizing:border-box;transition:background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;" onmouseover="this.style.background='#F9FAFB';this.style.transform='translateY(-2px)';this.style.boxShadow='0 6px 14px rgba(0,0,0,0.06)';" onmouseout="this.style.background='#FFFFFF';this.style.transform='translateY(0)';this.style.boxShadow='none';">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
        <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#10B981;flex-shrink:0;"></span>Employees on Work From Home Today</span>
        <span style="font-size:10px;color:#6b7280;">Today</span>
      </div>
      <div id="alp-on-wfh-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
    </div>
  </div>
</div>
"""

    cal_script = """
const root = root_element;
const monthLabel = root.querySelector("#cal-month-label");
const grid = root.querySelector("#alp-att-cal-grid");
const prevBtn = root.querySelector("#cal-prev-month");
const nextBtn = root.querySelector("#cal-next-month");

let current = new Date();

function changeMonth(delta) {
  const year = current.getFullYear();
  const month = current.getMonth() + 1 + delta;
  const d = new Date(year, month - 1, 1);
  loadMonth(d.getFullYear(), d.getMonth() + 1);
}

prevBtn.addEventListener("click", function () {
  changeMonth(-1);
});

nextBtn.addEventListener("click", function () {
  changeMonth(1);
});

function loadMonth(year, month) {
  current = new Date(year, month - 1, 1);
  monthLabel.innerText = current.toLocaleString("default", { month: "long", year: "numeric" });

  frappe.call({
    method: "alpinos.attendance_widget.get_monthly_attendance",
    args: { year: year, month: month },
    freeze: true,
    freeze_message: "Loading attendance...",
    callback: function (r) {
      if (r.exc) {
        frappe.msgprint("Could not load attendance calendar. Please try again.");
        return;
      }
      const data = r.message || {};
      renderCalendar(data.days || {}, year, month);
    },
  });
}

function timeToHHMM(t) {
  if (t == null || t === undefined || t === "") return "—";
  var s = String(t).trim();
  if (s === "—") return "—";
  if (s.indexOf("T") !== -1) s = s.split("T")[1] || s;
  if (s.indexOf(" ") !== -1) s = s.split(" ")[s.split(" ").length - 1] || s;
  var parts = s.split(":");
  if (parts.length >= 2) return parts[0] + ":" + parts[1];
  return s || "—";
}

function formatWorked(minutes) {
  if (minutes == null || minutes < 0) return "";
  var h = Math.floor(minutes / 60);
  var m = minutes % 60;
  if (h > 0 && m > 0) return h + "h " + m + "m";
  if (h > 0) return h + "h";
  return m + "m";
}

function getStatusIcon(status) {
  if (status === "Present") return "&#10003;";
  if (status === "Work From Home") return "&#127968;";
  if (status === "Absent") return "&#10007;";
  if (status === "Half Day") return "&#189;";
  if (status === "On Leave") return "&#127746;";
  if (status === "Holiday") return "&#9728;";
  return "&#8212;";
}

function getDayStyle(status, isToday) {
  var bg = "#f9fafb";
  if (status === "Present" || status === "Work From Home") bg = "#ecfdf5";
  else if (status === "Absent") bg = "#fef2f2";
  else if (status === "Half Day") bg = "#fffbeb";
  else if (status === "On Leave") bg = "#eff6ff";
  else if (status === "Holiday") bg = "#f3f4f6";
  var border = isToday ? "2px solid #3b82f6" : "1px solid #e5e7eb";
  var shadow = isToday ? "0 0 0 1px rgba(59,130,246,0.25)" : "none";
  return "border-radius:12px;padding:6px 6px;min-height:56px;display:flex;flex-direction:column;gap:2px;justify-content:center;align-items:flex-start;background:" + bg + ";border:" + border + ";box-shadow:" + shadow + ";box-sizing:border-box;cursor:pointer;";
}

function renderCalendar(days, year, month) {
  var first = new Date(year, month - 1, 1);
  var last = new Date(year, month, 0);
  var startWeekday = first.getDay();
  var totalDays = last.getDate();

  grid.innerHTML = "";
  grid.setAttribute("style", "display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;max-width:760px;margin-left:auto;margin-right:auto;");

  for (var i = 0; i < startWeekday; i++) {
    var emptyCell = document.createElement("div");
    emptyCell.setAttribute("style", "min-height:56px;box-sizing:border-box;");
    grid.appendChild(emptyCell);
  }

  var today = new Date();
  var todayKey = formatDateKey(today.getFullYear(), today.getMonth() + 1, today.getDate());

  for (var day = 1; day <= totalDays; day++) {
    var key = formatDateKey(year, month, day);
    var item = days[key] || {};
    var status = item.status || null;
    var isToday = key === todayKey;

    var cell = document.createElement("div");
    cell.setAttribute("style", getDayStyle(status, isToday));

    var head = document.createElement("div");
    head.setAttribute("style", "display:flex;align-items:center;justify-content:space-between;gap:4px;min-width:0;");
    var dayEl = document.createElement("span");
    dayEl.setAttribute("style", "font-weight:600;font-size:13px;color:#111827;");
    dayEl.textContent = String(day);
    var iconEl = document.createElement("span");
    iconEl.setAttribute("style", "font-size:13px;line-height:1;color:#6b7280;flex-shrink:0;");
    iconEl.innerHTML = getStatusIcon(status);
    head.appendChild(dayEl);
    head.appendChild(iconEl);
    cell.appendChild(head);

    var ci = timeToHHMM(item.check_in);
    var co = timeToHHMM(item.check_out);
    var worked = formatWorked(item.worked_minutes);

    var badges = [];
    if (item.late_coming) badges.push("&#128340; Late");
    if (item.early_leaving) badges.push("&#9201; Early");

    var badgeText = badges.join(" ");

    cell.setAttribute(
      "title",
      key +
        " — " +
        (status || "Not Marked") +
        " — In: " +
        (item.check_in || "—") +
        " Out: " +
        (item.check_out || "—") +
        (worked ? " — " + worked + " worked" : "") +
        (badgeText ? " — " + badgeText.replace(/&#128340;/g, \"Late\").replace(/&#9201;/g, \"Early\") : \"\")
    );

    grid.appendChild(cell);
  }
}

function formatDateKey(year, month, day) {
  const m = String(month).padStart(2, "0");
  const d = String(day).padStart(2, "0");
  return `${year}-${m}-${d}`;
}

// initial load
loadMonth(current.getFullYear(), current.getMonth() + 1);

// Load Birthdays & Anniversaries (embedded in same block)
(function () {
  var birthdaysList = root.querySelector("#alp-birthdays-list");
  var anniversariesList = root.querySelector("#alp-anniversaries-list");
  if (!birthdaysList && !anniversariesList) return;
  if (birthdaysList) birthdaysList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
  if (anniversariesList) anniversariesList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
  frappe.call({
    method: "alpinos.people_events.get_upcoming_birthdays_and_anniversaries",
    args: { days: 30 },
    freeze: false,
    callback: function (r) {
      if (r.exc) {
        if (birthdaysList) birthdaysList.innerHTML = "<span style='color:#9ca3af;'>Unable to load</span>";
        if (anniversariesList) anniversariesList.innerHTML = "<span style='color:#9ca3af;'>Unable to load</span>";
        return;
      }
      var data = r.message || {};
      function renderList(container, items, emptyText, isAnniv) {
        if (!container) return;
        container.innerHTML = "";
        if (!items || !items.length) {
          container.innerHTML = "<span style='color:#9ca3af;'>" + emptyText + "</span>";
          return;
        }
        items.forEach(function (item) {
          var row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";
          var left = document.createElement("div");
          left.style.cssText = "display:flex;flex-direction:column;gap:2px;min-width:0;";
          var name = document.createElement("div");
          name.style.cssText = "font-size:11px;font-weight:500;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
          name.textContent = item.employee_name || "";
          left.appendChild(name);
          if (item.company) {
            var company = document.createElement("div");
            company.style.cssText = "font-size:10px;color:#9ca3af;";
            company.textContent = item.company;
            left.appendChild(company);
          }
          var right = document.createElement("div");
          right.style.cssText = "display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0;";
          var day = document.createElement("div");
          day.style.cssText = "font-size:10px;color:#4b5563;";
          day.textContent = item.day || "";
          right.appendChild(day);
          if (isAnniv && item.years) {
            var years = document.createElement("div");
            years.style.cssText = "font-size:10px;color:#2563eb;font-weight:500;";
            years.textContent = item.years + " yr";
            right.appendChild(years);
          }
          row.appendChild(left);
          row.appendChild(right);
          container.appendChild(row);
        });
      }
      renderList(birthdaysList, data.birthdays || [], "No upcoming birthdays", false);
      renderList(anniversariesList, data.anniversaries || [], "No upcoming anniversaries", true);
    },
  });
})();

// On Leave Today & On WFH Today (visible to HR Manager or reporting managers only)
(function () {
  var onLeaveList = root.querySelector("#alp-on-leave-list");
  var onWfhList = root.querySelector("#alp-on-wfh-list");
  var widget = root.querySelector("#alp-on-leave-wfh-widget");
  if (!widget) return;
  if (onLeaveList) onLeaveList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
  if (onWfhList) onWfhList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
  frappe.call({
    method: "alpinos.people_events.get_on_leave_and_wfh_today",
    freeze: false,
    callback: function (r) {
      if (r.exc) {
        widget.style.display = "none";
        return;
      }
      var data = r.message || {};
      if (!data.allowed) {
        widget.style.display = "none";
        return;
      }
      function renderOnLeave(containerEl, items) {
        if (!containerEl) return;
        containerEl.innerHTML = "";
        if (!items || !items.length) {
          containerEl.innerHTML = "<span style='color:#9ca3af;'>No one on leave today</span>";
          return;
        }
        items.forEach(function (item) {
          var row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";
          var left = document.createElement("div");
          left.style.cssText = "display:flex;flex-direction:column;gap:2px;min-width:0;";
          var name = document.createElement("div");
          name.style.cssText = "font-size:11px;font-weight:500;color:#111827;";
          name.textContent = item.employee_name || item.employee || "";
          left.appendChild(name);
          var leaveType = document.createElement("div");
          leaveType.style.cssText = "font-size:10px;color:#6b7280;";
          leaveType.textContent = (item.leave_type || "") + (item.half_day ? " (Half day)" : "");
          left.appendChild(leaveType);
          var right = document.createElement("div");
          right.style.cssText = "font-size:10px;color:#4b5563;flex-shrink:0;";
          right.textContent = (item.from_date || "") + " to " + (item.to_date || "");
          row.appendChild(left);
          row.appendChild(right);
          containerEl.appendChild(row);
        });
      }
      function renderOnWfh(containerEl, items) {
        if (!containerEl) return;
        containerEl.innerHTML = "";
        if (!items || !items.length) {
          containerEl.innerHTML = "<span style='color:#9ca3af;'>No one on WFH today</span>";
          return;
        }
        items.forEach(function (item) {
          var row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";
          var name = document.createElement("div");
          name.style.cssText = "font-size:11px;font-weight:500;color:#111827;";
          name.textContent = item.employee_name || item.employee || "";
          row.appendChild(name);
          containerEl.appendChild(row);
        });
      }
      renderOnLeave(onLeaveList, data.on_leave || []);
      renderOnWfh(onWfhList, data.on_wfh || []);
    },
  });
})();
"""

    if frappe.db.exists("Custom HTML Block", cal_label):
        cal_block = frappe.get_doc("Custom HTML Block", cal_label)
        cal_block.html = cal_html
        cal_block.script = cal_script
        cal_block.save(ignore_permissions=True)
    else:
        cal_block = frappe.get_doc(
            {
                "doctype": "Custom HTML Block",
                "name": cal_label,
                "html": cal_html,
                "script": cal_script,
            }
        )
        cal_block.insert(ignore_permissions=True)

    cal_exists = frappe.db.exists(
        "Workspace Custom Block",
        {
            "parent": workspace,
            "custom_block_name": cal_label,
        },
    )

    if not cal_exists:
        cal_workspace_block = frappe.get_doc(
            {
                "doctype": "Workspace Custom Block",
                "parent": workspace,
                "parenttype": "Workspace",
                "parentfield": "custom_blocks",
                "custom_block_name": cal_label,
                "label": cal_label,
            }
        )

        cal_workspace_block.insert(ignore_permissions=True)

    workspace_doc = frappe.get_doc("Workspace", workspace)
    blocks = json.loads(workspace_doc.content or "[]")
    already_added = any(
        block.get("type") == "custom_block"
        and block.get("data", {}).get("custom_block_name") == label
        for block in blocks
    )

    if not already_added:
        custom_block_item = {
            "id": frappe.generate_hash(length=10),
            "type": "custom_block",
            "data": {
                "custom_block_name": label,
                "col": 12,
            },
        }
        blocks.insert(1, custom_block_item)

    # ensure calendar widget also present
    has_calendar = any(
        block.get("type") == "custom_block"
        and block.get("data", {}).get("custom_block_name") == cal_label
        for block in blocks
    )

    if not has_calendar:
        blocks.insert(
            2,
            {
                "id": frappe.generate_hash(length=10),
                "type": "custom_block",
                "data": {
                    "custom_block_name": cal_label,
                    "col": 12,
                },
            },
        )

    # -----------------------------
    # Upcoming Birthdays & Anniversaries (separate block below calendar)
    # -----------------------------
    people_label = "Upcoming Birthdays & Anniversaries"
    people_html = """
<div id="alp-people-widget" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;padding:20px;border:1px solid #e5e7eb;border-radius:16px;background:#ffffff;width:100%;max-width:100%;box-sizing:border-box;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
  <div style="border-radius:14px;border:1px solid #e5e7eb;background:#f9fafb;padding:16px;min-height:140px;box-sizing:border-box;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
      <span style="font-size:13px;font-weight:600;color:#111827;">Upcoming Birthdays</span>
      <span style="font-size:10px;color:#9ca3af;">Next 30 days</span>
    </div>
    <div id="alp-birthdays-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
  </div>
  <div style="border-radius:14px;border:1px solid #e5e7eb;background:#f9fafb;padding:16px;min-height:140px;box-sizing:border-box;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
      <span style="font-size:13px;font-weight:600;color:#111827;">Work Anniversaries</span>
      <span style="font-size:10px;color:#9ca3af;">Next 30 days</span>
    </div>
    <div id="alp-anniversaries-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
  </div>
</div>
"""
    people_script = """
var root = root_element;
var birthdaysList = root.querySelector("#alp-birthdays-list");
var anniversariesList = root.querySelector("#alp-anniversaries-list");
if (birthdaysList) birthdaysList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
if (anniversariesList) anniversariesList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";

frappe.call({
  method: "alpinos.people_events.get_upcoming_birthdays_and_anniversaries",
  args: { days: 30 },
  freeze: false,
  callback: function (r) {
    if (r.exc) {
      if (birthdaysList) birthdaysList.innerHTML = "<span style='color:#9ca3af;'>Unable to load</span>";
      if (anniversariesList) anniversariesList.innerHTML = "<span style='color:#9ca3af;'>Unable to load</span>";
      return;
    }
    var data = r.message || {};
    function renderList(container, items, emptyText, isAnniv) {
      if (!container) return;
      container.innerHTML = "";
      if (!items || !items.length) {
        container.innerHTML = "<span style='color:#9ca3af;'>" + emptyText + "</span>";
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";
        var left = document.createElement("div");
        left.style.cssText = "display:flex;flex-direction:column;gap:2px;min-width:0;";
        var name = document.createElement("div");
        name.style.cssText = "font-size:11px;font-weight:500;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
        name.textContent = item.employee_name || "";
        left.appendChild(name);
        if (item.company) {
          var company = document.createElement("div");
          company.style.cssText = "font-size:10px;color:#9ca3af;";
          company.textContent = item.company;
          left.appendChild(company);
        }
        var right = document.createElement("div");
        right.style.cssText = "display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0;";
        var day = document.createElement("div");
        day.style.cssText = "font-size:10px;color:#4b5563;";
        day.textContent = item.day || "";
        right.appendChild(day);
        if (isAnniv && item.years) {
          var years = document.createElement("div");
          years.style.cssText = "font-size:10px;color:#2563eb;font-weight:500;";
          years.textContent = item.years + " yr";
          right.appendChild(years);
        }
        row.appendChild(left);
        row.appendChild(right);
        container.appendChild(row);
      });
    }
    renderList(birthdaysList, data.birthdays || [], "No upcoming birthdays", false);
    renderList(anniversariesList, data.anniversaries || [], "No upcoming anniversaries", true);
  },
});
"""
    if frappe.db.exists("Custom HTML Block", people_label):
        people_block = frappe.get_doc("Custom HTML Block", people_label)
        people_block.html = people_html
        people_block.script = people_script
        people_block.save(ignore_permissions=True)
    else:
        people_block = frappe.get_doc({
            "doctype": "Custom HTML Block",
            "name": people_label,
            "html": people_html,
            "script": people_script,
        })
        people_block.insert(ignore_permissions=True)

    people_exists = frappe.db.exists(
        "Workspace Custom Block",
        {"parent": workspace, "custom_block_name": people_label},
    )
    if not people_exists:
        frappe.get_doc({
            "doctype": "Workspace Custom Block",
            "parent": workspace,
            "parenttype": "Workspace",
            "parentfield": "custom_blocks",
            "custom_block_name": people_label,
            "label": people_label,
        }).insert(ignore_permissions=True)

    # Remove people block from wherever it is so we can place it at index 3
    people_block_item = {
        "id": frappe.generate_hash(length=10),
        "type": "custom_block",
        "data": {"custom_block_name": people_label, "col": 12},
    }
    blocks = [b for b in blocks if not (
        b.get("type") == "custom_block"
        and (b.get("data") or {}).get("custom_block_name") == people_label
    )]
    # Insert right after calendar (index 3) so it appears below calendar, above shortcuts
    insert_idx = min(3, len(blocks))
    blocks.insert(insert_idx, people_block_item)

    workspace_doc.content = json.dumps(blocks)
    workspace_doc.save(ignore_permissions=True)
    workspace_doc.clear_cache()

    frappe.db.commit()

