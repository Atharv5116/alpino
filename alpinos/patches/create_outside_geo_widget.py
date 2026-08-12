"""Add an "Outside Geo-Location Check-ins" block to the Alpinos workspace (HR review).

Data: alpinos.outside_geo_checkins.get_outside_geo_checkins. Visible to HR roles only.
"""

import json

import frappe

LABEL = "Outside Geo-Location Check-ins"
WORKSPACE = "Home"
# Placed just below the "Missing Check-ins Today" HR block on the Home workspace.
ANCHOR_LABEL = "Missing Check-ins Today"
OLD_WORKSPACE = "Alpinos"  # the earlier (wrong) placement — cleaned up on migrate

HTML = """
<div id="alp-outgeo-widget" style="padding:20px;border:1px solid #e5e7eb;border-radius:16px;background:#ffffff;width:100%;max-width:100%;box-sizing:border-box;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:8px;flex-wrap:wrap;">
    <span style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;flex-shrink:0;"></span>Outside Geo-Location Check-ins</span>
    <span id="alp-outgeo-sub" style="font-size:11px;color:#9ca3af;">Today</span>
  </div>
  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
    <input type="date" id="alp-outgeo-from" style="padding:5px 8px;font-size:12px;border:1px solid #d1d5db;border-radius:8px;color:#374151;">
    <span style="color:#9ca3af;font-size:12px;">to</span>
    <input type="date" id="alp-outgeo-to" style="padding:5px 8px;font-size:12px;border:1px solid #d1d5db;border-radius:8px;color:#374151;">
    <button id="alp-outgeo-apply" style="padding:6px 14px;font-size:12px;border:1px solid #d1d5db;border-radius:8px;background:#f9fafb;color:#374151;cursor:pointer;">Apply</button>
    <button id="alp-outgeo-export" style="padding:6px 14px;font-size:12px;border:1px solid #2563eb;border-radius:8px;background:#2563eb;color:#ffffff;cursor:pointer;">Export Excel</button>
  </div>
  <div id="alp-outgeo-body" style="font-size:12px;color:#4b5563;overflow-x:auto;"></div>
</div>
"""

SCRIPT = """
var root = root_element;
var widget = root.querySelector("#alp-outgeo-widget");
var body = root.querySelector("#alp-outgeo-body");
var sub = root.querySelector("#alp-outgeo-sub");
var fromEl = root.querySelector("#alp-outgeo-from");
var toEl = root.querySelector("#alp-outgeo-to");
var applyBtn = root.querySelector("#alp-outgeo-apply");
var exportBtn = root.querySelector("#alp-outgeo-export");

var today = frappe.datetime.get_today();
if (fromEl && !fromEl.value) fromEl.value = today;
if (toEl && !toEl.value) toEl.value = today;

function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>\"']/g, function (c) {
    return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
  });
}
var th = "padding:6px 10px;border:1px solid #e5e7eb;text-align:left;background:#f9fafb;font-weight:600;color:#374151;";
var td = "padding:6px 10px;border:1px solid #e5e7eb;";
var PAGE = 8;
var _items = [];
var _shown = PAGE;

function draw() {
  var items = _items;
  var n = Math.min(_shown, items.length);
  var html = "<table style='border-collapse:collapse;font-size:12px;width:100%;'>"
    + "<thead><tr>"
    + "<th style='" + th + "'>Employee Name</th>"
    + "<th style='" + th + "'>Department</th>"
    + "<th style='" + th + "'>Check-In Date</th>"
    + "<th style='" + th + "'>Check-In Time</th>"
    + "<th style='" + th + "'>Reason</th>"
    + "<th style='" + th + "'>Explanation / Remarks</th>"
    + "</tr></thead><tbody>";
  for (var i = 0; i < n; i++) {
    var it = items[i];
    html += "<tr>"
      + "<td style='" + td + "'>" + esc(it.employee_name || it.employee) + "</td>"
      + "<td style='" + td + "'>" + esc(it.department) + "</td>"
      + "<td style='" + td + "'>" + esc(it.date) + "</td>"
      + "<td style='" + td + "'>" + esc(it.checkin_time) + "</td>"
      + "<td style='" + td + "'>" + esc(it.reason) + "</td>"
      + "<td style='" + td + "'>" + esc(it.remarks) + "</td>"
      + "</tr>";
  }
  html += "</tbody></table>";
  if (items.length > n) {
    html += "<div style='margin-top:10px;text-align:center;'>"
      + "<button id='alp-outgeo-more' style='padding:6px 14px;font-size:12px;border:1px solid #d1d5db;border-radius:8px;background:#f9fafb;color:#374151;cursor:pointer;'>Load more (" + (items.length - n) + ")</button>"
      + "</div>";
  }
  body.innerHTML = html;
  var btn = root.querySelector("#alp-outgeo-more");
  if (btn) btn.onclick = function () { _shown += PAGE; draw(); };
}

function load() {
  var f = (fromEl && fromEl.value) || today;
  var t = (toEl && toEl.value) || today;
  if (body) body.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
  frappe.call({
    method: "alpinos.outside_geo_checkins.get_outside_geo_checkins",
    args: { from_date: f, to_date: t },
    freeze: false,
    callback: function (r) {
      if (r.exc) { if (widget) widget.style.display = "none"; return; }
      var data = r.message || {};
      if (!data.allowed) { if (widget) widget.style.display = "none"; return; }
      var items = data.items || [];
      var rangeLabel = (f === t) ? f : (f + " \\u2192 " + t);
      if (!items.length) {
        if (sub) sub.textContent = rangeLabel + " \\u00b7 none";
        body.innerHTML = "<span style='color:#16a34a;'>No outside-location check-ins in this range.</span>";
        return;
      }
      if (sub) sub.textContent = rangeLabel + " \\u00b7 " + items.length + " total";
      _items = items;
      _shown = PAGE;
      draw();
    },
  });
}

if (applyBtn) applyBtn.onclick = load;
if (exportBtn) exportBtn.onclick = function () {
  var f = (fromEl && fromEl.value) || today;
  var t = (toEl && toEl.value) || today;
  window.open(
    "/api/method/alpinos.outside_geo_checkins.download_outside_geo_checkins?from_date="
      + encodeURIComponent(f) + "&to_date=" + encodeURIComponent(t),
    "_blank"
  );
};
load();
"""


