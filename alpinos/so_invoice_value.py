"""Keep a Sales Order's Total Invoice Value in step with its Delivery Notes.

Same basis as the Post Dispatch field: the dispatched (picked) products including GST,
taken from the Delivery Notes raised against the order. An order can be dispatched in
several lots, so the value is the sum of its submitted notes and grows with each one.
Blank until something is dispatched.
"""

import frappe
from frappe.utils import flt


def _dispatched_value(sales_order):
	"""GST-inclusive total of the submitted Delivery Notes for this order."""
	rows = frappe.get_all(
		"Delivery Note",
		filters={"custom_sales_order_id": sales_order, "docstatus": 1, "is_return": 0},
		fields=["grand_total", "base_grand_total"],
	)
	return sum(flt(r.grand_total) or flt(r.base_grand_total) for r in rows)


def refresh_for_sales_order(sales_order):
	"""Recompute and store the order's Total Invoice Value. Returns the new value."""
	if not sales_order or not frappe.db.exists("Sales Order", sales_order):
		return None
	value = _dispatched_value(sales_order)
	if flt(frappe.db.get_value("Sales Order", sales_order, "custom_total_invoice_value")) != flt(value):
		frappe.db.set_value(
			"Sales Order", sales_order, "custom_total_invoice_value", value, update_modified=False
		)
	return value


def refresh_from_delivery_note(doc, method=None):
	"""Delivery Note hook: keep the linked order's value current on submit / cancel / amend."""
	if doc.doctype != "Delivery Note":
		return
	targets = {(doc.get("custom_sales_order_id") or "").strip()}
	# A note built from the order carries the link on its items too.
	for row in doc.get("items") or []:
		if row.get("against_sales_order"):
			targets.add(row.against_sales_order)
	for so in targets:
		if not so:
			continue
		try:
			refresh_for_sales_order(so)
		except Exception:
			frappe.log_error(
				title="Total Invoice Value refresh failed for {0}".format(so),
				message=frappe.get_traceback(),
			)


@frappe.whitelist()
def backfill(from_date=None, to_date=None, apply=0):
	"""Fill the value on existing orders that already have Delivery Notes.

	Dry-run by default; apply=1 writes.

	  bench --site SITE execute alpinos.so_invoice_value.backfill --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	conditions = ["so.docstatus < 2"]
	params = {}
	if from_date:
		conditions.append("so.transaction_date >= %(from_date)s")
		params["from_date"] = from_date
	if to_date:
		conditions.append("so.transaction_date <= %(to_date)s")
		params["to_date"] = to_date

	names = frappe.db.sql(
		"""
		SELECT DISTINCT so.name
		FROM `tabSales Order` so
		JOIN `tabDelivery Note` dn
		  ON dn.custom_sales_order_id = so.name AND dn.docstatus = 1 AND dn.is_return = 0
		WHERE {conditions}
		ORDER BY so.name
		""".format(conditions=" AND ".join(conditions)),
		params,
		pluck="name",
	)

	changed, samples = 0, []
	for so in names:
		before = flt(frappe.db.get_value("Sales Order", so, "custom_total_invoice_value"))
		value = _dispatched_value(so)
		if flt(before) == flt(value):
			continue
		changed += 1
		if len(samples) < 25:
			samples.append({"sales_order": so, "old": before, "new": value})
		if apply:
			frappe.db.set_value(
				"Sales Order", so, "custom_total_invoice_value", value, update_modified=False
			)
	if apply:
		frappe.db.commit()

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"orders_with_delivery_notes": len(names),
		"changed": changed,
		"sample": samples,
	}
