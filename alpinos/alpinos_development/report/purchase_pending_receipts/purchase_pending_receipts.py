"""Pending Receipts — approved Purchase Orders with quantity still to come in.

Reads the rollup columns the module already maintains on the order
(purchase_order_fields.refresh_inward_progress) rather than re-deriving them from
the inward tables, so the report and the Purchase Order list can never disagree.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _rows(filters)


def _columns():
	return [
		{"label": _("Purchase Order"), "fieldname": "name", "fieldtype": "Link",
		 "options": "Purchase Order", "width": 150},
		{"label": _("PO Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 95},
		{"label": _("Vendor"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 190},
		{"label": _("PO Type"), "fieldname": "custom_inward_type", "fieldtype": "Data", "width": 80},
		{"label": _("Required By"), "fieldname": "schedule_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 105},
		{"label": _("Inward Status"), "fieldname": "custom_inward_status", "fieldtype": "Data", "width": 140},
		{"label": _("Ordered"), "fieldname": "total_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Received"), "fieldname": "custom_total_inward_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Pending"), "fieldname": "custom_pending_inward_qty", "fieldtype": "Float", "width": 95},
	]


def _rows(filters):
	conditions = ["po.docstatus = 1", "IFNULL(po.custom_direct_purchase_invoice, 0) = 0",
	              "po.status NOT IN ('Closed', 'Completed')",
	              "IFNULL(po.custom_pending_inward_qty, po.total_qty) > 0"]
	values = {}
	if filters.get("company"):
		conditions.append("po.company = %(company)s")
		values["company"] = filters.company
	if filters.get("supplier"):
		conditions.append("po.supplier = %(supplier)s")
		values["supplier"] = filters.supplier
	if filters.get("inward_type"):
		conditions.append("po.custom_inward_type = %(inward_type)s")
		values["inward_type"] = filters.inward_type

	rows = frappe.db.sql(
		"""
		SELECT po.name, po.transaction_date, po.supplier_name, po.custom_inward_type,
		       po.schedule_date, po.custom_inward_status, po.total_qty,
		       IFNULL(po.custom_total_inward_qty, 0) AS custom_total_inward_qty,
		       IFNULL(po.custom_pending_inward_qty, po.total_qty) AS custom_pending_inward_qty,
		       GREATEST(DATEDIFF(CURDATE(), po.schedule_date), 0) AS days_overdue
		FROM `tabPurchase Order` po
		WHERE {conditions}
		ORDER BY po.schedule_date ASC, po.name ASC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)
	return rows
