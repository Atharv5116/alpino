"""Add an HR-Manager-only "Upcoming HR Activities" block to the Home workspace.

Shows, for the next 30 days (dates as DD/MM/YYYY):
  - Probation completions (Employee.probation_end_date)
  - Internship completions (date_of_joining + custom_internship_duration months)
  - Salary increments (next date_of_joining anniversary, yearly)

Data + the HR Manager gate live in alpinos.people_events.get_upcoming_employee_lifecycle.
The block is added to the workspace for everyone, but the script hides it for any user
who is not an HR Manager (backend returns allowed:false).
"""

import json

import frappe

LABEL = "Upcoming HR Activities"
PEOPLE_LABEL = "Upcoming Birthdays & Anniversaries"
WORKSPACE = "Home"

HTML = """
<div id="alp-hr-life-widget" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;padding:20px;border:1px solid #e5e7eb;border-radius:16px;background:#ffffff;width:100%;max-width:100%;box-sizing:border-box;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
  <div style="border-radius:14px;border:1px solid #e5e7eb;background:#f9fafb;padding:16px;min-height:140px;box-sizing:border-box;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
      <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;flex-shrink:0;"></span>Probation Completion</span>
      <span style="font-size:10px;color:#9ca3af;">Next 30 days</span>
    </div>
    <div id="alp-probation-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
  </div>
  <div style="border-radius:14px;border:1px solid #e5e7eb;background:#f9fafb;padding:16px;min-height:140px;box-sizing:border-box;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
      <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#10b981;flex-shrink:0;"></span>Internship Completion</span>
      <span style="font-size:10px;color:#9ca3af;">Next 30 days</span>
    </div>
    <div id="alp-internship-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
  </div>
  <div style="border-radius:14px;border:1px solid #e5e7eb;background:#f9fafb;padding:16px;min-height:140px;box-sizing:border-box;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;">
      <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:#111827;"><span style="width:8px;height:8px;border-radius:50%;background:#6366f1;flex-shrink:0;"></span>Salary Increment</span>
      <span style="font-size:10px;color:#9ca3af;">Next 30 days</span>
    </div>
    <div id="alp-increment-list" style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#4b5563;"></div>
  </div>
</div>
"""

SCRIPT = """
var root = root_element;
var widget = root.querySelector("#alp-hr-life-widget");
var probList = root.querySelector("#alp-probation-list");
var internList = root.querySelector("#alp-internship-list");
var incList = root.querySelector("#alp-increment-list");
[probList, internList, incList].forEach(function (el) {
  if (el) el.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
});

frappe.call({
  method: "alpinos.people_events.get_upcoming_employee_lifecycle",
  args: { days: 30 },
  freeze: false,
  callback: function (r) {
    if (r.exc) {
      if (widget) widget.style.display = "none";
      return;
    }
    var data = r.message || {};
    // Hide the whole section for anyone who is not an HR Manager.
    if (!data.allowed) {
      if (widget) widget.style.display = "none";
      return;
    }
    function renderList(container, items, emptyText, showYears) {
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
        var date = document.createElement("div");
        date.style.cssText = "font-size:11px;color:#111827;font-weight:600;";
        date.textContent = item.date || "";
        right.appendChild(date);
        if (showYears && item.years) {
          var yr = document.createElement("div");
          yr.style.cssText = "font-size:10px;color:#2563eb;font-weight:500;";
          yr.textContent = item.years + " yr";
          right.appendChild(yr);
        }
        row.appendChild(left);
        row.appendChild(right);
        container.appendChild(row);
      });
    }
    renderList(probList, data.probation || [], "No upcoming probation completions", false);
    renderList(internList, data.internship || [], "No upcoming internship completions", false);
    renderList(incList, data.increment || [], "No upcoming increments", true);
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
			{
				"doctype": "Custom HTML Block",
				"name": LABEL,
				"html": HTML,
				"script": SCRIPT,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Workspace", WORKSPACE):
		frappe.db.commit()
		return

	# 2. Ensure the Workspace Custom Block child row exists.
	if not frappe.db.exists(
		"Workspace Custom Block",
		{"parent": WORKSPACE, "custom_block_name": LABEL},
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

	# 3. Place the block in the workspace layout, just after the
	#    Birthdays/Anniversaries block (or at the end if it isn't present).
	workspace_doc = frappe.get_doc("Workspace", WORKSPACE)
	blocks = json.loads(workspace_doc.content or "[]")

	# Drop any existing instance so this patch stays idempotent.
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
			and (b.get("data") or {}).get("custom_block_name") == PEOPLE_LABEL
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
