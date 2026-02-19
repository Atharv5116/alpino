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
}

function doCheckOut() {
  frappe.call({
    method:"alpinos.attendance_widget.check_out",
    args: {
      latitude: latitude,
      longitude: longitude,
    },
    callback(r){
      if(r.exc){
        showError(r.exc);
        btn("btn-out", false);
        return;
      }
      frappe.show_alert({message:"Checked Out",indicator:"red"});
      stopTimer();
      setStatusBadge("Checked Out", "out");
      btn("btn-in",true);
      btn("btn-out",true);
      setPausedTimer(r.message ? r.message.elapsed_seconds : 0);
    }
  });
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
        workspace_doc.content = json.dumps(blocks)
        workspace_doc.save(ignore_permissions=True)

    frappe.db.commit()

