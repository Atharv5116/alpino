"""Master Data Readiness — what will bite you at receiving, before it does.

Everything downstream assumes the masters are set up: expiry derives from the item
shelf life, the internal batch needs the item to be batch-tracked, and a GRN cannot
post without a UOM. When one of those is missing, the failure surfaces halfway
through a receipt with a message about the wrong thing.

Scope is deliberately narrow: only the items and vendors on Purchase Orders that are
still open for inward. A site-wide item audit would be thousands of rows nobody acts
on; this is the set somebody is about to receive against.
"""

import frappe
from frappe import _
from frappe.utils import cint

SEVERITY_BLOCK = "Blocks receiving"
SEVERITY_WARN = "Degrades the flow"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = _item_rows(filters) + _vendor_rows(filters)
	# Blocking problems first, then by subject, so the top of the report is the work.
	rows.sort(key=lambda r: (r["severity"] != SEVERITY_BLOCK, r["subject_type"], r["subject"]))
	return _columns(), rows


def _columns():
	return [
		{"label": _("Severity"), "fieldname": "severity", "fieldtype": "Data", "width": 140},
		{"label": _("Type"), "fieldname": "subject_type", "fieldtype": "Data", "width": 80},
		{"label": _("Subject"), "fieldname": "subject", "fieldtype": "Dynamic Link",
		 "options": "subject_doctype", "width": 220},
		{"label": _("Doctype"), "fieldname": "subject_doctype", "fieldtype": "Data", "width": 1,
		 "hidden": 1},
		{"label": _("Problem"), "fieldname": "problem", "fieldtype": "Data", "width": 330},
		{"label": _("What it breaks"), "fieldname": "consequence", "fieldtype": "Data", "width": 340},
		{"label": _("Open POs"), "fieldname": "open_pos", "fieldtype": "Int", "width": 90},
	]


def _open_po_condition():
	"""Orders that can still raise an inward: submitted, not direct-invoice, not closed."""
	return """
		po.docstatus = 1
		AND IFNULL(po.custom_direct_purchase_invoice, 0) = 0
		AND po.status NOT IN ('Closed', 'Completed')
		AND IFNULL(po.custom_pending_inward_qty, po.total_qty) > 0
	"""


def _item_rows(filters):
	items = frappe.db.sql(
		"""
		SELECT poi.item_code, COUNT(DISTINCT po.name) AS open_pos,
		       i.item_name, i.stock_uom, i.has_batch_no, i.shelf_life_in_days, i.disabled
		FROM `tabPurchase Order Item` poi
		JOIN `tabPurchase Order` po ON po.name = poi.parent
		JOIN `tabItem` i ON i.name = poi.item_code
		WHERE {cond}
		GROUP BY poi.item_code
		""".format(cond=_open_po_condition()),
		as_dict=True,
	)

	rows = []
	for it in items:
		def add(problem, consequence, severity):
			rows.append({
				"severity": severity, "subject_type": _("Item"),
				"subject": it.item_code, "subject_doctype": "Item",
				"problem": problem, "consequence": consequence,
				"open_pos": cint(it.open_pos),
			})

		if cint(it.disabled):
			add(_("Item is disabled"),
			    _("The order cannot be received at all until it is re-enabled."),
			    SEVERITY_BLOCK)
		if not it.stock_uom:
			add(_("No stock UOM"),
			    _("The receipt has no unit to post against and the GRN will not submit."),
			    SEVERITY_BLOCK)
		if not cint(it.has_batch_no):
			add(_("Not batch tracked"),
			    _("No internal batch, no QC sample batch and no expiry can be recorded "
			      "against this item."),
			    SEVERITY_WARN)
		elif not cint(it.shelf_life_in_days):
			add(_("Batch tracked but no shelf life"),
			    _("Expiry cannot derive from the manufacturing date, so every receipt "
			      "leaves the expiry blank."),
			    SEVERITY_WARN)
	return rows


def _vendor_rows(filters):
	suppliers = frappe.db.sql(
		"""
		SELECT po.supplier, po.supplier_name, COUNT(DISTINCT po.name) AS open_pos
		FROM `tabPurchase Order` po
		WHERE {cond}
		GROUP BY po.supplier
		""".format(cond=_open_po_condition()),
		as_dict=True,
	)

	rows = []
	has_gstin = frappe.get_meta("Supplier").has_field("gstin")
	for sup in suppliers:
		def add(problem, consequence, severity):
			rows.append({
				"severity": severity, "subject_type": _("Vendor"),
				"subject": sup.supplier, "subject_doctype": "Supplier",
				"problem": problem, "consequence": consequence,
				"open_pos": cint(sup.open_pos),
			})

		address = frappe.db.get_value("Supplier", sup.supplier, "supplier_primary_address")
		if not address:
			add(_("No primary address"),
			    _("The inward and the GRN print without a vendor address."),
			    SEVERITY_WARN)
		if has_gstin and not frappe.db.get_value("Supplier", sup.supplier, "gstin"):
			add(_("No GSTIN"),
			    _("Tax cannot be resolved for the order, and the debit note for any "
			      "rejected quantity will be raised without one."),
			    SEVERITY_WARN)
	return rows
