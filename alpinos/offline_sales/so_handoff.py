"""Sales Order creation from a Quotation and hand-off (doc Section 6, W7), for Offline orders.

- Offline Sales Settings "Offline Sales Orders must come from a Finalized Quotation" (OFF at
  deploy, client decision 13 Nov 2026): when ON, an Offline Sales Order without a Linked
  Quotation is refused. When OFF, direct orders work as before (the 3 Oct amendment lets a
  Sales Officer draft one).
- From a Quotation: only Sales Manager / Sales Admin (System Manager by app convention); the
  Quotation must be Finalized with SO Eligibility = Allowed and no other active Sales Order
  (Draft or submitted, not Cancelled / Rejected); a row lock stops two simultaneous creates.
- The order keeps its Customer and links; a Registered Business buyer needs its Billing GSTIN
  on creation and on submission; a Sales Officer can view such an order but not change it.
- Every commercial change on a Quotation-sourced Draft (also a difference from the Quotation
  made before the first save) needs a Reason for Change, recorded per field. The Quotation is
  never changed by the order.
- The Quotation moves to "Sales Order Created" (with its Sales Order ID) when the order is
  created, and back to "Finalized" when that order is cancelled, deleted as a Draft or rejected,
  so a replacement can be created (doc 3).
- Buyer Catalog sync stays on submission only (sales_mrp.update_buyer_catalog_on_submit); each
  synced row also records the Last Order Date and the Linked Sales Order (doc 8.3).
"""

import frappe
from frappe import _
from frappe.utils import flt

from alpinos.offline_sales import audit, is_manager, is_offline, is_sales_officer_only

MSG_DUPLICATE = "Sales Order [{0}] is already linked to Quotation [{1}]. Duplicate Sales Order creation is blocked."
MSG_DUPLICATE_SCREEN = "Sales Order [{0}] is already linked to this Quotation. Duplicate Sales Order creation is prohibited."
MSG_GSTIN = "Billing GSTIN is missing on selected Billing Address [{0}]. Please update GSTIN in Buyer Master before proceeding with the Sales Order."
MSG_SO_CANNOT_CREATE = "Permission Denied: Sales Officers are not authorized to create Sales Orders."
MSG_SO_READ_ONLY = "Permission Denied: Sales Officers can view Sales Orders but cannot edit or submit them."
MSG_QUOTATION_ONLY = "Offline Sales Orders are created from a Finalized Quotation. Open the Quotation and click Create Sales Order."
MSG_NOT_FINALIZED = "A Sales Order can be created only from a Finalized Quotation. Quotation {0} is {1}."
MSG_BLOCKED = "A Sales Order cannot be created yet: SO Eligibility of Quotation {0} is Blocked because a required Advance payment is still pending."
MSG_REASON = "Enter the Reason for Change. Every change to a Sales Order created from a Quotation is recorded with its reason."
INACTIVE = ("Cancelled", "Rejected")
COMMERCIAL_ITEM_FIELDS = {
	"qty": "Quantity",
	"custom_selling_price": "Selling Price",
	"custom_flat_discount": "Flat Discount %",
	"custom_offer": "Offer Discount %",
	"custom_additional_discount": "Additional Discount %",
}


def quotation_required():
	return bool(frappe.db.get_single_value("Offline Sales Settings", "quotation_required_for_sales_order"))


def _offline(doc):
	return is_offline(doc.get("custom_channel"))


def _has(field):
	return frappe.db.has_column("Quotation", field)


