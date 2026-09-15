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
				# BRD 2.3.1 lists item-level Remarks; Purchase Order Item has no such
				# field of its own (description holds the item description).
				fieldname="custom_item_remarks",
				label="Remarks",
				fieldtype="Data",
				insert_after="description",
				description="Line-level remarks for this order line.",
			),
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


def validate_items_match_po_type(doc, method=None):
	"""The PO Type must be the type of the goods on the order.

	A Purchase Inward takes its Inward Type from the order and only offers the lines of that
	type (inward_api.get_purchase_order_items), so an order typed PM carrying Finished Goods
	opened an inward with no lines and "N Purchase Order line(s) were not offered". The FG
	batch rule and the FG internal-batch format also key off the type, so receiving them as PM
	was never right either. An item whose group maps to no type is allowed on any order.

	A Direct Purchase Invoice order never reaches an inward, so its type decides nothing.
	"""
	if cint(doc.get("custom_direct_purchase_invoice")) or not doc.get("custom_inward_type"):
		return
	from alpinos.purchase.inward_api import item_inward_type

	wanted = doc.custom_inward_type
	cache = {}
	wrong = {}
	matching = False
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		found = item_inward_type(row.item_code, cache)
		if found == wanted:
			matching = True
		elif found:
			wrong.setdefault(found, [])
			if row.item_code not in wrong[found]:
				wrong[found].append(row.item_code)
	if not wrong:
		return

	lines = "".join(
		"<li>{0}: {1}</li>".format(frappe.bold(C.label_for_inward_type(code)), ", ".join(items))
		for code, items in wrong.items()
	)
	# One other type and nothing of the chosen one: the PO Type was simply picked wrong.
	hint = (
		frappe._("Set PO Type to {0}.").format(frappe.bold(next(iter(wrong))))
		if len(wrong) == 1 and not matching
		else frappe._("Raise a separate Purchase Order for each type.")
	)
	frappe.throw(
		frappe._("PO Type is {0}, but these items belong to another type:<ul>{1}</ul>{2}").format(
			frappe.bold(C.label_for_inward_type(wanted)), lines, hint
		),
		title=frappe._("PO Type Does Not Match the Items"),
	)


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


@frappe.whitelist()
def get_supplier_info(supplier, company=None):
	"""Vendor name, contact and addresses for the Purchase Order entry page (BRD 2.2.2).

	ERPNext's own lookup comes first -- erpnext.accounts.party.get_party_details, the call
	the standard Purchase Order form makes -- but it only returns Addresses and Contacts
	that are LINKED to the supplier through a Dynamic Link. Suppliers on this site often
	carry a Primary Address / Primary Contact that is not linked, so those fields are the
	fallback. The page used to read supplier_primary_address alone and showed the address
	record's NAME ("Billing Address-Billing") as the billing address, with no contact at all.

	Shipping / Delivery is the COMPANY's shipping address: a purchase order is delivered to
	the buyer, so it is not the vendor's address.
	"""
	if not supplier:
		return {}
	frappe.has_permission("Supplier", "read", supplier, throw=True)

	from erpnext.accounts.party import get_party_details
	from frappe.contacts.doctype.address.address import get_address_display

	try:
		details = get_party_details(
			party=supplier, party_type="Supplier", company=company, doctype="Purchase Order"
		) or {}
	except frappe.PermissionError:
		raise
	except Exception:
		# A missing default price list or account must not blank the whole block.
		details = {}

	master = frappe.db.get_value(
		"Supplier",
		supplier,
		["supplier_name", "supplier_primary_address", "supplier_primary_contact", "mobile_no"],
		as_dict=True,
	) or {}

	supplier_address = details.get("supplier_address") or master.get("supplier_primary_address")
	address_display = details.get("address_display") or (
		get_address_display(supplier_address)
		if supplier_address and frappe.db.exists("Address", supplier_address)
		else None
	)

	contact = details.get("contact_person") or master.get("supplier_primary_contact")
	contact_row = (
		frappe.db.get_value("Contact", contact, ["full_name", "mobile_no", "phone"], as_dict=True)
		if contact and frappe.db.exists("Contact", contact)
		else None
	) or {}
	contact_mobile = (
		details.get("contact_mobile")
		or details.get("contact_phone")
		or contact_row.get("mobile_no")
		or contact_row.get("phone")
		or master.get("mobile_no")
	)

	return {
		"supplier_name": master.get("supplier_name") or supplier,
		"contact_person": contact,
		"contact_display": details.get("contact_display") or contact_row.get("full_name") or contact,
		"contact_mobile": contact_mobile,
		"supplier_address": supplier_address,
		"address_display": address_display,
		"shipping_address": details.get("shipping_address"),
		"shipping_address_display": details.get("shipping_address_display"),
	}
