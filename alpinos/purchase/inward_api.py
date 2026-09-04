"""Whitelisted endpoints behind the Purchase Inward entry form (BRD 2.1 - 2.3).

Tasks 293 / 294 / 295. The desk form calls nothing but this module, and this module
calls nothing of its own: every rule it enforces already lives somewhere else and is
imported.

    freeze / section ownership  ->  alpinos.purchase.roles.can_edit_section
    who may run which action    ->  alpinos.purchase.workflow.assert_transition
    VAL-PI-01 / 02 / 13 / 15 / 22 -> PurchaseInward's own validate() helpers
    pending quantity maths      ->  PurchaseInward.received_by_po_detail

The one genuinely new thing here is the merge (BR-PI-16 .. BR-PI-18 / VAL-PI-14 /
19 / 20 / 21). The controller only decides *whether* a duplicate invoice number is an
error; picking a partner to merge with, deciding whether that partner is still
eligible, and recording the link are separate concerns and live below.

Merge semantics: `Purchase Inward.merged_into` already exists on the doctype, and
`PurchaseInward._validate_invoice_number` already returns early when it is set. So a
merge is a LINK, not a rewrite — the duplicate inward keeps its own rows, quantities
and audit trail (BRD "Merge Purchase Inward"), and states which earlier inward carries
the same vendor invoice. Nothing is destroyed and nothing is copied, which is the only
shape that survives the target already being submitted (`items` is not allow_on_submit).
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.alpinos_development.doctype.purchase_inward.purchase_inward import PurchaseInward
from alpinos.purchase import constants as C
from alpinos.purchase import workflow
from alpinos.purchase.roles import (
	SECTION_HEADER,
	assert_can_edit_section,
	can_edit_section,
	get_section_access,
)

DOCTYPE = "Purchase Inward"
PO_ITEM = "Purchase Order Item"

# A probe document is never saved; it only needs a name so that the controller's
# `name != self.name` duplicate filters compile to something SQL can match. A blank
# name would become `name != NULL`, which matches no row and turns every duplicate
# check green.
_PROBE_NAME = "__alpinos-purchase-inward-probe__"

# Downstream links that make an inward ineligible for merging (BR-PI-18 / VAL-PI-21).
DOWNSTREAM_FIELDS = ("purchase_qc", "purchase_receipt", "purchase_invoice", "debit_note")

# The only statuses at which an inward is still "before downstream processing".
MERGE_OPEN_STATUSES = (C.PI_DRAFT, C.PI_PENDING_RECEIPT)

# Transitions that already have their own whitelisted implementation elsewhere. Any
# action the workflow engine offers but that is not listed here is refused rather than
# silently reduced to a status write — a status must never move without its document.
ACTION_ENDPOINTS = {
	"submit_for_qc": "alpinos.purchase.notifications.submit_for_qc",
	"generate_grn": "alpinos.purchase.grn.generate_grn",
}

# Transitions whose implementation lives on the linked Purchase QC. These need their own
# map because purchase_qc.start_qc / complete_qc take the QC name, not the inward's, so
# dispatching them like ACTION_ENDPOINTS would hand them the wrong document. Without this
# the form offered enabled Start QC / Complete QC buttons whose only outcome was
# "... cannot be run from the Purchase Inward form."
QC_ACTION_ENDPOINTS = {
	"start_qc": "alpinos.alpinos_development.doctype.purchase_qc.purchase_qc.start_qc",
	"complete_qc": "alpinos.alpinos_development.doctype.purchase_qc.purchase_qc.complete_qc",
}


# ------------------------------------------------------------------ item type

# How an Item declares which inward type it belongs to, most explicit first:
#
#   1. `Item.custom_inward_type` — the same fieldname the Purchase Order already uses
#      for the inward type. The field does not exist on alpinos.test today; this branch
#      is what picks it up the day it is added, with no change here.
#   2. `Item.item_group`, and every ancestor group up to the root. A group is read as a
#      type when its name IS one of the codes (RM / PM / FG / MM) or contains one of the
#      spelled-out phrases below.
#
# Anything else is UNCLASSIFIED, not "mismatched" — alpinos.test ships exactly two item
# groups ("Products", "Marketing Material"), neither of which says anything about RM /
# PM / FG / MM. Guessing a mapping for them would quietly hide real Purchase Order lines
# from the Get Items dialog, so an unclassified item is always offered.
ITEM_TYPE_FIELD = "custom_inward_type"

GROUP_PHRASES = (
	(C.INWARD_RM, ("raw material", "raw materials")),
	(C.INWARD_PM, ("packaging material", "packing material", "packaging materials")),
	(C.INWARD_FG, ("finished good", "finished goods")),
	(C.INWARD_MM, ("miscellaneous material", "miscellaneous materials", "miscellaneous")),
)


def _normalise(value):
	return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _type_from_group_name(group):
	norm = _normalise(group)
	if not norm:
		return None
	upper = norm.upper()
	if upper in C.INWARD_TYPES:
		return upper
	for code, phrases in GROUP_PHRASES:
		if any(phrase in norm for phrase in phrases):
			return code
	return None


def _group_chain(item_group, cache):
	"""[group, parent, ... root] for an Item Group, most specific first."""
	if item_group in cache:
		return cache[item_group]
	bounds = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		cache[item_group] = [item_group]
		return cache[item_group]
	chain = frappe.get_all(
		"Item Group",
		filters={"lft": ("<=", bounds.lft), "rgt": (">=", bounds.rgt)},
		pluck="name",
		order_by="lft desc",
	)
	cache[item_group] = chain or [item_group]
	return cache[item_group]


def item_inward_type(item_code, cache=None):
	"""The inward type an Item belongs to, or None when it is unclassified."""
	cache = cache if cache is not None else {}
	items = cache.setdefault("items", {})
	if item_code in items:
		return items[item_code]

	fields = ["item_group"]
	has_field = bool(frappe.get_meta("Item").get_field(ITEM_TYPE_FIELD))
	if has_field:
		fields.append(ITEM_TYPE_FIELD)
	row = frappe.db.get_value("Item", item_code, fields, as_dict=True) or {}

	resolved = None
	declared = (row.get(ITEM_TYPE_FIELD) or "").strip().upper() if has_field else ""
	if declared in C.INWARD_TYPES:
		resolved = declared
	elif row.get("item_group"):
		for group in _group_chain(row.item_group, cache.setdefault("groups", {})):
			resolved = _type_from_group_name(group)
			if resolved:
				break

	items[item_code] = resolved
	return resolved


# -------------------------------------------------------------------- probes


def _probe(purchase_inward=None, **values):
	"""The real document when we have one, otherwise a throwaway carrying the same fields.

	Every validation below is the controller's own method, so it must be called on a
	document — not re-implemented against a dict.
	"""
	if purchase_inward and frappe.db.exists(DOCTYPE, purchase_inward):
		doc = frappe.get_doc(DOCTYPE, purchase_inward)
		doc.check_permission("read")
	else:
		frappe.has_permission(DOCTYPE, "read", throw=True)
		doc = frappe.new_doc(DOCTYPE)
		doc.name = _PROBE_NAME
	for key, value in values.items():
		if value not in (None, ""):
			doc.set(key, value)
	return doc


def _check(code, field, fn):
	"""Run one controller validation and report it instead of raising it.

	The messages the validators raise are already the BRD's own wording, so they are
	passed through untouched (they carry document links, hence the HTML).
	"""
	mark = len(frappe.get_message_log())
	try:
		fn()
	except Exception as exc:
		frappe.local.message_log = frappe.local.message_log[:mark]
		return {"code": code, "field": field, "ok": False, "message": str(exc)}
	frappe.local.message_log = frappe.local.message_log[:mark]
	return {"code": code, "field": field, "ok": True, "message": None}


@frappe.whitelist()
def validate_creation(
	purchase_order=None,
	invoice_number=None,
	challan_no=None,
	inward_type=None,
	purchase_inward=None,
):
	"""BRD 2.5 creation validations, as data rather than as exceptions.

	Lets the form warn while the user is still typing. Nothing here is a substitute for
	the server twins — the same three methods run again inside `PurchaseInward.validate`
	on every save, whatever the form did or did not ask.
	"""
	doc = _probe(
		purchase_inward=purchase_inward,
		purchase_order=purchase_order,
		invoice_number=invoice_number,
		challan_no=challan_no,
		inward_type=inward_type,
	)

	checks = [_check("VAL-PI-01/02", "purchase_order", doc._validate_purchase_order)]
	# The invoice and challan checks are per-vendor, and the vendor is only known once
	# the Purchase Order has been resolved above.
	checks.append(_check("VAL-PI-13/15", "invoice_number", doc._validate_invoice_number))
	checks.append(_check("VAL-PI-22", "challan_no", doc._validate_challan_no))

	failed = {c["code"]: c for c in checks if not c["ok"]}
	candidates = []
	if "VAL-PI-13/15" in failed and doc.supplier and doc.invoice_number:
		candidates = get_merge_candidates(
			doc.supplier,
			doc.invoice_number,
			exclude=doc.name if doc.name != _PROBE_NAME else None,
		)

	return {
		"ok": not failed,
		"checks": checks,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name
		or (frappe.db.get_value("Supplier", doc.supplier, "supplier_name") if doc.supplier else None),
		"company": doc.company,
		"inward_type": doc.inward_type,
		"merge_candidates": candidates,
	}


# ------------------------------------------------------- items from the order


@frappe.whitelist()
def get_purchase_order_items(
	purchase_order, inward_type=None, purchase_inward=None, include_unmatched=0
):
	"""Purchase Order lines that still have pending quantity, filtered by inward type.

	"Pending" is whatever `PurchaseInward.received_by_po_detail` says is left — the
	cumulative receipt of the SUBMITTED inwards on this order (ARCHITECTURE decision 6),
	never `Purchase Order Item.received_qty`, which counts submitted Purchase Receipts
	and would let two inwards raised in the same window jointly over-receive.

	Rows are dropped for exactly two reasons, and both are reported back so the form can
	explain an empty result rather than looking broken:

	    fully_received  pending quantity has reached zero
	    type_mismatch   the item belongs to a different inward type (see item_inward_type)

	Drop-ship rows are never offered: ERPNext sets their received_qty to the ordered
	quantity during PO validate and `make_purchase_receipt` skips them, so receiving one
	would double-count against the order.
	"""
	include_unmatched = cint(include_unmatched)
	doc = _probe(
		purchase_inward=purchase_inward,
		purchase_order=purchase_order,
		inward_type=inward_type,
	)
	# Filling the grid is an edit of the Purchase-owned header section.
	assert_can_edit_section(doc, SECTION_HEADER)
	# VAL-PI-01 / 02 and the PO gates, and it stamps supplier / company / inward type.
	doc._validate_purchase_order()

	wanted = doc.inward_type or None
	rows = frappe.get_all(
		PO_ITEM,
		filters={
			"parent": doc.purchase_order,
			"parenttype": "Purchase Order",
			"docstatus": 1,
		},
		fields=[
			"name",
			"idx",
			"item_code",
			"item_name",
			"description",
			"uom",
			"stock_uom",
			"conversion_factor",
			"qty",
			"rate",
			"amount",
			"warehouse",
			"delivered_by_supplier",
		],
		order_by="idx asc",
	)
	rows = [r for r in rows if not cint(r.delivered_by_supplier)]

	received = PurchaseInward.received_by_po_detail(
		doc.purchase_order,
		[r.name for r in rows],
		exclude_inward=purchase_inward or None,
	)

	cache = {}
	items = []
	skipped = {"fully_received": 0, "type_mismatch": 0}
	unmatched_available = 0

	for row in rows:
		previously = flt(received.get(row.name))
		pending = flt(row.qty) - previously
		if pending <= 0:
			skipped["fully_received"] += 1
			continue

		found = item_inward_type(row.item_code, cache)
		# An unclassified item is offered against every inward type; only a positive
		# disagreement is a mismatch.
		mismatch = bool(wanted and found and found != wanted)
		if mismatch:
			unmatched_available += 1
			if not include_unmatched:
				skipped["type_mismatch"] += 1
				continue

		items.append(
			{
				"po_detail": row.name,
				"purchase_order": doc.purchase_order,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"description": row.description,
				"uom": row.uom,
				"stock_uom": row.stock_uom,
				"conversion_factor": flt(row.conversion_factor) or 1.0,
				"order_qty": flt(row.qty),
				"previously_received_qty": previously,
				"pending_qty": pending,
				# Received Quantity belongs to the Store Team (BRD 2.2.1); the Purchase
				# Team only declares which lines arrived on this invoice.
				"received_qty": 0.0,
				"rate": flt(row.rate),
				"amount": flt(row.amount),
				"target_warehouse": row.warehouse or doc.target_warehouse,
				"item_inward_type": found,
				"matches_inward_type": not mismatch,
			}
		)

	return {
		"purchase_order": doc.purchase_order,
		"inward_type": wanted,
		"supplier": doc.supplier,
		"company": doc.company,
		"items": items,
		"skipped": skipped,
		"unmatched_available": unmatched_available,
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def po_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for `Purchase Inward Item.item_code`.

	Manual Add Row is filtered exactly like the Get Items button, so the two cannot
	offer different item sets. `filters` carries purchase_order, inward_type and (when
	the inward is saved) purchase_inward.
	"""
	filters = filters or {}
	purchase_order = filters.get("purchase_order")
	if not purchase_order:
		return []

	try:
		payload = get_purchase_order_items(
			purchase_order,
			inward_type=filters.get("inward_type"),
			purchase_inward=filters.get("purchase_inward") or None,
		)
	except (frappe.PermissionError, frappe.ValidationError):
		# A link search must never raise at somebody who is merely looking: neither a
		# section they do not own nor a Purchase Order that has since been put On Hold
		# should surface as an error dialog under the item picker.
		return []

	txt = (txt or "").lower()
	rows = []
	for item in payload["items"]:
		haystack = "{0} {1}".format(item["item_code"], item["item_name"] or "").lower()
		if txt and txt not in haystack:
			continue
		rows.append((item["item_code"], item["item_name"], item["pending_qty"]))
	return rows[start : start + page_len]


