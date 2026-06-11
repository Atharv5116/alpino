"""Add a "Missing Check-ins Today" block to the Home workspace.

Shows active employees with no check-in by 11:30 AM today and no approved leave
(same data as the scheduled email). Visible to HR Managers (all employees) and to
reporting managers (their direct reports only); hidden for everyone else.

Data + gate: alpinos.attendance_alerts.get_missing_checkins_today.
"""

import json

import frappe

LABEL = "Missing Check-ins Today"
LIFECYCLE_LABEL = "Upcoming HR Activities"
WORKSPACE = "Home"

HTML = """
<div id="alp-missing-checkin-widget" style="padding:20px;border:1px solid #e5e7eb;border-radius:16px;background:#ffffff;width:100%;max-width:100%;box-sizing:border-box;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:8px;flex-wrap:wrap;">
    <span style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#ef4444;flex-shrink:0;"></span>Missing Check-ins Today</span>
    <span id="alp-missing-checkin-sub" style="font-size:11px;color:#9ca3af;">By 11:30 AM &middot; no approved leave</span>
  </div>
  <div id="alp-missing-checkin-body" style="font-size:12px;color:#4b5563;overflow-x:auto;"></div>
</div>
"""

SCRIPT = """
var root = root_element;
var widget = root.querySelector("#alp-missing-checkin-widget");
var body = root.querySelector("#alp-missing-checkin-body");
if (body) body.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";

frappe.call({
  method: "alpinos.attendance_alerts.get_missing_checkins_today",
  freeze: false,
  callback: function (r) {
    if (r.exc) { if (widget) widget.style.display = "none"; return; }
    var data = r.message || {};
    if (!data.allowed) { if (widget) widget.style.display = "none"; return; }
    var items = data.employees || [];
    var sub = root.querySelector("#alp-missing-checkin-sub");
    if (data.before_cutoff) {
      if (sub) sub.textContent = "Available after 11:30 AM";
      body.innerHTML = "<span style='color:#9ca3af;'>The 11:30 AM cutoff hasn't passed yet \\u2014 check back after 11:30 AM.</span>";
      return;
    }
    if (!items.length) {
      if (sub) sub.textContent = "By 11:30 AM \\u00b7 no approved leave";
      body.innerHTML = "<span style='color:#16a34a;'>Everyone has checked in (or is on leave). \\u2705</span>";
      return;
    }
    if (sub) sub.textContent = "By 11:30 AM \\u00b7 no approved leave \\u00b7 " + items.length + " total";
    function esc(s) {
      return (s == null ? "" : String(s)).replace(/[&<>\"']/g, function (c) {
        return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
      });
    }
    var th = "padding:6px 10px;border:1px solid #e5e7eb;text-align:left;background:#f9fafb;font-weight:600;color:#374151;";
    var td = "padding:6px 10px;border:1px solid #e5e7eb;";
    var PAGE = 8;
    var shown = PAGE;
    function render() {
      var n = Math.min(shown, items.length);
      var html = "<table style='border-collapse:collapse;font-size:12px;width:100%;'>"
        + "<thead><tr>"
        + "<th style='" + th + "'>Sr No.</th>"
        + "<th style='" + th + "'>Employee ID/Name</th>"
        + "<th style='" + th + "'>Date</th>"
        + "<th style='" + th + "'>Department</th>"
        + "</tr></thead><tbody>";
      for (var i = 0; i < n; i++) {
        var it = items[i];
        var idName = it.employee + (it.employee_name ? " \\u2014 " + it.employee_name : "");
        html += "<tr>"
          + "<td style='" + td + "'>" + (i + 1) + "</td>"
          + "<td style='" + td + "'>" + esc(idName) + "</td>"
          + "<td style='" + td + "'>" + esc(it.date) + "</td>"
          + "<td style='" + td + "'>" + esc(it.department) + "</td>"
          + "</tr>";
      }
      html += "</tbody></table>";
      if (items.length > n) {
        html += "<div style='margin-top:10px;text-align:center;'>"
          + "<button id='alp-mc-more' style='padding:6px 14px;font-size:12px;border:1px solid #d1d5db;border-radius:8px;background:#f9fafb;color:#374151;cursor:pointer;'>Load more (" + (items.length - n) + ")</button>"
          + "</div>";
      }
      body.innerHTML = html;
      var btn = root.querySelector("#alp-mc-more");
      if (btn) btn.onclick = function () { shown += PAGE; render(); };
    }
    render();
  },
});
"""


def execute():
	# 1. Upsert the Custom HTML Block.
	if frappe.db.exists("Custom HTML Block", LABEL):
		block = frappe.get_doc("Custom HTML Block", LABEL)
		block.html = HTML
		block.script = SCRIPT
		block.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{"doctype": "Custom HTML Block", "name": LABEL, "html": HTML, "script": SCRIPT}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Workspace", WORKSPACE):
		frappe.db.commit()
		return

	# 2. Ensure the Workspace Custom Block child row exists.
	if not frappe.db.exists(
		"Workspace Custom Block", {"parent": WORKSPACE, "custom_block_name": LABEL}
	):
		frappe.get_doc(
			{
				"doctype": "Workspace Custom Block",
				"parent": WORKSPACE,
				"parenttype": "Workspace",
				"parentfield": "custom_blocks",
				"custom_block_name": LABEL,
				"label": LABEL,
			}
		).insert(ignore_permissions=True)

	# 3. Place it just after the "Upcoming HR Activities" block (or at the end).
	workspace_doc = frappe.get_doc("Workspace", WORKSPACE)
	blocks = json.loads(workspace_doc.content or "[]")
	blocks = [
		b
		for b in blocks
		if not (
			b.get("type") == "custom_block"
			and (b.get("data") or {}).get("custom_block_name") == LABEL
		)
	]
	insert_idx = len(blocks)
	for i, b in enumerate(blocks):
		if (
			b.get("type") == "custom_block"
			and (b.get("data") or {}).get("custom_block_name") == LIFECYCLE_LABEL
		):
			insert_idx = i + 1
			break
	blocks.insert(
		insert_idx,
		{
			"id": frappe.generate_hash(length=10),
			"type": "custom_block",
			"data": {"custom_block_name": LABEL, "col": 12},
		},
	)
	workspace_doc.content = json.dumps(blocks)
	workspace_doc.save(ignore_permissions=True)
	workspace_doc.clear_cache()
	frappe.db.commit()
