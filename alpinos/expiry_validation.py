"""Soft batch-expiry warnings for Pick List and Delivery Note, driven by Customer Type min_expiry_days."""

import frappe
from frappe.utils import flt, getdate, today


def _resolve_threshold(customer_type):
	if not customer_type:
		return None
	days = frappe.db.get_value(
		"Alpino Customer Type", customer_type, "min_expiry_days"
	)
	days = int(days) if days else 0
	return days or None


def _resolve_customer_type_from_sales_orders(sales_orders):
	"""First non-empty customer_type across the SO names, plus all distinct types seen."""
	seen = []
	for so in sales_orders:
		if not so:
			continue
		ct = frappe.db.get_value(
			"Sales Order", so, "custom_offline_buyer_customer_type"
		)
		if ct and ct not in seen:
			seen.append(ct)
	if not seen:
		return None, []
	return seen[0], seen


def resolve_customer_type_for_pick_list(doc):
	sos = [row.sales_order for row in (doc.locations or [])]
	return _resolve_customer_type_from_sales_orders(sos)


def resolve_customer_type_for_delivery_note(doc):
	sos = [row.against_sales_order for row in (doc.items or [])]
	return _resolve_customer_type_from_sales_orders(sos)


def _check_row(item_label, expiry_date, dispatch_date, threshold):
	"""Return None if OK; otherwise a string describing the violation."""
	if not threshold or not expiry_date:
		return None
	expiry = getdate(expiry_date)
	dispatch = getdate(dispatch_date) if dispatch_date else getdate(today())
	days_remaining = (expiry - dispatch).days
	if days_remaining < threshold:
		return (
			f"{item_label}: only {days_remaining} day(s) remaining to expiry "
			f"(minimum required: {threshold})."
		)
	return None


def _warn_mixed_customer_types(seen):
	if len(seen) > 1:
		frappe.msgprint(
			f"Multiple customer types referenced in this document: "
			f"{', '.join(seen)}. Using <b>{seen[0]}</b> for expiry validation.",
			indicator="orange",
			alert=True,
		)


def validate_expiry_on_pick_list(doc, method=None):
	customer_type, seen = resolve_customer_type_for_pick_list(doc)
	threshold = _resolve_threshold(customer_type)
	if not threshold:
		return
	_warn_mixed_customer_types(seen)
	violations = []
	dispatch_date = doc.get("custom_dispatch_date")
	for row in doc.locations or []:
		msg = _check_row(
			f"Row #{row.idx} ({row.item_code})",
			row.get("custom_expiry_date"),
			dispatch_date,
			threshold,
		)
		if msg:
			violations.append(msg)
	if violations:
		frappe.msgprint(
			"<b>Batch Expiry Warning</b> (customer type: "
			f"<b>{customer_type}</b>):<br>" + "<br>".join(violations),
			indicator="orange",
			title="Expiry Below Threshold",
		)


def validate_expiry_on_delivery_note(doc, method=None):
	customer_type, seen = resolve_customer_type_for_delivery_note(doc)
	threshold = _resolve_threshold(customer_type)
	if not threshold:
		return
	_warn_mixed_customer_types(seen)
	violations = []
	dispatch_raw = doc.get("custom_dispatch_date")
	dispatch_date = getdate(dispatch_raw) if dispatch_raw else getdate(today())
	for row in doc.items or []:
		expiry_raw = row.get("custom_expiry_date")
		if not expiry_raw:
			continue
		msg = _check_row(
			f"Row #{row.idx} ({row.item_code})",
			getdate(expiry_raw),
			dispatch_date,
			threshold,
		)
		if msg:
			violations.append(msg)
	if violations:
		frappe.msgprint(
			"<b>Batch Expiry Warning</b> (customer type: "
			f"<b>{customer_type}</b>):<br>" + "<br>".join(violations),
			indicator="orange",
			title="Expiry Below Threshold",
		)


@frappe.whitelist()
def check_row_expiry_warning(
	expiry_date, sales_order=None, dispatch_date=None, customer_type=None
):
	"""Single-row expiry check used during batch selection in the client."""
	if not customer_type and sales_order:
		customer_type = frappe.db.get_value(
			"Sales Order", sales_order, "custom_offline_buyer_customer_type"
		)
	threshold = _resolve_threshold(customer_type)
	if not threshold or not expiry_date:
		return {"ok": True, "message": "", "threshold": threshold, "days_remaining": None}
	expiry = getdate(expiry_date)
	dispatch = getdate(dispatch_date) if dispatch_date else getdate(today())
	days_remaining = (expiry - dispatch).days
	if days_remaining < threshold:
		return {
			"ok": False,
			"message": (
				f"Batch has only {days_remaining} day(s) remaining; customer type "
				f"{customer_type} requires {threshold}."
			),
			"threshold": threshold,
			"days_remaining": days_remaining,
		}
	return {
		"ok": True,
		"message": "",
		"threshold": threshold,
		"days_remaining": days_remaining,
	}
