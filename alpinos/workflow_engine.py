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
from frappe.utils import flt, getdate, today


# --- SO / PL status vocab ---------------------------------------------------

SO_DRAFT = "Draft"
SO_WAREHOUSE_PENDING = "Warehouse Approval Pending"
SO_FUTURE_DISPATCH = "Future Dispatch"
SO_TODAYS_DISPATCH = "Today's Dispatch"
SO_WAREHOUSE_APPROVED = "Warehouse Approved"
SO_PICKING = "Picking In Progress"
SO_STICKER_PENDING = "Sticker Pending"
SO_SUBMISSION_PENDING = "Submission Pending"
SO_READY = "Ready For Dispatch"
SO_DN_CREATED = "Delivery Note Created"
SO_DISPATCHED = "Dispatched"
SO_PARTIAL_READY = "Partial Ready For Dispatch"
SO_PARTIAL_DN_CREATED = "Partial Delivery Note Created"
SO_PARTIAL_DISPATCHED = "Partial Dispatched"
SO_FORCED_READY = "Forced Ready For Dispatch"
SO_FORCED_DN_CREATED = "Forced Delivery Note Created"
SO_FORCED_DISPATCHED = "Forced Dispatched"
SO_FORCED_COMPLETED = "Forced Completed"
SO_COMPLETED = "Completed"
SO_CANCELLED = "Cancelled"

# SO stages that may still be steered by Pick List progress (never regress past
# these — once a DN exists or the order is dispatched, PL edits must not pull it
# backwards).
SO_EARLY_STAGES = {
	SO_WAREHOUSE_PENDING,
	SO_FUTURE_DISPATCH,
	SO_TODAYS_DISPATCH,
	SO_WAREHOUSE_APPROVED,
	SO_PICKING,
	SO_STICKER_PENDING,
	SO_SUBMISSION_PENDING,
}

PL_DRAFT = "Draft"
PL_PICKING_PENDING = "Picking Pending"
PL_PICKING = "Picking In Progress"
PL_STICKER_PENDING = "Sticker Pending"
PL_SUBMISSION_PENDING = "Submission Pending"
PL_READY = "Ready To Dispatch"
PL_PARTIAL_READY = "Partial Ready To Dispatch"
PL_FORCED_READY = "Forced Ready To Dispatch"
PL_DISPATCHED = "Dispatched"
PL_CANCELLED = "Cancelled"

# PL stages that mean "actively being worked" -> the Sales Order mirrors them.
PL_ACTIVE_STAGES = {PL_PICKING, PL_STICKER_PENDING, PL_SUBMISSION_PENDING}

# A Pick List picking stage -> the Sales Order status it should reflect.
# Note: "Sticker Pending" is a Pick-List-only stage; while the PL is at Sticker
# Pending the Sales Order stays at "Picking In Progress".
PL_TO_SO_STATUS = {
	PL_PICKING: SO_PICKING,
	PL_STICKER_PENDING: SO_PICKING,
	PL_SUBMISSION_PENDING: SO_SUBMISSION_PENDING,
}

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


def refresh_todays_dispatch():
	"""Daily scheduled job: flip APPROVED, future-dated Sales Orders to "Today's
	Dispatch" on the day their dispatch date arrives. Only Future Dispatch orders
	are flipped — Warehouse Approval Pending is a manual gate (approve_sales_order)
	and must never be auto-approved by this job."""
	rows = frappe.get_all(
		"Sales Order",
		filters={
			"docstatus": 1,
			"custom_workflow_status": SO_FUTURE_DISPATCH,
		},
		fields=["name", "custom_dispatch_date"],
	)
	flipped = 0
	for so in rows:
		dd = so.get("custom_dispatch_date")
		if dd and getdate(dd) <= getdate(today()):
			_set_status("Sales Order", so.name, SO_TODAYS_DISPATCH)
			flipped += 1
	frappe.db.commit()
	return flipped