# ------------------------------------------------------------------- merging


def _merge_block_reason(row):
	"""BR-PI-18 / VAL-PI-21 — why this inward cannot take part in a merge, or None."""
	if cint(row.get("docstatus")) == 2:
		return _("A cancelled Purchase Inward cannot be merged.")
	for field in DOWNSTREAM_FIELDS:
		if row.get(field):
			return _(
				"This Purchase Inward cannot be merged because downstream processing has "
				"already been completed."
			)
	if (row.get("inward_status") or C.PI_DRAFT) not in MERGE_OPEN_STATUSES:
		return _(
			"This Purchase Inward cannot be merged because downstream processing has "
			"already been completed."
		)
	return None


MERGE_FIELDS = (
	"name",
	"docstatus",
	"inward_status",
	"supplier",
	"supplier_name",
	"invoice_number",
	"invoice_date",
	"challan_no",
	"purchase_order",
	"total_received_qty",
	"total_items",
	"merged_into",
) + DOWNSTREAM_FIELDS


@frappe.whitelist()
def get_merge_candidates(supplier, invoice_number, exclude=None):
	"""VAL-PI-14 — the existing inwards a duplicate invoice number could merge with.

	`frappe.get_list` rather than `get_all`: the user is about to be shown these rows, so
	they must pass the permission query and `has_permission` hooks.
	"""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	if not (supplier and invoice_number):
		return []

	filters = {
		"supplier": supplier,
		"invoice_number": invoice_number,
		"docstatus": ("<", 2),
	}
	if exclude:
		filters["name"] = ("!=", exclude)

	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		fields=list(MERGE_FIELDS),
		order_by="creation asc",
		limit_page_length=20,
	)
	for row in rows:
		reason = _merge_block_reason(row)
		row["eligible"] = reason is None and not row.get("merged_into")
		row["reason"] = reason or (
			_("This Purchase Inward has itself already been merged into {0}.").format(
				row.get("merged_into")
			)
			if row.get("merged_into")
			else None
		)
	return rows


