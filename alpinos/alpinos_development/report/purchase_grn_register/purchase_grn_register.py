"""GRN Register — every goods receipt this module raised, with the QC split.

One row per receipt: what was accepted, what QC rejected, whether a debit note came
out of it, and who finally submitted it (BR-GRN-07).
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _rows(filters)


def _columns():
	return [
		{"label": _("GRN"), "fieldname": "name", "fieldtype": "Link",
		 "options": "Purchase Receipt", "width": 150},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Vendor"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 180},
		{"label": _("Purchase Inward"), "fieldname": "custom_purchase_inward", "fieldtype": "Link",
		 "options": "Purchase Inward", "width": 145},
		{"label": _("Purchase QC"), "fieldname": "custom_purchase_qc", "fieldtype": "Link",
		 "options": "Purchase QC", "width": 145},
		{"label": _("GRN Status"), "fieldname": "custom_grn_status", "fieldtype": "Data", "width": 120},
		{"label": _("Accepted"), "fieldname": "accepted_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Rejected"), "fieldname": "rejected_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Debit Note"), "fieldname": "custom_debit_note", "fieldtype": "Link",
		 "options": "Purchase Invoice", "width": 145},
		{"label": _("Submitted By"), "fieldname": "custom_final_submitted_by", "fieldtype": "Link",
		 "options": "User", "width": 160},
	]


def _rows(filters):
	# Only this module's receipts. A Purchase Return copies the inward link, so it is
	# excluded explicitly rather than by hoping no return exists.
	conditions = ["pr.docstatus < 2", "IFNULL(pr.is_return, 0) = 0",
	              "IFNULL(pr.custom_purchase_inward, '') != ''"]
	values = {}
	if filters.get("from_date"):
		conditions.append("pr.posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("pr.posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.get("supplier"):
		conditions.append("pr.supplier = %(supplier)s")
		values["supplier"] = filters.supplier
	if filters.get("grn_status"):
		conditions.append("pr.custom_grn_status = %(grn_status)s")
		values["grn_status"] = filters.grn_status

	return frappe.db.sql(
		"""
		SELECT pr.name, pr.posting_date, pr.supplier_name, pr.custom_purchase_inward,
		       pr.custom_purchase_qc, pr.custom_grn_status, pr.custom_debit_note,
		       pr.custom_final_submitted_by,
		       IFNULL(SUM(pri.qty), 0)          AS accepted_qty,
		       IFNULL(SUM(pri.rejected_qty), 0) AS rejected_qty
		FROM `tabPurchase Receipt` pr
		LEFT JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
		WHERE {conditions}
		GROUP BY pr.name
		ORDER BY pr.posting_date DESC, pr.name DESC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)