# ---------------------------------------------------------------------------
# Sales Order events
# ---------------------------------------------------------------------------

def sales_order_validate(doc, method=None):
	if doc.docstatus == 0 and not doc.get("custom_workflow_status"):
		doc.custom_workflow_status = SO_DRAFT


def sales_order_on_submit(doc, method=None):
	# "Send for Warehouse Approval" always lands in Warehouse Approval Pending —
	# the approval stage must never be skipped. The date-driven Today's Dispatch
	# transition happens afterwards via refresh_todays_dispatch (the daily job
	# flips due-today orders forward), so it's the stage after, not instead.
	doc.db_set("custom_workflow_status", SO_WAREHOUSE_PENDING, update_modified=False)
	from alpinos import so_notifications as son
	_notify(lambda: son.n01_so_submitted(doc))


def sales_order_on_cancel(doc, method=None):
	_guard_sales_order_cancellation(doc)
	doc.db_set("custom_workflow_status", SO_CANCELLED, update_modified=False)


_ENTRY_PAGE_ROUTES = {
	"Sales Order": "sales-order-entry-view",
	"Pick List": "pick_list_entry",
	"Delivery Note": "delivery_note_entry",
}


def _linked_doc_refs(doctype, names):
	"""Linked-document IDs for cancellation guard messages. Rendered as links
	to the doctype's entry page only when the current user may read that
	doctype — otherwise plain IDs, so users without access see the ID but
	cannot navigate to it."""
	if frappe.has_permission(doctype, "read"):
		route = _ENTRY_PAGE_ROUTES[doctype]
		return ", ".join(
			f'<a href="/app/{route}/{frappe.utils.quote(n)}">{frappe.utils.escape_html(n)}</a>'
			for n in names
		)
	return ", ".join(frappe.utils.escape_html(n) for n in names)


def _guard_sales_order_cancellation(doc):
	dns = _active_delivery_notes_for_so(doc.name)
	if dns:
		frappe.throw(
			frappe._(
				"Sales Order cannot be cancelled because linked Delivery Note {0} exists. "
				"Please cancel the Delivery Note (and Pick List) first."
			).format(_linked_doc_refs("Delivery Note", dns))
		)
	pls = _active_pick_lists_for_so(doc.name)
	if pls:
		frappe.throw(
			frappe._(
				"Sales Order cannot be cancelled because linked Pick List {0} exists. "
				"Please cancel the Pick List first."
			).format(_linked_doc_refs("Pick List", pls))
		)


# ---------------------------------------------------------------------------
# Pick List events
# ---------------------------------------------------------------------------

def _sync_so_from_pick_list(so, pl_status):
	"""Mirror the Pick List's picking stage onto the Sales Order:
	Picking In Progress / Sticker Pending / Submission Pending. A Draft or
	Picking Pending PL leaves the SO at its date-driven status (Today's
	Dispatch / Warehouse queue). Never regress past Ready For Dispatch."""
	if not so:
		return
	cur = frappe.db.get_value("Sales Order", so, "custom_workflow_status")
	if cur not in SO_EARLY_STAGES:
		return
	target = PL_TO_SO_STATUS.get(pl_status)
	if target:
		_set_status("Sales Order", so, target)


def pick_list_after_insert(doc, method=None):
	from alpinos import so_notifications as son

	so = _so_of_pick_list(doc)
	prev_so = frappe.db.get_value("Sales Order", so, "custom_workflow_status") if so else None
	# Set the Pick List's own status; mirror any active picking stage onto the SO.
	status = _apply_pick_list_status(doc)
	_sync_so_from_pick_list(so, status)
	if so:
		if prev_so == SO_FUTURE_DISPATCH:
			_notify(lambda: son.n05_pl_from_future_dispatch(so, doc.name))
		else:
			_notify(lambda: son.n03_pl_created(so, doc.name))
	if doc.get("custom_assigned_to"):
		_notify(lambda: son.n06_pl_assigned(doc))