def assert_merge_allowed(doc, target, user=None):
	"""BR-PI-17 / BR-PI-18 and VAL-PI-19 / 20 / 21 for one (source, target) pair."""
	if not target:
		return
	if target == doc.get("name"):
		frappe.throw(_("A Purchase Inward cannot be merged into itself."))

	row = frappe.db.get_value(DOCTYPE, target, list(MERGE_FIELDS), as_dict=True)
	if not row:
		frappe.throw(_("Purchase Inward {0} does not exist.").format(target))

	if (row.supplier or "") != (doc.get("supplier") or ""):
		frappe.throw(
			_("Purchase Inward can only be merged for the same Vendor."), title=_("VAL-PI-19")
		)
	if (row.invoice_number or "") != (doc.get("invoice_number") or ""):
		frappe.throw(
			_("Purchase Inward can only be merged when the Invoice Number is the same."),
			title=_("VAL-PI-20"),
		)

	blocked = _merge_block_reason(row)
	if blocked:
		frappe.throw(blocked, title=_("VAL-PI-21"))
	if row.merged_into:
		frappe.throw(
			_("Purchase Inward {0} has itself already been merged into {1}.").format(
				target, row.merged_into
			),
			title=_("VAL-PI-21"),
		)

	# The document being merged must be just as free of downstream processing, or the
	# merge would tie a finished chain to an unfinished one.
	source = {field: doc.get(field) for field in MERGE_FIELDS if field != "name"}
	source["docstatus"] = doc.get("docstatus")
	blocked = _merge_block_reason(source)
	if blocked:
		frappe.throw(blocked, title=_("VAL-PI-21"))