def _remove_from_workspace(ws_name):
	"""Drop the Outside Geo block (layout + child row) from a workspace — used to clean up
	the earlier placement on the standalone 'Alpinos' workspace."""
	if frappe.db.exists("Workspace", ws_name):
		ws = frappe.get_doc("Workspace", ws_name)
		blocks = json.loads(ws.content or "[]")
		kept = [
			b for b in blocks
			if not (b.get("type") == "custom_block" and (b.get("data") or {}).get("custom_block_name") == LABEL)
		]
		if len(kept) != len(blocks):
			ws.content = json.dumps(kept)
			ws.save(ignore_permissions=True)
			ws.clear_cache()
	for row in frappe.get_all(
		"Workspace Custom Block", filters={"parent": ws_name, "custom_block_name": LABEL}, pluck="name"
	):
		frappe.delete_doc("Workspace Custom Block", row, ignore_permissions=True, force=True)


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

	# Clean up the earlier (wrong) placement on the standalone "Alpinos" workspace.
	_remove_from_workspace(OLD_WORKSPACE)

	if not frappe.db.exists("Workspace", WORKSPACE):
		frappe.db.commit()
		return

	# 2. Ensure the Workspace Custom Block child row exists on Home.
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

	# 3. Place it just after the "Missing Check-ins Today" block (or at the end).
	ws = frappe.get_doc("Workspace", WORKSPACE)
	blocks = json.loads(ws.content or "[]")
	blocks = [
		b for b in blocks
		if not (b.get("type") == "custom_block" and (b.get("data") or {}).get("custom_block_name") == LABEL)
	]
	insert_idx = len(blocks)
	for i, b in enumerate(blocks):
		if b.get("type") == "custom_block" and (b.get("data") or {}).get("custom_block_name") == ANCHOR_LABEL:
			insert_idx = i + 1
			break
	blocks.insert(
		insert_idx,
		{"id": frappe.generate_hash(length=10), "type": "custom_block",
		 "data": {"custom_block_name": LABEL, "col": 12}},
	)
	ws.content = json.dumps(blocks)
	ws.save(ignore_permissions=True)
	ws.clear_cache()
	frappe.db.commit()
