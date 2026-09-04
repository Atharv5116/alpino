"""Purchase Order side of the Purchase Inward module — custom fields, form layout and the
inward-progress rollup (task 285).

BRD "Purchase Inward Part -1": 2.1.1 Header Information, 2.2.2 Supplier Information,
3.5 VAL-PO-*, 3.6 BR-PO-*.

Only what the Purchase Team records while raising the ORDER lives here. The arrival
paperwork (invoice number, gross weight, actual arrival, received quantity) belongs to the
separate `Purchase Inward` doctype, which fetches the planned shipment details off these
fields (BR-PO-15 / BR-PO-17).

Three derived fields are kept on the order itself so the Purchase Order list can show,
filter and sort inward progress without joining the inward tables. `refresh_inward_progress`
owns them; nothing else may write them. They are deliberately NOT ERPNext's `received_qty`
/ `per_received`, which count submitted Purchase Receipts and are overwritten by raw SQL on
every receipt submit or cancel.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint, flt, get_datetime

from alpinos.purchase import constants as C

PO = "Purchase Order"
PO_ITEM = "Purchase Order Item"

# BRD 2.1.1: "If only the date is entered, the default time shall be set to 9:00 AM."
DEFAULT_ARRIVAL_HOUR = 9

# BR-PO-20 .. BR-PO-25. Shown on the checkbox itself so the buyer sees the consequence
# before ticking it, not after the inward is refused (VAL-PO-13).
DIRECT_INVOICE_DESCRIPTION = (
	"Skips Purchase Inward, QC and GRN. The order goes straight to Purchase Invoice and "
	"Payment once approved, and no Purchase Inward can be created against it."
)

# A leading blank keeps a reqd Select from silently defaulting to its first option.
_TYPE_OPTIONS = "\n" + C.select_options(C.INWARD_TYPES)
_STATUS_OPTIONS = "\n" + C.select_options(C.PI_STATUSES)

_PROGRESS_FIELDS = ("custom_inward_status", "custom_total_inward_qty", "custom_pending_inward_qty")


# --------------------------------------------------------------- field surface


def _custom_fields():
	"""The Purchase Order / Purchase Order Item field surface, in form order.

	insert_after chains off `amended_from`, the last field of the standard supplier
	section, so the inward block sits between Supplier and Accounting Dimensions.
	"""
	return {
		PO: [
			dict(
				fieldname="custom_inward_section",
				label="Purchase Inward",
				fieldtype="Section Break",
				insert_after="amended_from",
				collapsible=1,
			),
			dict(
				fieldname="custom_inward_type",
				label="PO Type",
				fieldtype="Select",
				options=_TYPE_OPTIONS,
				insert_after="custom_inward_section",
				reqd=1,
				in_list_view=1,
				in_standard_filter=1,
				description="RM / PM / FG / MM. Drives batch numbering and the QC checklist downstream.",
			),
			dict(
				fieldname="custom_supplier_order_no",
				label="Supplier Order No.",
				fieldtype="Data",
				insert_after="custom_inward_type",
				description="The vendor's own order reference, quoted back on their invoice and challan.",
			),
			dict(
				fieldname="custom_direct_purchase_invoice",
				label="Direct Purchase Invoice",
				fieldtype="Check",
				default="0",
				insert_after="custom_supplier_order_no",
				description=DIRECT_INVOICE_DESCRIPTION,
			),
			dict(
				fieldname="custom_inward_col_1",
				fieldtype="Column Break",
				insert_after="custom_direct_purchase_invoice",
			),
			dict(
				fieldname="custom_inward_attachment",
				label="Attachment",
				fieldtype="Attach",
				insert_after="custom_inward_col_1",
				description="Quotation, commercial offer or approval document (PDF / image).",
			),
			dict(
				fieldname="custom_inward_remarks",
				label="Remarks",
				fieldtype="Small Text",
				insert_after="custom_inward_attachment",
			),
			dict(
				fieldname="custom_planned_shipment_section",
				label="Planned Shipment",
				fieldtype="Section Break",
				insert_after="custom_inward_remarks",
				collapsible=1,
				description=(
					"Planned by the Purchase Team. The Purchase Inward fetches these and the "
					"Store Team records the actual values where they differ."
				),
			),
			dict(
				# Data, not Integer: vehicle-adjacent numbers carry leading zeros, +91 and
				# spaces, all of which an Int silently destroys.
				fieldname="custom_vehicle_no",
				label="Vehicle Number",
				fieldtype="Data",
				insert_after="custom_planned_shipment_section",
			),
			dict(
				fieldname="custom_driver_contact_no",
				label="Driver Contact Number",
				fieldtype="Data",
				insert_after="custom_vehicle_no",
			),
			dict(
				fieldname="custom_shipment_col_1",
				fieldtype="Column Break",
				insert_after="custom_driver_contact_no",
			),
			dict(
				fieldname="custom_estimated_arrival",
				label="Estimated Arrival Date & Time",
				fieldtype="Datetime",
				insert_after="custom_shipment_col_1",
				description="A date entered without a time is treated as 9:00 AM.",
			),
			dict(
				fieldname="custom_inward_progress_section",
				label="Inward Progress",
				fieldtype="Section Break",
				insert_after="custom_estimated_arrival",
				collapsible=1,
				description="Rolled up from the submitted Purchase Inwards raised against this order.",
			),
			dict(
				fieldname="custom_inward_status",
				label="Inward Status",
				fieldtype="Select",
				options=_STATUS_OPTIONS,
				insert_after="custom_inward_progress_section",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				in_list_view=1,
				in_standard_filter=1,
			),
			dict(
				fieldname="custom_progress_col_1",
				fieldtype="Column Break",
				insert_after="custom_inward_status",
			),
			dict(
				fieldname="custom_total_inward_qty",
				label="Total Inward Qty",
				fieldtype="Float",
				insert_after="custom_progress_col_1",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="Cumulative quantity received by submitted Purchase Inwards (BR-PO-08).",
			),
			dict(
				fieldname="custom_pending_inward_qty",
				label="Pending Inward Qty",
				fieldtype="Float",
				insert_after="custom_total_inward_qty",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="Ordered quantity less the cumulative inward quantity (BR-PO-10).",
			),
		],
		PO_ITEM: [
			dict(
				# Core received_qty counts submitted Purchase Receipts and is rewritten by
				# StatusUpdater on every receipt submit/cancel, so the inward figure needs
				# its own column.
				fieldname="custom_inward_received_qty",
				label="Inward Received Qty",
				fieldtype="Float",
				insert_after="received_qty",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				print_hide=1,
				description="Quantity received against this row by submitted Purchase Inwards.",
			),
		],
	}


# ---------------------------------------------------------------- form layout

# Re-asserted every migrate so a Customize Form edit cannot quietly un-collapse the
# block, drop the list columns or strip the checkbox description.
_LAYOUT = (
	(PO, "custom_inward_section", "collapsible", 1, "Check"),
	(PO, "custom_planned_shipment_section", "collapsible", 1, "Check"),
	(PO, "custom_inward_progress_section", "collapsible", 1, "Check"),
	(PO, "custom_direct_purchase_invoice", "description", DIRECT_INVOICE_DESCRIPTION, "Text"),
	(PO, "custom_inward_type", "in_list_view", 1, "Check"),
	(PO, "custom_inward_type", "in_standard_filter", 1, "Check"),
	(PO, "custom_inward_status", "in_list_view", 1, "Check"),
	(PO, "custom_inward_status", "in_standard_filter", 1, "Check"),
	(PO, "custom_inward_status", "allow_on_submit", 1, "Check"),
	(PO, "custom_total_inward_qty", "allow_on_submit", 1, "Check"),
	(PO, "custom_pending_inward_qty", "allow_on_submit", 1, "Check"),
	(PO_ITEM, "custom_inward_received_qty", "allow_on_submit", 1, "Check"),
)


def apply_purchase_order_form_layout():
	"""Property setters for the inward block. Idempotent: make_property_setter upserts."""
	for doctype, fieldname, prop, value, property_type in _LAYOUT:
		if not frappe.get_meta(doctype).has_field(fieldname):
			continue
		make_property_setter(
			doctype,
			fieldname,
			prop,
			value,
			property_type,
			validate_fields_for_doctype=False,
		)


# ---------------------------------------------------------------- entry point


def setup_purchase_order_fields():
	"""Create/refresh the Purchase Order inward fields and their layout. Idempotent."""
	create_custom_fields(_custom_fields(), ignore_validate=True, update=True)
	apply_purchase_order_form_layout()
	frappe.clear_cache(doctype=PO)
	frappe.clear_cache(doctype=PO_ITEM)


def execute():
	"""Alias so the module can also be run as a patch."""
	setup_purchase_order_fields()


# ------------------------------------------------------------ server-side guards


def normalize_estimated_arrival(doc, method=None):
	"""BRD 2.1.1 — a date-only Estimated Arrival defaults to 9:00 AM.

	Frappe hands a date-only entry to the server as midnight, so midnight is the only
	signal available; a genuine midnight arrival has to be entered as 00:01. Client-side
	defaulting alone would not survive an API or import, hence the server guard.
	"""
	value = doc.get("custom_estimated_arrival")
	if not value:
		return
	value = get_datetime(value)
	if value.hour or value.minute or value.second:
		return
	doc.custom_estimated_arrival = value.replace(
		hour=DEFAULT_ARRIVAL_HOUR, minute=0, second=0, microsecond=0
	)


# ------------------------------------------------------------ progress rollup


def _rollup_status(purchase_order, pending_qty):
	"""Inward status to show on the order: the least advanced LIVE inward wins.

	The order is only as far along as its slowest open inward, so that is what the buyer
	needs to see. Blank means nothing has been inwarded yet. "Completed" is downgraded to
	"Pending Material Receipt" while quantity is still due, otherwise a partially received
	order whose first inward finished would read as if the whole PO had landed.
	"""
	statuses = frappe.get_all(
		"Purchase Inward",
		filters={"purchase_order": purchase_order, "docstatus": 1},
		pluck="inward_status",
	)
	live = [s for s in statuses if s and s != C.PI_CANCELLED]
	if not live:
		return ""

	rank = {status: idx for idx, status in enumerate(C.PI_STATUSES)}
	status = min(live, key=lambda s: rank.get(s, len(rank)))
	if status == C.PI_COMPLETED and flt(pending_qty) > 0:
		return C.PI_PENDING_RECEIPT
	return status


def refresh_inward_progress(purchase_order):
	"""Recompute the inward rollup on `purchase_order` from its submitted inwards.

	Call after a Purchase Inward is submitted, edited after submit, or cancelled. Returns
	the new values, or None when there is nothing to update.

	Written with frappe.db.set_value rather than doc.save(): the order is normally
	submitted, and a derived number must never bump the document's modified timestamp and
	collide with a user who has the form open.
	"""
	name = getattr(purchase_order, "name", purchase_order)
	if not name:
		return None
	if not frappe.db.exists("DocType", "Purchase Inward"):
		return None
	if not frappe.get_meta(PO).has_field("custom_inward_status"):
		return None
	if not frappe.get_meta(PO_ITEM).has_field("custom_inward_received_qty"):
		return None

	# Lazily imported: this module is also loaded during a migrate that may not have
	# synced the inward doctype yet.
	from alpinos.alpinos_development.doctype.purchase_inward.purchase_inward import PurchaseInward

	docstatus = frappe.db.get_value(PO, name, "docstatus")
	if docstatus is None or cint(docstatus) == 2:
		return None

	rows = frappe.get_all(
		PO_ITEM,
		filters={"parent": name, "parenttype": PO},
		fields=["name", "qty", "delivered_by_supplier", "custom_inward_received_qty"],
	)
	if not rows:
		return None

	# Drop-ship rows never reach the store: ERPNext already marks them fully received, so
	# counting them would show quantity pending that nobody will ever inward.
	details = [row.name for row in rows if not cint(row.delivered_by_supplier)]
	received = PurchaseInward.received_by_po_detail(name, details) if details else {}

	total = 0.0
	pending = 0.0
	for row in rows:
		got = flt(received.get(row.name))
		if got != flt(row.custom_inward_received_qty):
			frappe.db.set_value(
				PO_ITEM, row.name, "custom_inward_received_qty", got, update_modified=False
			)
		if cint(row.delivered_by_supplier):
			continue
		total += got
		pending += max(flt(row.qty) - got, 0.0)

	total = flt(total, 6)
	pending = flt(pending, 6)
	values = {
		"custom_total_inward_qty": total,
		"custom_pending_inward_qty": pending,
		"custom_inward_status": _rollup_status(name, pending),
	}
	frappe.db.set_value(PO, name, values, update_modified=False)
	return values