def validate_merge_link(doc, method=None):
	"""doc_event `validate` twin of the form's Merge prompt.

	The Merge button only sets `merged_into`, and setting that field is what lets
	`PurchaseInward._validate_invoice_number` accept a duplicate invoice number. Without
	this guard a REST client could set it to any inward at all and walk straight past
	BR-PI-15.
	"""
	if doc.doctype != DOCTYPE or not doc.get("merged_into"):
		return
	# Only the moment the link is made is judged. Re-testing eligibility on every later
	# save would block a perfectly ordinary edit as soon as the target reached QC — the
	# link is a historical fact, not a standing claim.
	if not doc.has_value_changed("merged_into"):
		return
	assert_merge_allowed(doc, doc.merged_into)


@frappe.whitelist()
def merge_with_existing_inward(purchase_inward, target, reason=None):
	"""BRD "Merge Purchase Inward" — link this inward to the one holding the same invoice.

	Both documents keep their own rows and quantities; the relationship and the audit
	trail is the point (BR-PI-16). Returns the stored link.
	"""
	doc = frappe.get_doc(DOCTYPE, purchase_inward)
	doc.check_permission("write")
	assert_merge_allowed(doc, target)

	if cint(doc.docstatus) == 0:
		doc.merged_into = target
		# merged_into sits at permlevel 1 (roles._setup_audit_permlevel), and frappe runs
		# validate_higher_perm_levels() BEFORE validate() on save: without this flag anyone
		# short of an Admin role has the link reset to None on the way in, and the very next
		# check — _validate_invoice_number — then blocks the save on the duplicate invoice
		# (BR-PI-15) the merge existed to resolve. The merge is already authorised above by
		# check_permission("write") + assert_merge_allowed, so exempt this one field rather
		# than save with ignore_permissions; a plain REST save of merged_into is still reset.
		doc.flags.ignore_permlevel_for_fields = ["merged_into"]
		doc.save()
	else:
		# merged_into is allow_on_submit, so a submitted inward takes the link directly.
		doc.db_set("merged_into", target)

	note = _("Merged with {0} (same Vendor and Invoice Number).").format(target)
	if reason:
		note = "{0} {1}".format(note, reason)
	doc.add_comment("Comment", note)
	frappe.get_doc(DOCTYPE, target).add_comment(
		"Comment", _("Purchase Inward {0} was merged into this document.").format(doc.name)
	)
	return {"name": doc.name, "merged_into": target}


