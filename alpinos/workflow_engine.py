"""Operations workflow engine — keeps `custom_workflow_status` accurate across
the Sales Order -> Pick List -> Delivery Note lifecycle.

Phase 2 of the Operations workflow (Phase 1 = roles / permissions / status
fields, see workflow_role_access.py). This module drives the status *fields*
through their lifecycle via doc_events, enforces the cross-document
cancellation rules, and exposes the few user actions that have no document
event to hang off (Future Dispatch, Mark Delivered, Start Picking).

Status sources of truth:
  * Sales Order.custom_workflow_status  — 10 stages
  * Pick List.custom_workflow_status    — 8 stages
  * Delivery Note uses native docstatus (Draft / Dispatched / Cancelled)

Stock movement is intentionally left to native ERPNext (deducted on Delivery
Note submit). "Reserved" in the spec is reflected by the workflow status, not
by separate stock ledger entries.
"""

import frappe
from frappe.utils import flt, today


# --- SO / PL status vocab ---------------------------------------------------

SO_DRAFT = "Draft"
SO_WAREHOUSE_PENDING = "Warehouse Approval Pending"
SO_FUTURE_DISPATCH = "Future Dispatch"
SO_WAREHOUSE_APPROVED = "Warehouse Approved"
SO_PICKING = "Picking In Progress"
SO_READY = "Ready For Dispatch"
SO_DN_CREATED = "Delivery Note Created"
SO_DISPATCHED = "Dispatched"
SO_COMPLETED = "Completed"
SO_CANCELLED = "Cancelled"

# SO stages that may still be steered by Pick List progress (never regress past
# these — once a DN exists or the order is dispatched, PL edits must not pull it
# backwards).
SO_EARLY_STAGES = {
	SO_WAREHOUSE_PENDING,
	SO_FUTURE_DISPATCH,
	SO_WAREHOUSE_APPROVED,
	SO_PICKING,
}

PL_DRAFT = "Draft"
PL_PICKING_PENDING = "Picking Pending"
PL_PICKING = "Picking In Progress"
PL_STICKER_PENDING = "Sticker Pending"
PL_SUBMISSION_PENDING = "Submission Pending"
PL_READY = "Ready To Dispatch"
PL_DISPATCHED = "Dispatched"
PL_CANCELLED = "Cancelled"

# PL stages that mean "actively being worked" -> SO should read Picking In Progress.
PL_ACTIVE_STAGES = {PL_PICKING, PL_STICKER_PENDING, PL_SUBMISSION_PENDING}

WAREHOUSE_ROLES = {"Warehouse Admin", "Warehouse Manager", "System Manager"}
SALES_ROLES = {"Sales Admin", "Sales Manager", "System Manager"}
PICKER_ROLES = {"PL User", "Warehouse User", "Warehouse Admin", "Warehouse Manager", "System Manager"}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _set_status(doctype, name, status):
	"""Write a workflow status only when it actually changes. Direct DB write so
	it never re-triggers document hooks (no recursion) and works on submitted
	docs (the field is allow_on_submit)."""
	if not name or not status:
		return
	if frappe.db.get_value(doctype, name, "custom_workflow_status") == status:
		return
	frappe.db.set_value(doctype, name, "custom_workflow_status", status, update_modified=False)


def _require_roles(roles):
	if not (set(frappe.get_roles()) & set(roles)):
		frappe.throw(frappe._("You are not permitted to perform this action."))


# --- relationship lookups ---------------------------------------------------

def _so_of_pick_list(doc_or_name):
	if isinstance(doc_or_name, str):
		so = frappe.db.get_value("Pick List", doc_or_name, "custom_sales_order_id")
		if so:
			return so
		doc = frappe.get_doc("Pick List", doc_or_name)
	else:
		doc = doc_or_name
		if doc.get("custom_sales_order_id"):
			return doc.custom_sales_order_id
	for row in doc.get("locations") or []:
		if row.get("sales_order"):
			return row.sales_order
	return None


def _so_of_delivery_note(doc):
	if doc.get("custom_sales_order_id"):
		return doc.custom_sales_order_id
	for row in doc.get("items") or []:
		if row.get("against_sales_order"):
			return row.against_sales_order
	return None


def _pick_list_of_delivery_note(doc):
	for row in doc.get("items") or []:
		if row.get("against_pick_list"):
			return row.against_pick_list
	return None


def _active_pick_lists_for_so(so):
	if not so:
		return []
	return frappe.get_all(
		"Pick List",
		filters={"custom_sales_order_id": so, "docstatus": ["<", 2]},
		pluck="name",
	)


def _active_delivery_notes_for_so(so):
	if not so:
		return []
	return frappe.get_all(
		"Delivery Note",
		filters={"custom_sales_order_id": so, "docstatus": ["<", 2], "is_return": 0},
		pluck="name",
	)


