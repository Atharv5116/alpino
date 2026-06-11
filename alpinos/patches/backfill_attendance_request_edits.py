"""Backfill the Edit Check-in / Edit Check-out checkboxes on existing Attendance Request rows.

The checkboxes were added later, so older requests have the punch filled but the box unticked,
and any check-out that was auto-fetched (Frappe's Time auto-now) carries microseconds. Tick the
box for a genuinely-entered punch (whole-second value) and clear an auto-now value so it neither
counts toward the monthly edit limit nor shows a stray time.
"""

import datetime

import frappe


def execute():
	meta = frappe.get_meta("Attendance Request Detail")
	if not (meta.has_field("edit_check_in") and meta.has_field("edit_check_out")):
		return

	rows = frappe.get_all(
		"Attendance Request Detail",
		filters={"parenttype": "Attendance Request"},
		fields=["name", "check_in", "check_out", "edit_check_in", "edit_check_out"],
	)
	for r in rows:
		updates = {}
		for field, box in (("check_in", "edit_check_in"), ("check_out", "edit_check_out")):
			val = r.get(field)
			if val is None:
				continue
			micros = val.microseconds if isinstance(val, datetime.timedelta) else (1 if "." in str(val) else 0)
			if micros:
				# Auto-now value — clear it and leave the box unticked.
				updates[field] = None
				if r.get(box):
					updates[box] = 0
			elif not r.get(box):
				# Genuinely entered punch — tick its Edit box so it counts.
				updates[box] = 1
		if updates:
			frappe.db.set_value("Attendance Request Detail", r.name, updates, update_modified=False)
	frappe.db.commit()