# ------------------------------------------------------------------- actions


def assert_action(doc, action, user=None):
	"""One gate for every button the form draws, transition or not.

	`workflow.assert_transition` owns the status transitions; the read-only actions of
	BRD 1.4 (edit / delete / print / view ...) are not transitions and are checked
	against `workflow.available_actions`, which applies the same role rules. Going
	through the engine for both is what stops the form and the list page from disagreeing.
	"""
	status = doc.get("inward_status") or C.PI_DRAFT
	if any(t["action"] == action for t in workflow.INWARD_TRANSITIONS.get(status, [])):
		return workflow.assert_transition(doc, action, user)

	for entry in workflow.available_actions(doc, user):
		if entry["action"] != action:
			continue
		if not entry["enabled"]:
			frappe.throw(entry["reason"] or _("{0} is not available.").format(entry["label"]))
		return entry

	frappe.throw(
		_("{0} is not available while the Purchase Inward is {1}.").format(
			action.replace("_", " ").title(), status
		)
	)


def assert_submit_transition(doc, method=None):
	"""doc_event `before_submit` — route the desk Submit button through the engine.

	doc_events run AFTER the controller method, and `PurchaseInward.before_submit` has
	by then already moved `inward_status` to Pending Material Receipt, so the status the
	transition must be judged against is read back from the database rather than off the
	document in hand.
	"""
	if doc.doctype != DOCTYPE:
		return
	if frappe.flags.in_migrate or frappe.flags.in_install or frappe.flags.in_patch:
		return
	if frappe.flags.in_import or doc.flags.get("ignore_permissions"):
		return

	status = (
		frappe.db.get_value(DOCTYPE, doc.name, "inward_status") if doc.name else None
	) or C.PI_DRAFT
	probe = frappe._dict(doc.as_dict())
	probe["inward_status"] = status
	workflow.assert_transition(probe, "submit")