def _active_delivery_notes_for_pick_list(pl):
	if not pl:
		return []
	rows = frappe.get_all(
		"Delivery Note Item",
		filters={"against_pick_list": pl, "docstatus": ["<", 2]},
		fields=["parent"],
	)
	return list({r.parent for r in rows})


# ---------------------------------------------------------------------------
# Pick List status derivation
# ---------------------------------------------------------------------------

def _all_items_picked(doc):
	"""True when every location row has a picked qty and (for batched items) a
	batch — i.e. picking is complete and stickers can be printed."""
	rows = doc.get("locations") or []
	if not rows:
		return False
	for row in rows:
		if not flt(row.get("qty")):
			return False
		if row.get("item_code") and frappe.db.get_value("Item", row.item_code, "has_batch_no"):
			if not row.get("batch_no"):
				return False
	return True


def _compute_pick_list_status(doc):
	if doc.docstatus == 2:
		return PL_CANCELLED
	if doc.docstatus == 1:
		# Submitted: dispatched once a linked DN is submitted, else ready.
		dn_submitted = frappe.get_all(
			"Delivery Note Item",
			filters={"against_pick_list": doc.name, "docstatus": 1},
			limit=1,
		)
		return PL_DISPATCHED if dn_submitted else PL_READY
	# Draft progression (most-advanced first). Note: this app pre-fills picked
	# qty from the SO at PL creation, so "all items picked" can be true before
	# any picking happens — we therefore gate the picked states behind the
	# picker explicitly starting (custom_picking_started), matching the spec's
	# Draft -> Picking Pending -> Picking In Progress -> Sticker Pending flow.
	if doc.get("custom_sticker_printed"):
		return PL_SUBMISSION_PENDING
	if doc.get("custom_picking_started"):
		return PL_STICKER_PENDING if _all_items_picked(doc) else PL_PICKING
	if doc.get("custom_assigned_to") and doc.get("custom_transporter"):
		return PL_PICKING_PENDING
	return PL_DRAFT


def _apply_pick_list_status(doc):
	status = _compute_pick_list_status(doc)
	if doc.get("custom_workflow_status") != status:
		doc.db_set("custom_workflow_status", status, update_modified=False)
	return status


def _sync_so_from_pick_list(so, pl_status):
	"""Reflect Pick List progress onto the Sales Order, without regressing the
	SO past stages it has already moved beyond (DN created / dispatched / etc.)."""
	if not so:
		return
	cur = frappe.db.get_value("Sales Order", so, "custom_workflow_status")
	if cur not in SO_EARLY_STAGES:
		return
	if pl_status in PL_ACTIVE_STAGES:
		_set_status("Sales Order", so, SO_PICKING)
	else:
		_set_status("Sales Order", so, SO_WAREHOUSE_APPROVED)


# ---------------------------------------------------------------------------
# Sales Order events
# ---------------------------------------------------------------------------

def sales_order_validate(doc, method=None):
	if doc.docstatus == 0 and not doc.get("custom_workflow_status"):
		doc.custom_workflow_status = SO_DRAFT


def sales_order_on_submit(doc, method=None):
	# Submitting the SO drops it into the warehouse queue.
	doc.db_set("custom_workflow_status", SO_WAREHOUSE_PENDING, update_modified=False)
	_notify(lambda: _notify_so_submitted(doc))


def sales_order_on_cancel(doc, method=None):
	_guard_sales_order_cancellation(doc)
	doc.db_set("custom_workflow_status", SO_CANCELLED, update_modified=False)


def _guard_sales_order_cancellation(doc):
	if _active_delivery_notes_for_so(doc.name):
		frappe.throw(
			frappe._(
				"Sales Order cannot be cancelled because a linked Delivery Note exists. "
				"Please cancel the Delivery Note and Pick List first."
			)
		)
	if _active_pick_lists_for_so(doc.name):
		frappe.throw(
			frappe._(
				"Sales Order cannot be cancelled because a linked Pick List exists. "
				"Please cancel the Pick List first."
			)
		)


# ---------------------------------------------------------------------------
# Pick List events
# ---------------------------------------------------------------------------

def pick_list_after_insert(doc, method=None):
	# A Pick List existing == warehouse approved the order.
	so = _so_of_pick_list(doc)
	_set_status("Sales Order", so, SO_WAREHOUSE_APPROVED)
	status = _apply_pick_list_status(doc)
	_sync_so_from_pick_list(so, status)


def pick_list_on_update(doc, method=None):
	if doc.docstatus != 0:
		return
	status = _apply_pick_list_status(doc)
	_sync_so_from_pick_list(_so_of_pick_list(doc), status)


def pick_list_on_submit(doc, method=None):
	doc.db_set("custom_workflow_status", PL_READY, update_modified=False)
	_set_status("Sales Order", _so_of_pick_list(doc), SO_READY)
	_notify(lambda: _notify_pl_submitted(doc))