def pick_list_on_update(doc, method=None):
	if doc.docstatus != 0:
		return
	from alpinos import so_notifications as son

	old_status = doc.get("custom_workflow_status")
	status = _apply_pick_list_status(doc)
	_sync_so_from_pick_list(_so_of_pick_list(doc), status)
	if status != old_status:
		if status == PL_STICKER_PENDING:
			_notify(lambda: son.n07_sticker_pending(doc))
		elif status == PL_SUBMISSION_PENDING:
			_notify(lambda: son.n08_submission_pending(doc))
	# Assignment notice: only on a real re-assignment of an EXISTING doc.
	# On insert, has_value_changed() is True (no prior value) and
	# pick_list_after_insert already fires n06 — guard against the double-send.
	if (
		doc.get_doc_before_save()
		and doc.has_value_changed("custom_assigned_to")
		and doc.get("custom_assigned_to")
	):
		_notify(lambda: son.n06_pl_assigned(doc))


def pick_list_on_submit(doc, method=None):
	from alpinos import partial_dispatch as pd
	from alpinos.forced_close import is_force_closed

	so = _so_of_pick_list(doc)
	if so and is_force_closed(so):
		doc.db_set("custom_workflow_status", PL_FORCED_READY, update_modified=False)
		_set_status("Sales Order", so, SO_FORCED_READY)
	# Partial order still short of full coverage -> partial ready statuses.
	elif so and pd.is_partial_round(so):
		doc.db_set("custom_workflow_status", PL_PARTIAL_READY, update_modified=False)
		_set_status("Sales Order", so, SO_PARTIAL_READY)
	else:
		doc.db_set("custom_workflow_status", PL_READY, update_modified=False)
		_set_status("Sales Order", so, SO_READY)
	from alpinos import so_notifications as son
	_notify(lambda: son.n09_pl_submitted(doc, so))


def pick_list_on_cancel(doc, method=None):
	_guard_pick_list_cancellation(doc)
	doc.db_set("custom_workflow_status", PL_CANCELLED, update_modified=False)
	# Reservation released — recompute the SO back to its date-driven queue.
	so = _so_of_pick_list(doc)
	if so:
		_set_status("Sales Order", so, _recompute_so_status(so))


def _guard_pick_list_cancellation(doc):
	dns = _active_delivery_notes_for_pick_list(doc.name)
	if dns:
		frappe.throw(
			frappe._(
				"Pick List cannot be cancelled because linked Delivery Note {0} exists. "
				"Please cancel the Delivery Note first."
			).format(_linked_doc_refs("Delivery Note", dns))
		)


# ---------------------------------------------------------------------------
# Delivery Note events
# ---------------------------------------------------------------------------

def delivery_note_after_insert(doc, method=None):
	if doc.get("is_return"):
		return
	from alpinos import partial_dispatch as pd
	from alpinos.forced_close import is_force_closed

	so = _so_of_delivery_note(doc)
	if so and is_force_closed(so):
		_set_status("Sales Order", so, SO_FORCED_DN_CREATED)
	elif so and pd.is_partial_round(so):
		_set_status("Sales Order", so, SO_PARTIAL_DN_CREATED)
	else:
		_set_status("Sales Order", so, SO_DN_CREATED)


def delivery_note_on_submit(doc, method=None):
	if doc.get("is_return"):
		return
	from alpinos import partial_dispatch as pd
	from alpinos.forced_close import is_force_closed

	from alpinos import so_notifications as son

	pl = _pick_list_of_delivery_note(doc)
	if pl:
		_set_status("Pick List", pl, PL_DISPATCHED)
	so = _so_of_delivery_note(doc)
	if so:
		if is_force_closed(so):
			# Forced chain: dispatch what's picked, order stays locked until Sales confirms.
			_set_status("Sales Order", so, SO_FORCED_DISPATCHED)
			_notify(lambda: son.n18_forced_dn_submitted(so, doc))
		elif pd.is_partial_order(so):
			# Auto-complete once cumulative dispatched covers the full order;
			# otherwise the order stays in the partial chain (no Partial Completed).
			if pd.so_fully_dispatched(so):
				_set_status("Sales Order", so, SO_COMPLETED)
				_notify(lambda: son.n16_auto_completed(so, doc))
			else:
				_set_status("Sales Order", so, SO_PARTIAL_DISPATCHED)
				_notify(lambda: son.n15_partial_dn_submitted(so, doc))
		else:
			_set_status("Sales Order", so, SO_DISPATCHED)
			_notify(lambda: son.n11_dn_dispatched(doc, so))


