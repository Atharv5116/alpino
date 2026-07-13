"""
Forced Close (Workflow 3).

At any point where dispatched qty < ordered qty, the warehouse may permanently close
a Sales Order at whatever has been dispatched — abandoning the remaining qty. Available
on ANY order regardless of the Partial flag. A mandatory reason is captured and logged.

Adaptation to this app's architecture (there is no PL-submission modal): Forced Close is
the alternative to "Create PL for Remaining Qty" — a "Force Close Order" action on the SO
view. Once closed, no new Pick List / Delivery Note can be created (enforced in
partial_dispatch.validate_pick_list_partial).

Status chain: ... -> Forced Dispatched -> Forced Completed (terminal). If nothing was
dispatched, it closes straight to Forced Completed.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import now, today

FORCE_CLOSE_REASONS = ("Damage", "Stock Shortage", "Expiry", "Others")

# Statuses (mirror workflow_engine constants; kept here to avoid an import cycle).
SO_FORCED_DISPATCHED = "Forced Dispatched"
SO_FORCED_COMPLETED = "Forced Completed"
_TERMINAL = {"Completed", "Forced Completed", "Cancelled"}


# ---------------------------------------------------------------------------
# Setup (after_migrate)
# ---------------------------------------------------------------------------
def setup_forced_close_fields():
	custom_fields = {
		"Sales Order": [
			dict(
				fieldname="custom_forced_close_section",
				label="Forced Close",
				fieldtype="Section Break",
				insert_after="custom_partial_order_allowed",
				collapsible=1,
				depends_on="eval:doc.custom_force_closed",
			),
			dict(
				fieldname="custom_force_closed",
				label="Force Closed",
				fieldtype="Check",
				insert_after="custom_forced_close_section",
				read_only=1,
				allow_on_submit=1,
				in_standard_filter=1,
			),
			dict(
				fieldname="custom_force_close_reason",
				label="Force Close Reason",
				fieldtype="Select",
				options="\n" + "\n".join(FORCE_CLOSE_REASONS),
				insert_after="custom_force_closed",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_force_close_col",
				fieldtype="Column Break",
				insert_after="custom_force_close_reason",
			),
			dict(
				fieldname="custom_force_closed_by",
				label="Force Closed By",
				fieldtype="Link",
				options="User",
				insert_after="custom_force_close_col",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_force_closed_on",
				label="Force Closed On",
				fieldtype="Datetime",
				insert_after="custom_force_closed_by",
				read_only=1,
				allow_on_submit=1,
			),
		],
	}
	create_custom_fields(custom_fields, update=True)
	print("✅ Forced Close fields created on Sales Order")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_force_closed(sales_order) -> bool:
	if not sales_order:
		return False
	return bool(frappe.db.get_value("Sales Order", sales_order, "custom_force_closed"))


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
@frappe.whitelist()
def force_close_sales_order(sales_order, reason):
	"""Permanently close a Sales Order at the qty already dispatched."""
	from alpinos import partial_dispatch as pd
	from alpinos.workflow_engine import WAREHOUSE_ROLES, _require_roles, _set_status

	_require_roles(WAREHOUSE_ROLES)
	if not sales_order:
		frappe.throw(_("Sales Order is required."))
	reason = (reason or "").strip()
	if reason not in FORCE_CLOSE_REASONS:
		frappe.throw(_("A valid Force Close reason is required: {0}.").format(", ".join(FORCE_CLOSE_REASONS)))

	so = frappe.get_doc("Sales Order", sales_order)
	cur = so.get("custom_workflow_status")
	if cur in _TERMINAL:
		frappe.throw(_("Order {0} is already in a terminal status ({1}).").format(frappe.bold(sales_order), cur))
	if so.get("custom_force_closed"):
		frappe.throw(_("Order {0} is already Force Closed.").format(frappe.bold(sales_order)))
	if pd.so_fully_dispatched(sales_order):
		frappe.throw(_("Order {0} is fully dispatched — nothing to force close.").format(frappe.bold(sales_order)))

	# An open draft Pick List must be resolved first (submit or cancel).
	if frappe.db.exists("Pick List", {"custom_sales_order_id": sales_order, "docstatus": 0}):
		frappe.throw(_("Submit or cancel the open Pick List before forcing this order closed."))

	dispatched = any(v > 0 for v in pd.dispatched_qty_by_sku(sales_order).values())
	new_status = SO_FORCED_DISPATCHED if dispatched else SO_FORCED_COMPLETED

	frappe.db.set_value(
		"Sales Order", sales_order,
		{
			"custom_force_closed": 1,
			"custom_force_close_reason": reason,
			"custom_force_closed_by": frappe.session.user,
			"custom_force_closed_on": now(),
		},
		update_modified=False,
	)
	_set_status("Sales Order", sales_order, new_status)
	# Audit trail.
	so.add_comment(
		"Comment",
		_("Force Closed by {0}. Reason: {1}. Remaining qty abandoned.").format(
			frappe.session.user, reason
		),
	)
	frappe.db.commit()
	from alpinos import so_notifications as son
	son.safe(lambda: son.n17_forced_close(sales_order, reason))
	return {"status": new_status}


def apply_forced_close_after_pl(sales_order, pick_list, reason):
	"""Force-close chosen in the short-pick modal at PL submission.

	Called AFTER the closing Pick List is submitted (so its own validate never sees
	the lock). Sets the force-close flag and moves PL + SO into the Forced Ready state;
	the Delivery Note flow then drives Forced DN Created -> Forced Dispatched.
	"""
	from alpinos.workflow_engine import PL_FORCED_READY, SO_FORCED_READY, _set_status

	reason = (reason or "").strip()
	if reason not in FORCE_CLOSE_REASONS:
		reason = "Others"
	frappe.db.set_value(
		"Sales Order", sales_order,
		{
			"custom_force_closed": 1,
			"custom_force_close_reason": reason,
			"custom_force_closed_by": frappe.session.user,
			"custom_force_closed_on": now(),
		},
		update_modified=False,
	)
	if pick_list:
		_set_status("Pick List", pick_list, PL_FORCED_READY)
	_set_status("Sales Order", sales_order, SO_FORCED_READY)
	frappe.get_doc("Sales Order", sales_order).add_comment(
		"Comment",
		_("Force Closed at Pick List submission by {0}. Reason: {1}. Remaining qty abandoned.").format(
			frappe.session.user, reason
		),
	)
	from alpinos import so_notifications as son
	son.safe(lambda: son.n17_forced_close(sales_order, reason))


@frappe.whitelist()
def confirm_forced_completion(sales_order):
	"""Sales confirms delivery of a force-dispatched order -> Forced Completed (terminal)."""
	from alpinos.workflow_engine import SALES_ROLES, _require_roles, _set_status

	_require_roles(SALES_ROLES)
	cur = frappe.db.get_value("Sales Order", sales_order, "custom_workflow_status")
	if cur != SO_FORCED_DISPATCHED:
		frappe.throw(_("Only a Force Dispatched order can be marked Forced Completed."))
	_set_status("Sales Order", sales_order, SO_FORCED_COMPLETED)
	frappe.db.set_value("Sales Order", sales_order, "custom_delivered_on", today(), update_modified=False)
	frappe.db.commit()
	return {"status": SO_FORCED_COMPLETED}
