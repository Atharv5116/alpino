"""Track the date an employee was suspended, so reports can drop them the following month."""

import frappe
from frappe.utils import getdate, nowdate


def setup_suspension_date_field():
	"""after_migrate: add the `Suspension Date` field to Employee."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Employee": [
				dict(
					fieldname="custom_suspension_date",
					label="Suspension Date",
					fieldtype="Date",
					insert_after="status",
					depends_on="eval:doc.status=='Suspended'",
					description=(
						"Stamped automatically when the status is set to Suspended. Attendance "
						"reports show the employee up to this month and drop them afterwards."
					),
				)
			]
		},
		ignore_validate=True,
	)


def stamp_suspension_date(doc, method=None):
	"""Set the suspension date when status turns Suspended; clear it when the employee returns."""
	if doc.doctype != "Employee":
		return

	if doc.status == "Suspended":
		if not doc.get("custom_suspension_date"):
			doc.custom_suspension_date = getdate(nowdate())
	elif doc.get("custom_suspension_date"):
		doc.custom_suspension_date = None


@frappe.whitelist()
def backfill(apply=0):
	"""Stamp a suspension date on already-Suspended employees that have none.

	Uses the last status change recorded in Version, falling back to the Employee's own
	modified timestamp. Dry-run by default; apply=1 writes.

	  bench --site SITE execute alpinos.employee_suspension.backfill --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	names = frappe.get_all(
		"Employee",
		filters={"status": "Suspended", "custom_suspension_date": ["is", "not set"]},
		fields=["name", "modified"],
	)

	changes = []
	for emp in names:
		suspended_on = _last_status_change(emp.name, "Suspended") or getdate(emp.modified)
		changes.append({"employee": emp.name, "suspension_date": str(suspended_on)})
		if apply:
			frappe.db.set_value(
				"Employee", emp.name, "custom_suspension_date", suspended_on, update_modified=False
			)
	if apply:
		frappe.db.commit()

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"employees": len(names),
		"sample": changes[:25],
	}


def _last_status_change(employee, status):
	"""Date the Employee's status was last changed to `status`, from the Version log."""
	rows = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Employee", "docname": employee},
		fields=["data", "creation"],
		order_by="creation desc",
		limit=50,
	)
	for row in rows:
		try:
			changed = frappe.parse_json(row.data).get("changed") or []
		except Exception:
			continue
		for field, _old, new in (c for c in changed if len(c) == 3):
			if field == "status" and new == status:
				return getdate(row.creation)
	return None
