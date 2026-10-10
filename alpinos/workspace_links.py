"""Remove workspace links and shortcuts that point at something which no longer exists.

A Workspace validates every link on save, so one dead shortcut makes the whole workspace
unsavable -- and the Home widgets re-save Home on every migrate. On this site that has
happened twice: a "Bad POS" shortcut to another app's page, and on Frappe v16 the
Leaderboard page, which v16 removed. Either one stopped every after_migrate step after it.

Runs as the FIRST alpinos after_migrate step. By then Frappe has synced every standard
DocType, Report and Page, so a target that is missing really is gone. (It is not a
Workspace doc_event: during the standard sync a workspace is imported before the charts
and cards it shows exist, and v16 validates links before any before_validate hook.)
Rows are deleted directly rather than through a save, which is the very thing they break.
"""

import json

import frappe

_LINKABLE = {"DocType", "Report", "Page", "Dashboard"}


def prune_dead_links():
	for row in frappe.db.sql(
		"""select name, parent, parentfield, type as target_type, link_to, label
		from `tabWorkspace Shortcut` where ifnull(link_to, '') != ''
		union all
		select name, parent, parentfield, link_type, link_to, label
		from `tabWorkspace Link` where type = 'Link' and ifnull(link_to, '') != ''""",
		as_dict=True,
	):
		if row.target_type not in _LINKABLE or frappe.db.exists(row.target_type, row.link_to):
			continue
		child = "Workspace Shortcut" if row.parentfield == "shortcuts" else "Workspace Link"
		frappe.db.delete(child, {"name": row.name})
		if child == "Workspace Shortcut":
			_drop_shortcut_block(row.parent, row.label)
		frappe.log_error(
			title=f"Workspace {row.parent}: removed a dead {child.split()[-1].lower()}",
			message=f"{row.target_type} {row.link_to!r} no longer exists (label {row.label!r}).",
		)
		print(f"Workspace {row.parent}: removed dead {row.target_type} link {row.link_to!r}")


def _drop_shortcut_block(workspace, label):
	content = frappe.db.get_value("Workspace", workspace, "content")
	try:
		blocks = json.loads(content or "[]")
	except ValueError:
		return
	kept = [
		b for b in blocks
		if not (b.get("type") == "shortcut" and (b.get("data") or {}).get("shortcut_name") == label)
	]
	if len(kept) != len(blocks):
		frappe.db.set_value("Workspace", workspace, "content", json.dumps(kept), update_modified=False)
