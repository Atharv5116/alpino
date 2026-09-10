"""QC Pending — inspections not yet completed, with the BR-QC-03 SLA against them.

An SLA that has run out is what this report exists to surface, so the breach column
is computed from sla_due against now rather than trusting a flag that only a
scheduled job refreshes.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_hours

from alpinos.purchase import constants as C


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _rows(filters)


def _columns():
	return [
		{"label": _("Purchase QC"), "fieldname": "name", "fieldtype": "Link",
		 "options": "Purchase QC", "width": 150},
		{"label": _("Purchase Inward"), "fieldname": "purchase_inward", "fieldtype": "Link",
		 "options": "Purchase Inward", "width": 150},
		{"label": _("Vendor"), "fieldname": "supplier", "fieldtype": "Link",
		 "options": "Supplier", "width": 180},
		{"label": _("QC Status"), "fieldname": "qc_status", "fieldtype": "Data", "width": 140},
		{"label": _("Inspector"), "fieldname": "inspector", "fieldtype": "Link",
		 "options": "User", "width": 160},
		{"label": _("SLA Due"), "fieldname": "sla_due", "fieldtype": "Datetime", "width": 160},
		{"label": _("Hours Overdue"), "fieldname": "hours_overdue", "fieldtype": "Float",
		 "precision": 1, "width": 115},
		{"label": _("SLA"), "fieldname": "sla_state", "fieldtype": "Data", "width": 110},
		{"label": _("Received Qty"), "fieldname": "received_qty", "fieldtype": "Float", "width": 105},
	]


def _rows(filters):
	conditions = ["qc.docstatus < 2", "qc.qc_status != %(completed)s"]
	values = {"completed": C.QC_COMPLETED}
	if filters.get("supplier"):
		conditions.append("qc.supplier = %(supplier)s")
		values["supplier"] = filters.supplier
	if filters.get("only_breached"):
		conditions.append("qc.sla_due IS NOT NULL AND qc.sla_due < NOW()")

	rows = frappe.db.sql(
		"""
		SELECT qc.name, qc.purchase_inward, qc.supplier, qc.qc_status, qc.inspector,
		       qc.sla_due, qc.received_qty
		FROM `tabPurchase QC` qc
		WHERE {conditions}
		ORDER BY qc.sla_due IS NULL, qc.sla_due ASC, qc.name ASC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)

	now = now_datetime()
	for row in rows:
		if row.sla_due and row.sla_due < now:
			row.hours_overdue = round(time_diff_in_hours(now, row.sla_due), 1)
			row.sla_state = _("Breached")
		else:
			row.hours_overdue = 0
			row.sla_state = _("Within SLA") if row.sla_due else _("No SLA")
	return rows
