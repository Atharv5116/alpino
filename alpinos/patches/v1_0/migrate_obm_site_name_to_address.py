"""Move the Offline Buyer Master parent `site_name` onto its primary address row.

`site_name` was removed from Offline Buyer Master (sites now live per address row on
the Offline Buyer Address child table). Frappe leaves the now-orphaned column in the
DB, so this post-model-sync patch reads it directly and copies the value onto the
primary (or first) address row, without clobbering a row that already has a site.
"""

import frappe


def execute():
	# The OBM field is gone from meta but the column may still hold legacy data.
	obm_cols = [c.get("Field") for c in frappe.db.sql("SHOW COLUMNS FROM `tabOffline Buyer Master`", as_dict=True)]
	if "site_name" not in obm_cols:
		return

	rows = frappe.db.sql(
		"SELECT name, site_name FROM `tabOffline Buyer Master` WHERE IFNULL(site_name, '') != ''",
		as_dict=True,
	)

	moved = 0
	for r in rows:
		site = (r.get("site_name") or "").strip()
		if not site:
			continue

		# Primary address row wins; otherwise the first row by idx.
		addr = frappe.db.sql(
			"""
			SELECT name FROM `tabOffline Buyer Address`
			WHERE parent = %s AND parenttype = 'Offline Buyer Master'
			ORDER BY is_primary DESC, idx ASC
			LIMIT 1
			""",
			(r["name"],),
		)
		if not addr:
			continue

		addr_name = addr[0][0]
		current = (frappe.db.get_value("Offline Buyer Address", addr_name, "site_name") or "").strip()
		if current:
			continue

		frappe.db.set_value("Offline Buyer Address", addr_name, "site_name", site, update_modified=False)
		moved += 1

	frappe.db.commit()
	print(f"✅ Migrated site_name onto primary address for {moved} Offline Buyer Master record(s)")
