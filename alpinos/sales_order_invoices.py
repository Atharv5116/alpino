"""Changes(HP) #51: several invoices against one partially dispatched Sales Order.

    "If Partial Order Allowed is ticked in the Sales Order, allow creation and linking of
     multiple Sales Invoices against that Sales Order... On clicking the Sales Invoice
     field/link, first open a pop-up listing all invoices linked to that Sales Order...
     Show the invoice number, invoice date, invoice amount, and the respective part number."

An invoice here is a Tally number brought in by the invoice sync, not an ERPNext Sales
Invoice document, so "linking" means recording it against the order and the dispatch it
belongs to. The Sales Order Invoice child table holds them; the Sales Order's own
custom_invoice_no stays exactly as it is, and an order with one invoice and no table rows
still reads correctly through the fallback below. Nothing has to be migrated for the list
to keep working.

Part numbers follow the same ordering #63 uses for the Accounts Format Report -- the
submitted Pick Lists oldest dispatch first -- so Part 1 means the same thing in both places.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

INVOICE_TABLE = "custom_invoices"


def _parts_for(sales_order):
	"""{pick list: part number}, oldest dispatch first. Matches #63's ordering."""
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabPick List`
		WHERE custom_sales_order_id = %(so)s AND docstatus = 1
		ORDER BY IFNULL(custom_dispatch_date, '9999-12-31') ASC, creation ASC
		""",
		{"so": sales_order},
	)
	return {r[0]: i for i, r in enumerate(rows, start=1)}


@frappe.whitelist()
def get_sales_order_invoices(sales_order):
	"""Every invoice linked to this Sales Order, with its part number and download link.

	Returns the table rows when there are any, and otherwise falls back to the single
	invoice the order has always carried -- so this reads correctly for the whole history
	without a migration.
	"""
	so = frappe.db.get_value(
		"Sales Order", sales_order,
		["name", "custom_invoice_no", "custom_invoice_pdf", "custom_total_invoice_value",
		 "custom_partial_order_allowed"],
		as_dict=True,
	)
	if not so:
		return {"sales_order": sales_order, "invoices": [], "count": 0, "multiple": 0}

	parts = _parts_for(sales_order)
	rows = frappe.get_all(
		"Sales Order Invoice",
		filters={"parent": sales_order, "parenttype": "Sales Order"},
		fields=["name", "invoice_no", "part_no", "invoice_date", "invoice_amount",
		        "pick_list", "invoice_pdf", "idx"],
		order_by="part_no asc, idx asc",
	)

	invoices = []
	for r in rows:
		part = cint(r.part_no) or parts.get(r.pick_list) or 0
		invoices.append({
			"invoice_no": r.invoice_no,
			"part_no": part,
			"part_label": _("Part {0}").format(part) if part else "",
			"invoice_date": str(r.invoice_date) if r.invoice_date else "",
			"invoice_amount": flt(r.invoice_amount),
			"pick_list": r.pick_list or "",
			"invoice_pdf": r.invoice_pdf or "",
		})

	if not invoices and (so.custom_invoice_no or "").strip():
		# The order's single invoice, shown the same way so one popup serves both shapes.
		invoices.append({
			"invoice_no": so.custom_invoice_no.strip(),
			"part_no": 1 if len(parts) > 1 else 0,
			"part_label": _("Part 1") if len(parts) > 1 else "",
			"invoice_date": "",
			"invoice_amount": flt(so.custom_total_invoice_value),
			"pick_list": "",
			"invoice_pdf": so.custom_invoice_pdf or "",
		})

	return {
		"sales_order": sales_order,
		"invoices": invoices,
		"count": len(invoices),
		"multiple": 1 if len(invoices) > 1 else 0,
		"partial_order_allowed": cint(so.custom_partial_order_allowed),
		"parts": len(parts),
	}


@frappe.whitelist()
def set_part_invoice(sales_order, invoice_no, pick_list=None, invoice_date=None,
                     invoice_amount=None, invoice_pdf=None):
	"""Record one invoice against an order, optionally against a specific dispatch part.

	Re-recording the same invoice number updates that row instead of adding another, so a
	correction does not leave two rows claiming the same number.
	"""
	invoice_no = (invoice_no or "").strip()
	if not invoice_no:
		frappe.throw(_("Invoice No is required."))
	if not frappe.db.exists("Sales Order", sales_order):
		frappe.throw(_("No such Sales Order."))
	if pick_list:
		owner_so = frappe.db.get_value("Pick List", pick_list, "custom_sales_order_id")
		if owner_so != sales_order:
			frappe.throw(
				_("Pick List {0} does not belong to {1}.").format(pick_list, sales_order)
			)

	parts = _parts_for(sales_order)
	part_no = parts.get(pick_list) or 0 if pick_list else 0

	# Written straight to the child table rather than through a save of the parent. Saving a
	# submitted Sales Order would re-run every validation on it and fire the Activity Trail
	# hook, so recording an invoice number would look like somebody had edited the order.
	existing = frappe.db.get_value(
		"Sales Order Invoice",
		{"parent": sales_order, "parenttype": "Sales Order", "invoice_no": invoice_no},
		"name",
	)
	values = {"invoice_no": invoice_no}
	if pick_list:
		values["pick_list"] = pick_list
		values["part_no"] = part_no
	if invoice_date:
		values["invoice_date"] = invoice_date
	if invoice_amount is not None:
		values["invoice_amount"] = flt(invoice_amount)
	if invoice_pdf:
		values["invoice_pdf"] = invoice_pdf

	if existing:
		frappe.db.set_value("Sales Order Invoice", existing, values, update_modified=False)
	else:
		last_idx = frappe.db.sql(
			"""SELECT IFNULL(MAX(idx), 0) FROM `tabSales Order Invoice`
			   WHERE parent = %(so)s AND parenttype = 'Sales Order'""",
			{"so": sales_order},
		)[0][0]
		child = frappe.get_doc(dict(
			doctype="Sales Order Invoice",
			parent=sales_order,
			parenttype="Sales Order",
			parentfield=INVOICE_TABLE,
			idx=int(last_idx) + 1,
			**values,
		))
		child.db_insert()
	frappe.db.commit()
	return get_sales_order_invoices(sales_order)


@frappe.whitelist()
def invoice_counts(sales_orders):
	"""{sales order: invoice count} for a page that wants to flag the multi-invoice rows."""
	import json

	if isinstance(sales_orders, str):
		sales_orders = json.loads(sales_orders) if sales_orders.startswith("[") else [sales_orders]
	names = [str(s).strip() for s in (sales_orders or []) if str(s).strip()]
	if not names:
		return {}

	counts = {}
	for r in frappe.db.sql(
		"""
		SELECT parent, COUNT(*) AS n FROM `tabSales Order Invoice`
		WHERE parenttype = 'Sales Order' AND parent IN %(names)s
		GROUP BY parent
		""",
		{"names": tuple(names)}, as_dict=True,
	):
		counts[r.parent] = cint(r.n)
	# An order with no table rows still has its single invoice, if it carries one.
	for r in frappe.db.sql(
		"""
		SELECT name FROM `tabSales Order`
		WHERE name IN %(names)s AND IFNULL(custom_invoice_no, '') <> ''
		""",
		{"names": tuple(names)}, as_dict=True,
	):
		counts.setdefault(r.name, 1)
	return counts