def pick_list_on_cancel(doc, method=None):
	_guard_pick_list_cancellation(doc)
	doc.db_set("custom_workflow_status", PL_CANCELLED, update_modified=False)
	# Reservation released — SO returns to the warehouse queue for a fresh PL.
	_set_status("Sales Order", _so_of_pick_list(doc), SO_WAREHOUSE_PENDING)


def _guard_pick_list_cancellation(doc):
	if _active_delivery_notes_for_pick_list(doc.name):
		frappe.throw(
			frappe._(
				"Pick List cannot be cancelled because a linked Delivery Note exists. "
				"Please cancel the Delivery Note first."
			)
		)


# ---------------------------------------------------------------------------
# Delivery Note events
# ---------------------------------------------------------------------------

def delivery_note_after_insert(doc, method=None):
	if doc.get("is_return"):
		return
	_set_status("Sales Order", _so_of_delivery_note(doc), SO_DN_CREATED)


def delivery_note_on_submit(doc, method=None):
	if doc.get("is_return"):
		return
	pl = _pick_list_of_delivery_note(doc)
	if pl:
		_set_status("Pick List", pl, PL_DISPATCHED)
	_set_status("Sales Order", _so_of_delivery_note(doc), SO_DISPATCHED)
	_notify(lambda: _notify_dn_dispatched(doc))


def delivery_note_on_cancel(doc, method=None):
	if doc.get("is_return"):
		return
	pl = _pick_list_of_delivery_note(doc)
	if pl and frappe.db.get_value("Pick List", pl, "docstatus") == 1:
		_set_status("Pick List", pl, PL_READY)
	so = _so_of_delivery_note(doc)
	if so and frappe.db.get_value("Sales Order", so, "custom_workflow_status") != SO_CANCELLED:
		_set_status("Sales Order", so, SO_READY)


# ---------------------------------------------------------------------------
# User actions (no document event to hang off)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def submit_sales_order(sales_order):
	"""Submit a draft Sales Order -> Warehouse Approval Pending.

	Used by the 'Send for Warehouse Approval' button on the Sales Order view
	page (the page now saves new orders as Draft, then this advances them)."""
	doc = frappe.get_doc("Sales Order", sales_order)
	if doc.docstatus != 0:
		frappe.throw(frappe._("This Sales Order is already submitted."))
	# Frappe enforces the submit permission inside doc.submit().
	doc.submit()
	return frappe.db.get_value("Sales Order", sales_order, "custom_workflow_status")


@frappe.whitelist()
def mark_future_dispatch(sales_order, expected_date):
	"""Warehouse parks an order awaiting stock, with an expected dispatch date."""
	_require_roles(WAREHOUSE_ROLES)
	if not expected_date:
		frappe.throw(frappe._("Expected Dispatch Date is mandatory for Future Dispatch."))
	cur = frappe.db.get_value("Sales Order", sales_order, "custom_workflow_status")
	if cur not in (SO_WAREHOUSE_PENDING, SO_FUTURE_DISPATCH):
		frappe.throw(frappe._("Future Dispatch can only be set while the order is awaiting warehouse approval."))
	if _active_pick_lists_for_so(sales_order):
		frappe.throw(frappe._("A Pick List already exists for this order; it cannot be moved to Future Dispatch."))
	frappe.db.set_value(
		"Sales Order",
		sales_order,
		{"custom_workflow_status": SO_FUTURE_DISPATCH, "custom_expected_dispatch_date": expected_date},
		update_modified=False,
	)
	frappe.db.commit()
	return SO_FUTURE_DISPATCH


@frappe.whitelist()
def mark_delivered(sales_order):
	"""Sales confirms the customer received the order -> Completed (final)."""
	_require_roles(SALES_ROLES)
	cur = frappe.db.get_value("Sales Order", sales_order, "custom_workflow_status")
	if cur != SO_DISPATCHED:
		frappe.throw(frappe._("Only a Dispatched order can be marked Completed."))
	frappe.db.set_value(
		"Sales Order",
		sales_order,
		{"custom_workflow_status": SO_COMPLETED, "custom_delivered_on": today()},
		update_modified=False,
	)
	frappe.db.commit()
	return SO_COMPLETED


@frappe.whitelist()
def start_picking(pick_list):
	"""Assigned picker starts collecting items -> Picking In Progress."""
	_require_roles(PICKER_ROLES)
	doc = frappe.get_doc("Pick List", pick_list)
	if doc.docstatus != 0:
		frappe.throw(frappe._("Picking can only start on a draft Pick List."))
	if not doc.get("custom_assigned_to"):
		frappe.throw(frappe._("Please assign a Picker before starting picking."))
	if not doc.get("custom_transporter"):
		frappe.throw(frappe._("Please assign a Transporter before starting picking."))
	frappe.db.set_value("Pick List", pick_list, "custom_picking_started", 1, update_modified=False)
	doc.reload()
	status = _apply_pick_list_status(doc)
	_sync_so_from_pick_list(_so_of_pick_list(doc), status)
	frappe.db.commit()
	return status


