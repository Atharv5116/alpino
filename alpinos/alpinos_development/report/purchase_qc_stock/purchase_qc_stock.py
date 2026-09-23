"""QC Stock — the items physically with QC right now.

"Right now" means the inspection has been handed over and not yet finished: the goods
are in the building, counted on the Purchase Inward, and not yet posted to a warehouse
by the GRN. Nothing here reads the stock ledger, because the module never posts inward
stock into QC Hold — this report IS the answer to "what is in QC at the moment".

Rows are per item per inspection, so the same item on two inspections stays two lines;
the total row adds the quantities up.
"""

import frappe
from frappe import _

from alpinos.purchase import constants as C


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _rows(filters)


def _columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link",
		 "options": "Item", "width": 180},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Qty in QC"), "fieldname": "received_qty", "fieldtype": "Float",
		 "width": 100},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM",
		 "width": 80},
		{"label": _("QC Status"), "fieldname": "qc_status", "fieldtype": "Data", "width": 130},
		{"label": _("Purchase QC"), "fieldname": "purchase_qc", "fieldtype": "Link",
		 "options": "Purchase QC", "width": 140},
		{"label": _("Purchase Inward"), "fieldname": "purchase_inward", "fieldtype": "Link",
		 "options": "Purchase Inward", "width": 140},
		{"label": _("Vendor"), "fieldname": "supplier", "fieldtype": "Link",
		 "options": "Supplier", "width": 180},
		{"label": _("Inspector"), "fieldname": "inspector", "fieldtype": "Link",
		 "options": "User", "width": 150},
		{"label": _("With QC Since"), "fieldname": "since", "fieldtype": "Datetime",
		 "width": 160},
	]


def _rows(filters):
	conditions = [
		"qc.docstatus < 2",
		"qc.qc_status != %(completed)s",
	]
	values = {"completed": C.QC_COMPLETED}

	if filters.get("supplier"):
		conditions.append("qc.supplier = %(supplier)s")
		values["supplier"] = filters.supplier
	if filters.get("item_code"):
		conditions.append("item.item_code = %(item_code)s")
		values["item_code"] = filters.item_code
	if filters.get("qc_status"):
		conditions.append("qc.qc_status = %(qc_status)s")
		values["qc_status"] = filters.qc_status

	return frappe.db.sql(
		"""
		SELECT item.item_code, item.item_name, item.received_qty, item.uom,
		       qc.qc_status, qc.name AS purchase_qc, qc.purchase_inward, qc.supplier,
		       qc.inspector, qc.creation AS since
		FROM `tabPurchase QC Item` item
		INNER JOIN `tabPurchase QC` qc ON qc.name = item.parent
		WHERE {conditions}
		ORDER BY qc.creation ASC, item.idx ASC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)
