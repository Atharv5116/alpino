"""Re-apply the "Upcoming HR Activities" workspace block (v2)."""

from alpinos.patches.create_hr_lifecycle_widget import HTML, SCRIPT, LABEL, PEOPLE_LABEL, WORKSPACE
import json
import frappe


def execute():
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

	# Place it just after the Birthdays/Anniversaries block, or at the end
	workspace_doc = frappe.get_doc("Workspace", WORKSPACE)
	blocks = json.loads(workspace_doc.content or "[]")

	# Drop any existing instance to stay idempotent
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