def active_sales_order(quotation, exclude=None):
	"""The active Sales Order of a Quotation: Draft or submitted, not Cancelled / Rejected."""
	if not quotation:
		return None
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabSales Order`
		WHERE custom_quotation = %(q)s AND docstatus < 2 AND name != %(me)s
			AND IFNULL(custom_workflow_status, '') NOT IN %(inactive)s
		ORDER BY creation LIMIT 1
		""",
		{"q": quotation, "me": exclude or "", "inactive": INACTIVE},
	)
	return rows[0][0] if rows else None


def creation_problem(quotation, user=None):
	"""Why a Sales Order cannot be created from this Quotation now ("" when it can)."""
	if not is_manager(user):
		return _(MSG_SO_CANNOT_CREATE)
	q = frappe.db.get_value("Quotation", quotation, ["docstatus", "name"], as_dict=True)
	if not q:
		return _("Quotation {0} not found.").format(quotation)
	if _has("custom_quotation_status"):
		status = frappe.db.get_value("Quotation", quotation, "custom_quotation_status")
		if status != "Finalized":
			return _(MSG_NOT_FINALIZED).format(quotation, status or _("not Finalized"))
	elif q.docstatus != 1:
		return _(MSG_NOT_FINALIZED).format(quotation, _("not Finalized"))
	if _has("custom_so_eligibility") and frappe.db.get_value("Quotation", quotation, "custom_so_eligibility") != "Allowed":
		return _(MSG_BLOCKED).format(quotation)
	other = active_sales_order(quotation)
	if other:
		return _(MSG_DUPLICATE_SCREEN).format(other)
	return ""


@frappe.whitelist()
def can_create_sales_order(quotation):
	"""For the Quotation's Create Sales Order button: {allowed, reason}."""
	# company-scope: n/a (the Quotation's own read permission, which carries its company, is checked first)
	frappe.get_doc("Quotation", quotation).check_permission("read")
	problem = creation_problem(quotation)
	return {"allowed": not problem, "reason": problem}


# ------------------------------------------------------------------------------ validate


def sales_order_validate(doc, method=None):
	# company-scope: n/a (checks the order being saved and its own Quotation)
	if not _offline(doc):
		return
	if doc.is_new() and not doc.get("custom_quotation"):
		# the entry page carries the Quotation on every line (prevdoc_docname)
		doc.custom_quotation = next(
			(r.prevdoc_docname for r in doc.get("items") or [] if r.get("prevdoc_docname") and frappe.db.exists("Quotation", r.prevdoc_docname)),
			None,
		)
	if doc.is_new():
		_creation_rules(doc)
	elif doc.get("custom_quotation"):
		_keep_links(doc)
		if is_sales_officer_only():
			frappe.throw(_(MSG_SO_READ_ONLY), frappe.PermissionError)
	if doc.get("custom_quotation") and doc.docstatus == 0:
		_commercial_changes(doc)
	if doc.get("custom_quotation") and (doc.is_new() or doc.get("_action") == "submit"):
		_billing_gstin(doc)


def _creation_rules(doc):
	if not doc.get("custom_quotation"):
		if quotation_required():
			frappe.throw(_(MSG_QUOTATION_ONLY), title=_("Quotation required"))
		return
	if is_sales_officer_only():
		frappe.throw(_(MSG_SO_CANNOT_CREATE), frappe.PermissionError)
	# a row lock on the Quotation: two people creating at the same moment get one order
	frappe.db.sql("SELECT name FROM `tabQuotation` WHERE name = %s FOR UPDATE", doc.custom_quotation)
	other = active_sales_order(doc.custom_quotation, exclude=doc.name)
	if other:
		frappe.throw(_(MSG_DUPLICATE).format(other, doc.custom_quotation), title=_("Duplicate Sales Order"))
	problem = creation_problem(doc.custom_quotation)
	if problem:
		frappe.throw(problem, title=_("Sales Order from Quotation"))
	if not doc.get("custom_opportunity"):
		doc.custom_opportunity = frappe.db.get_value("Quotation", doc.custom_quotation, "opportunity")
	if not doc.get("custom_order_remarks"):
		for field in ("custom_quotation_remarks", "custom_opportunity_remark"):
			if _has(field):
				remark = frappe.db.get_value("Quotation", doc.custom_quotation, field)
				if remark:
					doc.custom_order_remarks = remark
					break


def _keep_links(doc):
	before = doc.get_doc_before_save()
	if not before or not before.get("custom_quotation"):
		return
	for field in ("custom_quotation", "custom_opportunity", "customer"):
		if (before.get(field) or "") != (doc.get(field) or ""):
			frappe.throw(
				_("This Sales Order was created from Quotation {0}, so its {1} cannot be changed.").format(
					before.custom_quotation, doc.meta.get_label(field)
				)
			)


def _rows(rows, fields, by_mrp):
	out = {}
	for r in rows or []:
		key = (r.get("item_code"), flt(r.get("custom_customer_mrp") or r.get("custom_mrp")) if by_mrp else 0.0)
		cur = out.setdefault(key, {f: 0.0 for f in fields})
		cur["qty"] += flt(r.get("qty"))
		for f in fields:
			if f != "qty":
				cur[f] = flt(r.get(f), 2)
	return out


def _commercial_changes(doc):
	"""Collect commercial differences (vs the stored order, or vs the Quotation on creation);
	a reason is required for any of them and goes with each recorded change."""
	if doc.is_new():
		source = frappe.get_doc("Quotation", doc.custom_quotation)
		meta = frappe.get_meta("Quotation Item")
		before_items, before_cash = source.get("items"), flt(source.get("custom_cash_discount"))
		by_mrp = False  # the Quotation and the order name their MRP field differently
	else:
		before = doc.get_doc_before_save()
		if not before:
			return
		meta = frappe.get_meta("Sales Order Item")
		before_items, before_cash = before.get("items"), flt(before.get("custom_cash_discount"))
		by_mrp = True
	fields = [f for f in COMMERCIAL_ITEM_FIELDS if f == "qty" or (meta.has_field(f) and frappe.get_meta("Sales Order Item").has_field(f))]
	before_rows = _rows(before_items, fields, by_mrp)
	after_rows = _rows(doc.get("items"), fields, by_mrp)
	after_cash = flt(doc.get("custom_cash_discount"))
	changes = []
	for key in sorted(set(before_rows) | set(after_rows), key=lambda k: (k[0] or "", k[1])):
		old, new = before_rows.get(key), after_rows.get(key)
		if not old:
			changes.append((key[0], "Item Added", "", f"{key[0]} x {flt(new['qty'])}"))
			continue
		if not new:
			changes.append((key[0], "Item Removed", f"{key[0]} x {flt(old['qty'])}", ""))
			continue
		for f in fields:
			if abs(flt(old[f]) - flt(new[f])) > 0.001:
				changes.append((key[0], COMMERCIAL_ITEM_FIELDS[f], old[f], new[f]))
	if abs(before_cash - after_cash) > 0.001:
		changes.append((None, "Cash Discount %", before_cash, after_cash))
	if not changes:
		return
	reason = (doc.flags.change_reason or "").strip()
	if not reason:
		frappe.throw(_(MSG_REASON), title=_("Reason for Change"))
	# the existing rule wants a row remark where the quantity went below the Quotation's: the
	# reason just given is that remark, so nobody types it twice
	reduced = {c[0] for c in changes if c[1] == "Quantity" and flt(c[3]) < flt(c[2])}
	for row in doc.get("items") or []:
		if row.item_code in reduced and not (row.get("custom_remarks") or "").strip():
			row.custom_remarks = reason
	doc.flags.commercial_changes = (changes, reason)


def on_update(doc, method=None):
	"""Write the reasoned commercial changes once the save went through."""
	pending = doc.flags.get("commercial_changes")
	if not pending:
		return
	changes, reason = pending
	doc.flags.commercial_changes = None
	for item_code, label, old, new in changes:
		audit.log("Sales Order", doc.name, "Sales Order Commercial Value Changed", label, old, new, reason=reason, item_code=item_code)


def _billing_gstin(doc):
	if (doc.get("custom_billing_gstin") or "").strip():
		return
	gst_type = frappe.db.get_value("Buyer Master", {"customer": doc.customer}, "gst_type")
	if gst_type != "Registered Business":
		return
	where = doc.get("custom_site_name") or doc.get("customer_address") or ""
	frappe.throw(_(MSG_GSTIN).format(where), title=_("Billing GSTIN missing"))


def before_submit(doc, method=None):
	if _offline(doc) and doc.get("custom_quotation") and is_sales_officer_only():
		frappe.throw(_(MSG_SO_READ_ONLY), frappe.PermissionError)


# ------------------------------------------------------------------------------ Quotation status


def after_insert(doc, method=None):
	"""The Quotation now has its Sales Order (doc 3, 9)."""
	if not doc.get("custom_quotation"):
		return
	q = doc.custom_quotation
	values = {}
	if _has("custom_linked_sales_order"):
		values["custom_linked_sales_order"] = doc.name
	before = frappe.db.get_value("Quotation", q, "custom_quotation_status") if _has("custom_quotation_status") else None
	if _has("custom_quotation_status"):
		values["custom_quotation_status"] = "Sales Order Created"
	if values:
		frappe.db.set_value("Quotation", q, values, update_modified=False)
	audit.log("Quotation", q, "Sales Order Created", "Sales Order ID", None, doc.name)
	if before is not None:
		audit.log("Quotation", q, "Quotation Status Changed", "Quotation Status", before, "Sales Order Created")
	audit.log("Sales Order", doc.name, "Sales Order Created", "Linked Quotation",
		None, doc.custom_quotation + (f" / Opportunity {doc.custom_opportunity}" if doc.get("custom_opportunity") else ""))


def release_quotation(sales_order, why):
	"""Back to Finalized when the Quotation's order is cancelled, deleted or rejected."""
	so = frappe.db.get_value("Sales Order", sales_order, ["custom_quotation", "name"], as_dict=True)
	q = so.custom_quotation if so else None
	if not q or not _has("custom_quotation_status"):
		return
	if active_sales_order(q, exclude=sales_order):
		return
	current = frappe.db.get_value("Quotation", q, ["custom_quotation_status", "custom_linked_sales_order"], as_dict=True)
	if current.custom_quotation_status != "Sales Order Created":
		return
	frappe.db.set_value("Quotation", q, {"custom_quotation_status": "Finalized", "custom_linked_sales_order": None},
		update_modified=False)
	audit.log("Quotation", q, "Sales Order Released", "Sales Order ID", sales_order, None, reason=why)
	audit.log("Quotation", q, "Quotation Status Changed", "Quotation Status", "Sales Order Created", "Finalized", reason=why)


def on_cancel(doc, method=None):
	if doc.get("custom_quotation"):
		release_quotation(doc.name, _("Sales Order {0} cancelled").format(doc.name))


def on_trash(doc, method=None):
	if doc.get("custom_quotation") and doc.docstatus == 0:
		frappe.db.set_value("Sales Order", doc.name, "custom_workflow_status", "Cancelled", update_modified=False)
		release_quotation(doc.name, _("Draft Sales Order {0} deleted").format(doc.name))


def on_rejected(sales_order):
	release_quotation(sales_order, _("Sales Order {0} rejected").format(sales_order))


def on_submit(doc, method=None):
	"""The doc's "Sales Order Submitted" row with the final values, and "Fulfillment Handoff"
	(by the System) as the order goes to the existing Warehouse / Pick List / QC / Delivery
	Note / Dispatch flow."""
	if _offline(doc):
		lines = [r for r in doc.get("items") or [] if r.item_code]
		final = _("{0} lines, Qty {1}, Grand Total {2}").format(
			len(lines), flt(sum(flt(r.qty) for r in lines)), frappe.utils.fmt_money(doc.grand_total, currency=doc.currency)
		)
		audit.log("Sales Order", doc.name, "Sales Order Submitted", "Final Values", "Draft", final, after_submit=1)
		audit.log("Sales Order", doc.name, "Fulfillment Handoff", "Status", "Submitted", "Downstream Processing",
			reason=_("Submitted Sales Order handed to the existing operational workflow"), after_submit=1, role="System")


# ------------------------------------------------------------------------------ catalogue


def stamp_catalog_on_submit(doc, method=None):
	"""Last Order Date + Linked Sales Order on every Buyer Catalog row this order synced."""
	# company-scope: n/a (writes the order's own buyer's catalogue rows)
	if (doc.get("custom_channel") or "").strip() == "E-com" or not doc.get("customer"):
		return
	if not frappe.db.has_column("Buyer Item", "last_sales_order"):
		return
	from alpinos import item_mrp as IM

	for row in doc.get("items") or []:
		if not row.item_code or flt(row.get("custom_selling_price")) <= 0:
			continue
		mrp = flt(row.get("custom_customer_mrp"))
		by_mrp = bool(mrp > 0 and IM.applicable(row.item_code).tracked)
		buyer = doc.get("custom_offline_buyer_master") or frappe.db.get_value("Buyer Master", {"customer": doc.customer}, "name")
		if buyer:
			# doc Section 8: Buyer, SKU, Submitted SO, Selling Price, Discount
			audit.log("Buyer Master", buyer, "Buyer Catalog Updated", "Selling Price / Flat Discount %", None,
				f"{flt(row.get('custom_selling_price'), 2)} / {flt(row.get('custom_flat_discount'), 2)}%",
				reason=_("From submitted Sales Order {0}").format(doc.name), item_code=row.item_code, role="System")
		frappe.db.sql(
			f"""
			UPDATE `tabBuyer Item` bil
			INNER JOIN `tabBuyer Items` bi ON bi.name = bil.parent AND bil.parenttype = 'Buyer Items'
			SET bil.last_order_date = %(date)s, bil.last_sales_order = %(so)s
			WHERE bi.buyer = %(customer)s AND IFNULL(bi.docstatus, 0) < 2 AND bil.item_code = %(item)s
				{"AND ROUND(IFNULL(bil.mrp, 0), 2) = %(mrp)s" if by_mrp else ""}
			""",
			{"date": doc.transaction_date, "so": doc.name, "customer": doc.customer, "item": row.item_code, "mrp": IM.q(mrp) if by_mrp else 0},
		)
