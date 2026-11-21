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

Nothing writes the table yet: the Invoice Mapping upload stamps part 1's invoice on the order
(and its Pick List) and a later part's, SOR-.../2, /3, on that part's Pick List (Changes(HP)
#125). So the popup also lists the invoices on the order's Pick Lists, each number once.

Part numbers follow the Accounts Format Report: a Partial PO order's SOR-.../2, /3
references, else the submitted Pick Lists oldest dispatch first (#63), so Part 2 means the
same thing in both places.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

INVOICE_TABLE = "custom_invoices"


def _parts_for(sales_order):
	"""{pick list: part number}.

	A Partial PO order is numbered as the Accounts Format Report references it (SOR-.../2, /3,
	Changes(HP) #125: the order the Pick Lists were made), so Part 2 here is the part the
	accounts team uploaded SOR-.../2 for. Any other order, oldest dispatch first as #63.
	"""
	from alpinos.partial_po_ref import part_numbers

	numbers = part_numbers(sales_order)
	if numbers:
		return numbers
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabPick List`
		WHERE custom_sales_order_id = %(so)s AND docstatus = 1
		ORDER BY IFNULL(custom_dispatch_date, '9999-12-31') ASC, creation ASC
		""",
		{"so": sales_order},
	)
	return {r[0]: i for i, r in enumerate(rows, start=1)}


def _part_invoices(sales_orders):
	"""{sales order: {pick list: invoice no}} for the invoices recorded on the orders' parts.

	The Invoice Mapping upload puts a later part's invoice (SOR-.../2, /3) on that part's Pick
	List, and part 1's on both the order and its Pick List (Changes(HP) #125). A part whose
	Pick List has none may carry it on the Delivery Note raised from it: the same rule as the
	Accounts Format Report's Invoice No per part (#63).
	"""
	if not sales_orders:
		return {}
	pls = frappe.db.sql(
		"""
		SELECT name, custom_sales_order_id AS so, custom_invoice_no AS inv
		FROM `tabPick List`
		WHERE custom_sales_order_id IN %(names)s AND docstatus = 1
		""",
		{"names": tuple(sales_orders)}, as_dict=True,
	)
	blank = [p.name for p in pls if not (p.inv or "").strip()]
	from_dn = {}
	if blank:
		for r in frappe.db.sql(
			"""
			SELECT dni.against_pick_list AS pl, dn.custom_invoice_no AS inv
			FROM `tabDelivery Note` dn
			INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
			WHERE dni.against_pick_list IN %(pls)s AND dn.docstatus < 2
				AND IFNULL(dn.custom_invoice_no, '') <> ''
			ORDER BY dn.modified DESC
			""",
			{"pls": tuple(blank)}, as_dict=True,
		):
			from_dn.setdefault(r.pl, r.inv.strip())
	out = {}
	for p in pls:
		inv = (p.inv or "").strip() or from_dn.get(p.name, "")
		if inv:
			out.setdefault(p.so, {})[p.name] = inv
	return out


def attached_invoice_pdf(sales_order, invoice_no):
	"""The PDF the invoice sync attached to the order for this invoice, or "".

	The sync saves it as <invoice no>.pdf; Frappe adds the last 6 characters of the content
	hash when that name is already taken (live: 1230756169c.pdf for invoice 12307).
	"""
	ext = frappe.db.get_single_value("Invoice Sync Settings", "pdf_extension") or ".pdf"
	row = frappe.db.sql(
		"""
		SELECT file_url FROM `tabFile`
		WHERE attached_to_doctype = 'Sales Order' AND attached_to_name = %(so)s
			AND (file_name = %(plain)s OR file_name = CONCAT(%(inv)s, RIGHT(content_hash, 6), %(ext)s))
		ORDER BY creation DESC LIMIT 1
		""",
		{"so": sales_order, "plain": f"{invoice_no}{ext}", "inv": invoice_no, "ext": ext},
	)
	return (row[0][0] or "") if row else ""


@frappe.whitelist()
def get_sales_order_invoices(sales_order):
	"""Every invoice linked to this Sales Order, with its part number and download link.

	Reads the table rows, then the invoices recorded on the order's Pick Lists (where the
	Invoice Mapping upload puts SOR-.../2, /3), then the single invoice the order has always
	carried, each number once -- so this reads correctly for the whole history without a
	migration.
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

	seen = {i["invoice_no"] for i in invoices}
	own = (so.custom_invoice_no or "").strip()
	on_parts = _part_invoices([sales_order]).get(sales_order, {})
	for pl, inv in sorted(on_parts.items(), key=lambda kv: parts.get(kv[0], 0)):
		if inv in seen:
			continue
		seen.add(inv)
		part = parts.get(pl, 0) if len(parts) > 1 else 0
		invoices.append({
			"invoice_no": inv,
			"part_no": part,
			"part_label": _("Part {0}").format(part) if part else "",
			"invoice_date": "",
			"invoice_amount": 0,
			"pick_list": pl,
			"invoice_pdf": (so.custom_invoice_pdf if inv == own else attached_invoice_pdf(sales_order, inv)) or "",
		})

	if own and own not in seen:
		# The order's own invoice, shown the same way so one popup serves both shapes.
		first = len(parts) > 1 and all(i["part_no"] != 1 for i in invoices)
		invoices.append({
			"invoice_no": own,
			"part_no": 1 if first else 0,
			"part_label": _("Part 1") if first else "",
			"invoice_date": "",
			"invoice_amount": 0,
			"pick_list": "",
			"invoice_pdf": so.custom_invoice_pdf or "",
		})

	if len(invoices) == 1 and not invoices[0]["invoice_amount"] and invoices[0]["invoice_no"] == own:
		# The order's Total Invoice Value is the whole order's; it is that invoice's amount only
		# when the order has one invoice. Against one of several it would read as that part's.
		invoices[0]["invoice_amount"] = flt(so.custom_total_invoice_value)
	invoices.sort(key=lambda i: i["part_no"])

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

	# The same numbers the popup lists, each once: the table rows, the invoices on the orders'
	# Pick Lists (SOR-.../2, /3 from the Invoice Mapping upload) and each order's own invoice.
	numbers = {}
	for r in frappe.db.sql(
		"""
		SELECT parent, invoice_no FROM `tabSales Order Invoice`
		WHERE parenttype = 'Sales Order' AND parent IN %(names)s
		""",
		{"names": tuple(names)}, as_dict=True,
	):
		numbers.setdefault(r.parent, set()).add((r.invoice_no or "").strip())
	for so, by_part in _part_invoices(names).items():
		numbers.setdefault(so, set()).update(by_part.values())
	for r in frappe.db.sql(
		"""
		SELECT name, custom_invoice_no FROM `tabSales Order`
		WHERE name IN %(names)s AND IFNULL(custom_invoice_no, '') <> ''
		""",
		{"names": tuple(names)}, as_dict=True,
	):
		numbers.setdefault(r.name, set()).add(r.custom_invoice_no.strip())
	return {so: len(nos - {""}) for so, nos in numbers.items() if nos - {""}}