def mark_sticker_printed(pick_list):
	"""Flip the sticker-printed flag and advance to Submission Pending. Called
	from the sticker-generation endpoint (not whitelisted directly)."""
	if frappe.db.get_value("Pick List", pick_list, "docstatus") != 0:
		return
	if frappe.db.get_value("Pick List", pick_list, "custom_sticker_printed"):
		return
	frappe.db.set_value("Pick List", pick_list, "custom_sticker_printed", 1, update_modified=False)
	doc = frappe.get_doc("Pick List", pick_list)
	status = _apply_pick_list_status(doc)
	_sync_so_from_pick_list(_so_of_pick_list(doc), status)


# ---------------------------------------------------------------------------
# Notifications (defensive — must never block the workflow)
# ---------------------------------------------------------------------------

def _notify(fn):
	try:
		fn()
	except Exception:
		frappe.log_error(title="Workflow notification failed", message=frappe.get_traceback())


def _dm_roles(roles, text, doc=None):
	from alpinos.raven_notifications import _get_bot, _role_users, _send_dm

	bot = _get_bot()
	if not bot:
		return
	seen = set()
	for role in roles:
		for user in _role_users(role) or []:
			if user in seen:
				continue
			seen.add(user)
			_send_dm(bot, user, text, doc)


def _notify_so_submitted(doc):
	_dm_roles(
		["Warehouse Admin", "Warehouse Manager"],
		frappe._("New Sales Order {0} submitted. Please review.").format(doc.name),
		doc,
	)


def _notify_pl_submitted(doc):
	_dm_roles(
		["Sales Admin", "Sales Manager"],
		frappe._("Pick List {0} submitted. Ready for dispatch.").format(doc.name),
		doc,
	)


def _notify_dn_dispatched(doc):
	lr = doc.get("custom_lr_gr_no") or ""
	transporter = doc.get("custom_transporter_name") or ""
	so = _so_of_delivery_note(doc) or ""
	_dm_roles(
		["Sales Admin", "Sales Manager"],
		frappe._("Order {0} dispatched. LR/AWB: {1}. Transporter: {2}.").format(so, lr, transporter),
		doc,
	)


# ---------------------------------------------------------------------------
# Backfill — bring existing documents up to a correct workflow status
# ---------------------------------------------------------------------------

def _recompute_so_status(so):
	"""Derive a Sales Order's workflow status purely from its current docstatus
	and linked Pick List / Delivery Note state. Used for backfill and migrate."""
	ds = frappe.db.get_value("Sales Order", so, "docstatus")
	if ds == 2:
		return SO_CANCELLED
	if ds == 0:
		return SO_DRAFT

	cur = frappe.db.get_value("Sales Order", so, "custom_workflow_status")

	if frappe.get_all("Delivery Note", filters={"custom_sales_order_id": so, "docstatus": 1, "is_return": 0}, limit=1):
		# Preserve a manually-confirmed Completed; otherwise it's Dispatched.
		return SO_COMPLETED if cur == SO_COMPLETED else SO_DISPATCHED
	if frappe.get_all("Delivery Note", filters={"custom_sales_order_id": so, "docstatus": 0, "is_return": 0}, limit=1):
		return SO_DN_CREATED
	if frappe.get_all("Pick List", filters={"custom_sales_order_id": so, "docstatus": 1}, limit=1):
		return SO_READY
	draft_pls = frappe.get_all("Pick List", filters={"custom_sales_order_id": so, "docstatus": 0}, pluck="name")
	if draft_pls:
		statuses = [frappe.db.get_value("Pick List", p, "custom_workflow_status") for p in draft_pls]
		if any(s in PL_ACTIVE_STAGES for s in statuses):
			return SO_PICKING
		return SO_WAREHOUSE_APPROVED
	# Submitted with no Pick List yet.
	return SO_FUTURE_DISPATCH if cur == SO_FUTURE_DISPATCH else SO_WAREHOUSE_PENDING


def backfill_workflow_statuses():
	"""Recompute workflow status for every existing Pick List and Sales Order.
	Idempotent; safe to run on every migrate. Pick Lists first so the Sales
	Order derivation reads fresh PL statuses."""
	for pl in frappe.get_all("Pick List", pluck="name"):
		doc = frappe.get_doc("Pick List", pl)
		_set_status("Pick List", pl, _compute_pick_list_status(doc))
	for so in frappe.get_all("Sales Order", pluck="name"):
		_set_status("Sales Order", so, _recompute_so_status(so))
	frappe.db.commit()