@frappe.whitelist()
def run_action(purchase_inward, action):
	"""Run one workflow action from the form.

	Every branch is gated by `assert_action` first, and the work itself is always
	delegated — this module owns no transition of its own.
	"""
	doc = frappe.get_doc(DOCTYPE, purchase_inward)
	doc.check_permission("read")
	assert_action(doc, action)

	if action == "submit":
		doc.submit()
	elif action in ACTION_ENDPOINTS:
		frappe.get_attr(ACTION_ENDPOINTS[action])(purchase_inward=purchase_inward)
	elif action in QC_ACTION_ENDPOINTS:
		if not doc.get("purchase_qc"):
			frappe.throw(
				_("No Purchase QC has been raised against {0} yet.").format(doc.name)
			)
		frappe.get_attr(QC_ACTION_ENDPOINTS[action])(purchase_qc=doc.purchase_qc)
	else:
		frappe.throw(
			_("{0} cannot be run from the Purchase Inward form.").format(
				action.replace("_", " ").title()
			)
		)

	doc.reload()
	return {
		"name": doc.name,
		"docstatus": cint(doc.docstatus),
		"inward_status": doc.inward_status,
	}


@frappe.whitelist()
def cancel_draft(purchase_inward):
	"""BRD 2.3.3 Cancel — "Cancel the Purchase Inward before submission".

	A draft has no cancelled state in Frappe, so cancelling one before submission means
	discarding it. The engine calls this action `delete` (BRD 1.4 lists Edit / Delete /
	Print at Draft), and the permission is checked as such. A SUBMITTED inward is
	cancelled by the standard Cancel button, which runs `PurchaseInward.on_cancel` and
	its reverse-chronological downstream guard (BRD 5.3).
	"""
	doc = frappe.get_doc(DOCTYPE, purchase_inward)
	doc.check_permission("read")
	if cint(doc.docstatus) != 0:
		frappe.throw(
			_(
				"Only a draft Purchase Inward can be cancelled here. Use Cancel on the "
				"submitted document instead."
			)
		)
	assert_action(doc, "delete")
	doc.check_permission("delete")
	frappe.delete_doc(DOCTYPE, purchase_inward)
	return {"deleted": purchase_inward}


# ------------------------------------------------------------- form context


@frappe.whitelist()
def get_form_context(purchase_inward=None):
	"""Everything the form needs to draw itself, in one round trip.

	`sections` and `actions` are the same structures the list page and the SPA read, so
	no screen can invent a button or unlock a section the others would refuse.
	"""
	name = purchase_inward if purchase_inward and frappe.db.exists(DOCTYPE, purchase_inward) else None
	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.check_permission("read")
	else:
		frappe.has_permission(DOCTYPE, "read", throw=True)
		doc = frappe.new_doc(DOCTYPE)

	editable, reason = can_edit_section(doc, SECTION_HEADER)
	return {
		"name": name,
		"docstatus": cint(doc.get("docstatus")),
		"status": doc.get("inward_status") or C.PI_DRAFT,
		"sections": get_section_access(DOCTYPE, name),
		"actions": workflow.available_actions(doc),
		"header_editable": bool(editable),
		"header_reason": reason,
	}


