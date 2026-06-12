import json
import os

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
      let status = r.message ? r.message.status : "NONE";
  if(status === "IN"){
    setStatusBadge("Checked In", "in");
    btn("btn-in",true);
    btn("btn-out",false);
        if(r.message && r.message.last_time){
          startTimer(new Date(r.message.last_time));
        }
        return;
      }
  if(status === "OUT"){
    setStatusBadge("Checked Out", "out");
    btn("btn-in",true);
    btn("btn-out",true);
        setPausedTimer(r.message ? r.message.elapsed_seconds : 0);
        return;
      }
  resetUI();
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
  frappe.call({
    method:"alpinos.attendance_widget.log_frontend_action",
    args: { action: "WIDGET_CHECKIN_CLICK", log_type: "IN", details: "User clicked Check In button on Attendance widget." },
    silent: true
  });
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
  frappe.call({
    method:"alpinos.attendance_widget.log_frontend_action",
    args: { action: "WIDGET_CHECKOUT_CLICK", log_type: "OUT", details: "User clicked Check Out button on Attendance widget before any confirm dialogs." },
    silent: true
  });
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

function doCheckOut(outside) {
  const args = { latitude: latitude, longitude: longitude };
  if (outside && outside.reason) {
    args.outside_reason = outside.reason;
    if (outside.remarks) args.outside_remarks = outside.remarks;
  }
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
    showCheckoutReasonDialog(function(outside) { doCheckOut(outside); });
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
      const reason = (d.$body.find(".checkout-reason-select").val() || "").trim();
      const remarks = (d.$body.find(".checkout-remarks-input").val() || "").trim();
      if (!reason) {
        frappe.msgprint("Please select a reason for checking out from outside the office location.");
        return;
      }
      if (reason === "Other" && !remarks) {
        frappe.msgprint("Please add an explanation for 'Other'.");
        return;
      }
      d.hide();
      onConfirm({ reason: reason, remarks: remarks });
    },
    secondary_action_label: "Cancel",
    secondary_action() {
      d.hide();
      btn("btn-out", false);
    }
  });
  d.$body.html(`
    <p style="color:#64748b;margin-bottom:12px;font-size:13px;">
      You are checking out from outside the office location. Please select a reason.
    </p>
    <select class="form-control checkout-reason-select" style="margin-bottom:10px;">
      <option value="">Select reason...</option>
      <option value="Client/Vendor">Client/Vendor</option>
      <option value="Shoot">Shoot</option>
      <option value="Meeting">Meeting</option>
      <option value="Other">Other</option>
    </select>
    <textarea class="form-control checkout-remarks-input" rows="2" placeholder="Explanation / remarks (required for 'Other')" style="display:none;"></textarea>
  `);
  d.$body.find(".checkout-reason-select").on("change", function () {
    d.$body.find(".checkout-remarks-input").toggle($(this).val() === "Other");
  });
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
function resetUI(){ setStatusBadge("Not Checked In", "none"); btn("btn-in",false); btn("btn-out",true); timerEl.innerText="00:00:00"; }
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
    _wdir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(_wdir, "attendance_calendar.html"), encoding="utf-8") as _f:
        cal_html = _f.read()
    with open(os.path.join(_wdir, "attendance_calendar.js"), encoding="utf-8") as _f:
        cal_script = _f.read()

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

    # Keep exactly one calendar: ours (cal_label). Remove any OTHER block that renders the
    # calendar grid (a leftover site-side manual calendar with a different name), then make sure
    # ours is present. This self-heals the "two calendars" case on every migrate — no manual
    # cleanup needed.
    def _is_other_calendar(block):
        if block.get("type") != "custom_block":
            return False
        nm = (block.get("data") or {}).get("custom_block_name")
        if not nm or nm == cal_label:
            return False
        block_html = frappe.db.get_value("Custom HTML Block", nm, "html") or ""
        return "alp-att-cal-grid" in block_html

    for stale in [b for b in blocks if _is_other_calendar(b)]:
        nm = stale["data"]["custom_block_name"]
        for wcb in frappe.get_all(
            "Workspace Custom Block", filters={"parent": workspace, "custom_block_name": nm}, pluck="name"
        ):
            frappe.delete_doc("Workspace Custom Block", wcb, force=1, ignore_permissions=True)
        blocks.remove(stale)

    has_calendar = any(
        b.get("type") == "custom_block" and (b.get("data") or {}).get("custom_block_name") == cal_label
        for b in blocks
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
    <div id="alp-birthdays-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;max-height:200px;overflow-y:auto;padding-right:4px;"></div>
  </div>
  <div style="border-radius:14px;border:1px solid #e5e7eb;background:#f9fafb;padding:16px;min-height:140px;box-sizing:border-box;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
      <span style="font-size:13px;font-weight:600;color:#111827;">Work Anniversaries</span>
      <span style="font-size:10px;color:#9ca3af;">Next 30 days</span>
    </div>
    <div id="alp-anniversaries-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;max-height:200px;overflow-y:auto;padding-right:4px;"></div>
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

