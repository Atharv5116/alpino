"""Accounts view of the Sales Order list (doc Section 8, W8).

The Sales Order list shows Accounts User / Accounts Manager two more columns, read live from the
order's linked Quotation (the order keeps no payment status of its own): Payment Status, and
Payment Attachments ("View Files (N)" / "No Files") which opens the proofs in a preview without
leaving the list. Proofs are the Quotation's private payment files; they are served here to
anyone who may read the Sales Order and holds an Accounts or sales manager role, so Accounts
needs no access to Quotations themselves.
"""

import mimetypes

import frappe
from frappe import _

VIEW_ROLES = {"Accounts User", "Accounts Manager", "Sales Manager", "Sales Admin", "System Manager"}


def _ready():
	return frappe.db.has_column("Quotation", "custom_payment_status") and frappe.db.table_exists("Quotation Payment Receipt")


def payment_columns(sales_orders):
	"""{sales order: {payment_status, payment_proof_count}} in two bulk queries."""
	if not sales_orders or not frappe.db.has_column("Sales Order", "custom_quotation"):
		return {}
	links = dict(
		frappe.get_all("Sales Order", filters={"name": ("in", list(sales_orders))}, fields=["name", "custom_quotation"], as_list=True)
	)
	quotations = sorted({q for q in links.values() if q})
	status, proofs = {}, {}
	if quotations and _ready():
		# company-scope: n/a (Quotations of Sales Orders the caller already listed)
		status = dict(frappe.db.sql(
			"SELECT name, custom_payment_status FROM `tabQuotation` WHERE name IN %(q)s", {"q": tuple(quotations)}
		))
		proofs = dict(frappe.db.sql(
			"""SELECT parent, COUNT(*) FROM `tabQuotation Payment Receipt`
			WHERE parent IN %(q)s AND parenttype = 'Quotation' AND IFNULL(payment_proof, '') != ''
			GROUP BY parent""",
			{"q": tuple(quotations)},
		))
	out = {}
	for so, q in links.items():
		out[so] = {
			"payment_status": status.get(q) or "" if q else "",
			"payment_proof_count": int(proofs.get(q) or 0) if q else 0,
			"has_quotation": bool(q),
		}
	return out


def _check(sales_order):
	if not (set(frappe.get_roles()) & VIEW_ROLES) and frappe.session.user != "Administrator":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	frappe.get_doc("Sales Order", sales_order).check_permission("read")
	q = frappe.db.get_value("Sales Order", sales_order, "custom_quotation")
	if not q or not _ready():
		return None, []
	rows = frappe.get_all(
		"Quotation Payment Receipt",
		filters={"parent": q, "parenttype": "Quotation", "payment_proof": ("is", "set")},
		fields=["payment_proof", "received_date", "received_amount", "idx"],
		order_by="received_date asc, idx asc",
	)
	return q, rows


@frappe.whitelist()
def so_payment_proofs(sales_order):
	"""The proof files of an order's Quotation, in received-date order, for the preview."""
	q, rows = _check(sales_order)
	out = []
	for i, r in enumerate(rows):
		url = r.payment_proof
		kind = (mimetypes.guess_type(url)[0] or "")
		out.append({
			"index": i,
			"file_name": url.rsplit("/", 1)[-1],
			"received_date": str(r.received_date or ""),
			"received_amount": r.received_amount,
			"kind": "image" if kind.startswith("image/") else ("pdf" if kind == "application/pdf" else "other"),
			"url": f"/api/method/alpinos.offline_sales.accounts_view.proof_file?sales_order={frappe.utils.quote(sales_order)}&index={i}",
		})
	return {"quotation": q, "files": out}


@frappe.whitelist()
def proof_file(sales_order, index=0):
	"""One proof file, shown inline (images, PDF) or downloaded (anything else)."""
	_q, rows = _check(sales_order)
	index = int(index)
	if index < 0 or index >= len(rows):
		raise frappe.DoesNotExistError
	url = rows[index].payment_proof
	name = frappe.db.get_value("File", {"file_url": url}, "name")
	if not name:
		raise frappe.DoesNotExistError
	f = frappe.get_doc("File", name)
	frappe.local.response.filename = f.file_name
	frappe.local.response.filecontent = f.get_content()
	frappe.local.response.type = "binary"
	frappe.local.response.display_content_as = "inline"