# ------------------------------------------- admin invoice-number correction


@frappe.whitelist()
def correct_invoice_number(purchase_inward, new_invoice_number, reason=None):
	"""BR-PI-19/20/21 and VAL-PI-16/17/18/24 - Admin correction of the Invoice Number.

	The doctype already shipped the storage for this (original_invoice_number and the
	invoice_change_log table) but nothing ever wrote it, and Invoice No. is allow_on_submit=0,
	so once an inward was submitted the number could only be changed with a direct db_set from
	the console. That is exactly the case the BRD calls out: a vendor reissues an invoice long
	after the material was received, and the correction has to be possible AND fully audited.

	Deliberately allowed at any status, including Completed (BR-PI-19). Everything is
	recorded: the original number, the new one, who changed it, when, and why.
	"""
	from alpinos.purchase import workflow

	doc = frappe.get_doc(DOCTYPE, purchase_inward)
	doc.check_permission("read")

	# VAL-PI-18: only an authorised Admin, whatever their DocPerm write access says.
	if not (workflow.user_roles() & set(C.INVOICE_CORRECTION_ROLES)):
		frappe.throw(
			_("Invoice Number can only be updated by an authorized Admin."),
			frappe.PermissionError,
			title=_("VAL-PI-18"),
		)

	new_invoice_number = str(new_invoice_number or "").strip()
	if not new_invoice_number:
		frappe.throw(_("Please enter the new Invoice Number."))

	# VAL-PI-24: the reason is not optional.
	reason = str(reason or "").strip()
	if not reason:
		frappe.throw(
			_("Please provide a reason for changing the Invoice Number."),
			title=_("VAL-PI-24"),
		)

	old_invoice_number = str(doc.invoice_number or "").strip()
	if new_invoice_number == old_invoice_number:
		frappe.throw(_("The Invoice Number is already {0}.").format(new_invoice_number))

	# VAL-PI-17: still unique for this vendor.
	clash = frappe.get_all(
		DOCTYPE,
		filters={
			"name": ("!=", doc.name),
			"supplier": doc.supplier,
			"invoice_number": new_invoice_number,
			"docstatus": ("<", 2),
		},
		pluck="name",
		limit=5,
	)
	if clash:
		frappe.throw(
			_("This Invoice Number already exists for this Vendor.<br><br>Existing: {0}").format(
				", ".join(frappe.utils.get_link_to_form(DOCTYPE, n) for n in clash)
			),
			title=_("VAL-PI-17"),
		)

	# The first correction is what defines "original"; later ones must not overwrite it.
	if not (doc.original_invoice_number or "").strip():
		doc.db_set("original_invoice_number", old_invoice_number, update_modified=False)

	# Invoice No. is allow_on_submit=0, and original_invoice_number is engine-owned, so both
	# are written with db_set - which bypasses the save path and its guards by design.
	doc.db_set("invoice_number", new_invoice_number, update_modified=False)

	# The log row is inserted directly rather than through doc.append()+save(): saving the
	# parent would re-enter before_update_after_submit and trip _guard_engine_owned_fields.
	frappe.get_doc(
		{
			"doctype": "Purchase Invoice Change Log",
			"parent": doc.name,
			"parenttype": DOCTYPE,
			"parentfield": "invoice_change_log",
			"idx": cint(frappe.db.count("Purchase Invoice Change Log", {"parent": doc.name})) + 1,
			"old_invoice_no": old_invoice_number,
			"new_invoice_no": new_invoice_number,
			"reason": reason,
			"changed_by": frappe.session.user,
			"changed_on": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)

	doc.add_comment(
		"Comment",
		_("Invoice Number corrected from {0} to {1}. Reason: {2}").format(
			old_invoice_number or "(blank)", new_invoice_number, reason
		),
	)
	return {
		"name": doc.name,
		"invoice_number": new_invoice_number,
		"original_invoice_number": doc.original_invoice_number or old_invoice_number,
	}