def delivery_note_on_cancel(doc, method=None):
	if doc.get("is_return"):
		return
	from alpinos import partial_dispatch as pd

	so = _so_of_delivery_note(doc)
	partial = bool(so and pd.is_partial_round(so))
	pl = _pick_list_of_delivery_note(doc)
	if pl and frappe.db.get_value("Pick List", pl, "docstatus") == 1:
		_set_status("Pick List", pl, PL_PARTIAL_READY if partial else PL_READY)
	if so and frappe.db.get_value("Sales Order", so, "custom_workflow_status") != SO_CANCELLED:
		_set_status("Sales Order", so, _recompute_so_status(so))


# ---------------------------------------------------------------------------
# User actions (no document event to hang off)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def cancel_document(doctype, name):
	"""Cancel a Sales Order / Pick List / Delivery Note from its entry page.

	Requires cancel permission on the doctype (the page only shows the button
	when the user has it; this is the server-side enforcement). Cancellation
	guards run via on_cancel and block with the linked document's ID when a
	downstream document is still active."""
	if doctype not in _ENTRY_PAGE_ROUTES:
		frappe.throw(frappe._("Cancellation is not supported for {0}.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(frappe._("Only submitted documents can be cancelled."))
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus}


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
def approve_sales_order(sales_order):
	"""Warehouse approves an order pending approval -> it enters the dispatch queue:
	Today's Dispatch if the dispatch date is due (<= today), else Future Dispatch."""
	_require_roles(WAREHOUSE_ROLES)
	cur = frappe.db.get_value("Sales Order", sales_order, "custom_workflow_status")
	if cur != SO_WAREHOUSE_PENDING:
		frappe.throw(frappe._("Only an order Pending Warehouse Approval can be approved."))
	dd = frappe.db.get_value("Sales Order", sales_order, "custom_dispatch_date")
	new_status = SO_TODAYS_DISPATCH if (dd and getdate(dd) <= getdate(today())) else SO_FUTURE_DISPATCH
	_set_status("Sales Order", sales_order, new_status)
	frappe.db.commit()
	return {"status": new_status}


@frappe.whitelist()
def mark_future_dispatch(sales_order, expected_date):
	"""Warehouse parks an order awaiting stock, with an expected dispatch date."""
	_require_roles(WAREHOUSE_ROLES)
	if not expected_date:
		frappe.throw(frappe._("Expected Dispatch Date is mandatory for Future Dispatch."))
	cur = frappe.db.get_value("Sales Order", sales_order, "custom_workflow_status")
	# Allowed while the order is still in the warehouse queue (a submitted Pick
	# List moves the SO to Ready For Dispatch, which is not in this set, so it's
	# naturally blocked). A *draft* Pick List is fine — we re-sync its date below.
	if cur not in (SO_WAREHOUSE_PENDING, SO_FUTURE_DISPATCH, SO_TODAYS_DISPATCH):
		frappe.throw(frappe._("The dispatch date can only be changed while the order is awaiting warehouse dispatch."))
	# Picking today -> "Today's Dispatch"; a future date -> "Future Dispatch".
	new_status = SO_TODAYS_DISPATCH if getdate(expected_date) == getdate(today()) else SO_FUTURE_DISPATCH
	# Move the visible Dispatch Date to the chosen date too (and record it as the
	# expected dispatch date), so the order reschedules to when it will go out.
	frappe.db.set_value(
		"Sales Order",
		sales_order,
		{
			"custom_workflow_status": new_status,
			"custom_expected_dispatch_date": expected_date,
			"custom_dispatch_date": expected_date,
		},
		update_modified=False,
	)
	# Keep any linked draft Pick List's dispatch date in sync with the order.
	for pl in _active_pick_lists_for_so(sales_order):
		if frappe.db.get_value("Pick List", pl, "docstatus") == 0:
			frappe.db.set_value("Pick List", pl, "custom_dispatch_date", expected_date, update_modified=False)
	frappe.db.commit()
	if new_status == SO_FUTURE_DISPATCH:
		from alpinos import so_notifications as son
		_notify(lambda: son.n04_future_dispatch(sales_order))
	return new_status


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
	from alpinos import so_notifications as son
	_notify(lambda: son.n12_completed(sales_order))
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


@frappe.whitelist()
def stop_picking(pick_list):
	"""Picker presses Stop at the sticker-generation point -> Submission Pending
	(picking finished; the Pick List is now ready to submit)."""
	_require_roles(PICKER_ROLES)
	if frappe.db.get_value("Pick List", pick_list, "docstatus") != 0:
		frappe.throw(frappe._("Picking can only be stopped on a draft Pick List."))
	if not frappe.db.get_value("Pick List", pick_list, "custom_picking_started"):
		frappe.throw(frappe._("Start picking before stopping."))
	mark_sticker_printed(pick_list)  # sets the flag -> Submission Pending
	frappe.db.commit()
	return frappe.db.get_value("Pick List", pick_list, "custom_workflow_status")


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

	# Force-closed orders are locked to their forced terminal state.
	if frappe.db.get_value("Sales Order", so, "custom_force_closed"):
		return cur if cur in (SO_FORCED_DISPATCHED, SO_FORCED_COMPLETED) else SO_FORCED_COMPLETED

	from alpinos import partial_dispatch as pd
	partial = pd.is_partial_order(so)

	if frappe.get_all("Delivery Note", filters={"custom_sales_order_id": so, "docstatus": 1, "is_return": 0}, limit=1):
		if partial:
			# Auto-complete when fully dispatched, else stay in the partial chain.
			return SO_COMPLETED if pd.so_fully_dispatched(so) else SO_PARTIAL_DISPATCHED
		# Preserve a manually-confirmed Completed; otherwise it's Dispatched.
		return SO_COMPLETED if cur == SO_COMPLETED else SO_DISPATCHED
	if frappe.get_all("Delivery Note", filters={"custom_sales_order_id": so, "docstatus": 0, "is_return": 0}, limit=1):
		return SO_PARTIAL_DN_CREATED if pd.is_partial_round(so) else SO_DN_CREATED
	if frappe.get_all("Pick List", filters={"custom_sales_order_id": so, "docstatus": 1}, limit=1):
		return SO_PARTIAL_READY if pd.is_partial_round(so) else SO_READY
	# A draft Pick List that is being picked mirrors its stage onto the SO.
	draft_pls = frappe.get_all("Pick List", filters={"custom_sales_order_id": so, "docstatus": 0}, pluck="name")
	if draft_pls:
		statuses = [frappe.db.get_value("Pick List", p, "custom_workflow_status") for p in draft_pls]
		for stage in (PL_SUBMISSION_PENDING, PL_STICKER_PENDING, PL_PICKING):  # most advanced first
			if stage in statuses:
				return PL_TO_SO_STATUS[stage]
	# Otherwise the warehouse-queue status is date-driven:
	# due today (or overdue) -> Today's Dispatch; future -> waiting / parked.
	dd = frappe.db.get_value("Sales Order", so, "custom_dispatch_date")
	if dd and getdate(dd) <= getdate(today()):
		return SO_TODAYS_DISPATCH
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
