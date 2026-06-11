"""Add a "Pending Approvals" block to a dedicated Approvals workspace.

Shows the requests awaiting the current user's approval (HR sees all; a reporting manager
sees their direct reports'). Data: alpinos.approval_dashboard.get_pending_approvals.
"""

import json

import frappe

LABEL = "Pending Approvals"
WORKSPACE = "Approvals"

HTML = """
<div id="alp-approvals-widget" style="padding:20px;border:1px solid var(--border-color);border-radius:16px;background:var(--card-bg);width:100%;max-width:100%;box-sizing:border-box;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:8px;flex-wrap:wrap;">
    <span style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;color:var(--heading-color);"><span style="width:8px;height:8px;border-radius:50%;background:#6366f1;flex-shrink:0;"></span>Pending Approvals</span>
    <span id="alp-approvals-sub" style="font-size:11px;color:var(--text-muted);">Requests awaiting your action</span>
  </div>
  <div id="alp-approvals-body" style="font-size:12px;color:var(--text-color);overflow-x:auto;"></div>
</div>
"""

SCRIPT = """
var root = root_element;
var widget = root.querySelector("#alp-approvals-widget");
var body = root.querySelector("#alp-approvals-body");
var sub = root.querySelector("#alp-approvals-sub");
if (body) body.innerHTML = "<span style='color:var(--text-muted);'>Loading...</span>";

frappe.call({
  method: "alpinos.approval_dashboard.get_pending_approvals",
  freeze: false,
  callback: function (r) {
    if (r.exc) { if (widget) widget.style.display = "none"; return; }
    var data = r.message || {};
    if (!data.allowed) { if (widget) widget.style.display = "none"; return; }
    var items = data.items || [];
    if (!items.length) {
      if (sub) sub.textContent = "Nothing pending \\u2705";
      body.innerHTML = "<span style='color:#16a34a;'>No requests are waiting for your approval.</span>";
      return;
    }
    if (sub) sub.textContent = items.length + " pending";
    function esc(s) {
      return (s == null ? "" : String(s)).replace(/[&<>\"']/g, function (c) {
        return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
      });
    }
    var th = "padding:6px 10px;border:1px solid var(--border-color);text-align:left;background:var(--bg-color);font-weight:600;color:var(--text-color);";
    var td = "padding:6px 10px;border:1px solid var(--border-color);";
    var PAGE = 10;
    var shown = PAGE;
    function render() {
      var n = Math.min(shown, items.length);
      var html = "<table style='border-collapse:collapse;font-size:12px;width:100%;'>"
        + "<thead><tr>"
        + "<th style='" + th + "'>Type</th>"
        + "<th style='" + th + "'>Employee</th>"
        + "<th style='" + th + "'>Date</th>"
        + "<th style='" + th + "'>Request</th>"
        + "</tr></thead><tbody>";
      for (var i = 0; i < n; i++) {
        var it = items[i];
        var emp = it.employee_name || it.employee || "";
        var url = "/app/" + it.route + "/" + encodeURIComponent(it.name);
        html += "<tr>"
          + "<td style='" + td + "'><span style='font-weight:600;'>" + esc(it.type) + "</span></td>"
          + "<td style='" + td + "'>" + esc(emp) + "</td>"
          + "<td style='" + td + "'>" + esc(it.date) + "</td>"
          + "<td style='" + td + "'><a href='" + url + "' style='color:var(--text-color);text-decoration:underline;'>" + esc(it.name) + "</a></td>"
          + "</tr>";
      }
      html += "</tbody></table>";
      if (items.length > n) {
        html += "<div style='margin-top:10px;text-align:center;'>"
          + "<button id='alp-appr-more' style='padding:6px 14px;font-size:12px;border:1px solid var(--border-color);border-radius:8px;background:var(--bg-color);color:var(--text-color);cursor:pointer;'>Load more (" + (items.length - n) + ")</button>"
          + "</div>";
      }
      body.innerHTML = html;
      var btn = root.querySelector("#alp-appr-more");
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

	# 2. Create the Approvals workspace if it doesn't exist.
	if not frappe.db.exists("Workspace", WORKSPACE):
		content = [
			{"id": frappe.generate_hash(length=10), "type": "header",
			 "data": {"text": "<span class='h4'>Pending Approvals</span>", "col": 12}},
			{"id": frappe.generate_hash(length=10), "type": "custom_block",
			 "data": {"custom_block_name": LABEL, "col": 12}},
		]
		ws = frappe.get_doc(
			{
				"doctype": "Workspace",
				"name": WORKSPACE,
				"title": WORKSPACE,
				"label": WORKSPACE,
				"public": 1,
				"icon": "todo",
				"content": json.dumps(content),
			}
		)
		ws.append("custom_blocks", {"custom_block_name": LABEL, "label": LABEL})
		ws.insert(ignore_permissions=True)
		frappe.db.commit()
		return

	# 3. Workspace exists — ensure the block + layout entry are present (idempotent).
	if not frappe.db.exists("Workspace Custom Block", {"parent": WORKSPACE, "custom_block_name": LABEL}):
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

	ws = frappe.get_doc("Workspace", WORKSPACE)
	blocks = json.loads(ws.content or "[]")
	if not any(
		b.get("type") == "custom_block" and (b.get("data") or {}).get("custom_block_name") == LABEL
		for b in blocks
	):
		blocks.append(
			{"id": frappe.generate_hash(length=10), "type": "custom_block",
			 "data": {"custom_block_name": LABEL, "col": 12}}
		)
		ws.content = json.dumps(blocks)
		ws.save(ignore_permissions=True)
		ws.clear_cache()
	frappe.db.commit()
