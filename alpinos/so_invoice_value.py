"""Keep a Sales Order's Total Invoice Value in step with its Pick Lists and Delivery Notes.

Dispatched value wins: once any Delivery Note is submitted the figure is what those notes
shipped, priced at the ORDER's own rates, GST included, growing with each lot. Before
anything ships it falls back to what has been PICKED, so an order sitting on a submitted
Pick List shows a number instead of 0. Blank only while nothing is picked or dispatched.
"""

import frappe
from frappe.utils import flt


def _dispatched_value(sales_order):
	"""GST-inclusive value of what submitted Delivery Notes shipped, at the ORDER's rates.

	Priced the same way as _picked_value: the share of each order line the notes covered,
	applied to the order's grand_total. The notes' own grand_total is not used -- a note
	prices free rows (freebies, scheme, additional units) from the Item Price list, so
	summing notes charged for samples nobody bills, and the note carries none of the
	order's cash-discount rules. Pro-rating inherits the order's GST, discounts and
	rounding, so a fully dispatched order reads exactly its own grand total.
	"""
	rows = frappe.db.sql(
		"""
		SELECT dni.so_detail AS soi, SUM(dni.stock_qty) AS delivered
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.custom_sales_order_id = %s AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
		  AND IFNULL(dni.so_detail, '') <> ''
		GROUP BY dni.so_detail
		""",
		sales_order,
		as_dict=True,
	)
	delivered = {r.soi: flt(r.delivered) for r in rows if r.soi}
	if not delivered:
		return 0.0

	lines = frappe.get_all(
		"Sales Order Item", filters={"parent": sales_order}, fields=["name", "amount", "stock_qty"]
	)
	net = sum(flt(l.amount) for l in lines)
	if net <= 0:
		return 0.0
	share = sum(
		flt(l.amount) * (delivered.get(l.name, 0.0) / flt(l.stock_qty))
		for l in lines
		if flt(l.stock_qty) > 0
	) / net
	grand = flt(frappe.db.get_value("Sales Order", sales_order, "grand_total"))
	return flt(grand * share, 2)


def bundle_units(item_codes):
	"""item_code -> individual units in ONE combo, for the codes that are bundles.

	The native Product Bundle is the stock engine's source (alpinos.product_bundle_sync
	keeps it in step with the Item's own mapping); the Item mapping is the fallback for a
	bundle whose native record is missing.
	"""
	if not item_codes:
		return {}
	units = {}
	for r in frappe.db.sql(
		"""
		SELECT pb.new_item_code AS item, SUM(pbi.qty) AS units
		FROM `tabProduct Bundle` pb
		JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
		WHERE pb.new_item_code IN %(codes)s
		GROUP BY pb.new_item_code
		""",
		{"codes": tuple(item_codes)},
		as_dict=True,
	):
		if flt(r.units) > 0:
			units[r.item] = flt(r.units)

	missing = [c for c in item_codes if c not in units]
	if missing and frappe.db.table_exists("Product Bundle Mapping"):
		for r in frappe.db.sql(
			"""
			SELECT parent AS item, SUM(base_qty) AS units
			FROM `tabProduct Bundle Mapping`
			WHERE parenttype = 'Item' AND parent IN %(codes)s
			GROUP BY parent
			""",
			{"codes": tuple(missing)},
			as_dict=True,
		):
			if flt(r.units) > 0:
				units[r.item] = flt(r.units)
	return units


def picked_by_line(sales_orders):
	"""Sales Order Item -> what submitted Pick Lists picked for it, in the line's own stock
	units, so it compares straight with the line's stock_qty: the quantity ORDERED.

	Measured against the order, never the pick list row. The warehouse removes quantity by
	cutting the row down (20 on the list against 30 ordered), and picked-over-row would
	call that line complete. A Pick List explodes a Product Bundle into its components, all
	pointing at the one bundle line; their units are totalled and divided by the units in
	one combo (the sheet's rule), so a combo line reads in combos.
	"""
	if not sales_orders:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT pli.sales_order_item AS soi, soi.item_code, soi.stock_qty AS ordered,
		       SUM(CASE WHEN IFNULL(pli.picked_qty, 0) > 0 THEN pli.picked_qty ELSE pli.stock_qty END) AS picked,
		       SUM(pli.stock_qty) AS required,
		       MAX(IF(IFNULL(pli.product_bundle_item, '') <> '', 1, 0)) AS exploded
		FROM `tabPick List Item` pli
		JOIN `tabPick List` pl ON pl.name = pli.parent AND pl.docstatus = 1
		JOIN `tabSales Order Item` soi ON soi.name = pli.sales_order_item
		WHERE soi.parent IN %(names)s
		GROUP BY pli.sales_order_item, soi.item_code, soi.stock_qty
		""",
		{"names": tuple(sales_orders)},
		as_dict=True,
	)
	units = bundle_units(list({r.item_code for r in rows if r.exploded}))
	picked = {}
	for r in rows:
		# A row with no picked_qty on a SUBMITTED pick list is taken as fully picked: the
		# warehouse signed the list off, and some entry paths never write the column.
		qty = flt(r.picked)
		if r.exploded:
			if units.get(r.item_code):
				qty = qty / units[r.item_code]
			elif flt(r.required) > 0:
				# Combo with no known make-up: the share of its own components picked.
				qty = flt(r.ordered) * min(1.0, qty / flt(r.required))
		picked[r.soi] = qty
	return picked


def _picked_value(sales_order):
	"""GST-inclusive value of what a submitted Pick List has picked, but nothing shipped yet.

	Priced by pro-rating the order's own grand_total by the share of each ORDERED line the
	pick covered (picked_by_line), NOT by summing picked lines: a Pick List's bundle rows
	carry component codes no Sales Order line prices. Pro-rating inherits the order's GST,
	discounts and rounding, which keeps this basis comparable with the Delivery Note one,
	and a line the warehouse cut down counts only for what was picked.
	"""
	picked = picked_by_line([sales_order])
	if not picked:
		return 0.0

	lines = frappe.get_all(
		"Sales Order Item", filters={"parent": sales_order}, fields=["name", "amount", "stock_qty"]
	)
	net = sum(flt(l.amount) for l in lines)
	if net <= 0:
		return 0.0
	share = sum(
		flt(l.amount) * min(1.0, picked.get(l.name, 0.0) / flt(l.stock_qty))
		for l in lines
		if flt(l.stock_qty) > 0
	) / net
	grand = flt(frappe.db.get_value("Sales Order", sales_order, "grand_total"))
	return flt(grand * share, 2)


def refresh_for_sales_order(sales_order):
	"""Recompute and store the order's Total Invoice Value. Returns the new value."""
	if not sales_order or not frappe.db.exists("Sales Order", sales_order):
		return None
	value = _dispatched_value(sales_order)
	# Nothing shipped yet -> show what has been picked, so the figure is not 0 while the
	# order sits on a pick list. A single submitted note takes the basis back to dispatch.
	if not flt(value):
		value = _picked_value(sales_order)
	if flt(frappe.db.get_value("Sales Order", sales_order, "custom_total_invoice_value")) != flt(value):
		frappe.db.set_value(
			"Sales Order", sales_order, "custom_total_invoice_value", value, update_modified=False
		)
	return value


def refresh_post_dispatch_for_delivery_note(delivery_note):
	"""Restate the Post Dispatch rows raised against this note from the note's own total.

	Post Dispatch stamps Total Invoice Value once, at creation. A note whose total moves
	afterwards -- a post-submit edit, or a note that had no total when the row was made --
	left the dispatch row showing the old number, or 0. Returns rows changed.
	"""
	if not delivery_note:
		return 0
	value = flt(
		frappe.db.get_value("Delivery Note", delivery_note, "grand_total")
		or frappe.db.get_value("Delivery Note", delivery_note, "base_grand_total")
	)
	changed = 0
	for row in frappe.get_all(
		"Post Dispatch", filters={"delivery_note": delivery_note}, fields=["name", "total_invoice_value"]
	):
		if flt(row.total_invoice_value) == flt(value):
			continue
		frappe.db.set_value(
			"Post Dispatch", row.name, "total_invoice_value", value, update_modified=False
		)
		changed += 1
	return changed


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
	# The dispatch row reads from the same note, so it moves on the same events.
	try:
		refresh_post_dispatch_for_delivery_note(doc.name)
	except Exception:
		frappe.log_error(
			title="Post Dispatch invoice value refresh failed for {0}".format(doc.name),
			message=frappe.get_traceback(),
		)


def refresh_from_pick_list(doc, method=None):
	"""Pick List hook: an order with no Delivery Note yet is valued from its pick."""
	if doc.doctype != "Pick List":
		return
	targets = {(doc.get("custom_sales_order_id") or "").strip()}
	for row in doc.get("locations") or []:
		if row.get("sales_order"):
			targets.add(row.sales_order)
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
def backfill(from_date=None, to_date=None, apply=0, sample=25):
	"""Fill the value on existing orders that already have Delivery Notes.

	Dry-run by default; apply=1 writes. sample caps the orders listed back (0 = all).

	  bench --site SITE execute alpinos.so_invoice_value.backfill --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	sample = int(sample)
	conditions = ["so.docstatus < 2"]
	params = {}
	if from_date:
		conditions.append("so.transaction_date >= %(from_date)s")
		params["from_date"] = from_date
	if to_date:
		conditions.append("so.transaction_date <= %(to_date)s")
		params["to_date"] = to_date

	# Orders with a submitted note OR a submitted pick list -- the pick-list-only ones are
	# exactly the orders that used to sit at 0 with nothing to fill them.
	names = frappe.db.sql(
		"""
		SELECT DISTINCT so.name
		FROM `tabSales Order` so
		WHERE {conditions}
		  AND (
		    EXISTS (SELECT 1 FROM `tabDelivery Note` dn
		            WHERE dn.custom_sales_order_id = so.name AND dn.docstatus = 1 AND dn.is_return = 0)
		    OR EXISTS (SELECT 1 FROM `tabPick List Item` pli
		               JOIN `tabPick List` pl ON pl.name = pli.parent
		               WHERE pli.sales_order = so.name AND pl.docstatus = 1)
		  )
		ORDER BY so.name
		""".format(conditions=" AND ".join(conditions)),
		params,
		pluck="name",
	)

	changed, samples = 0, []
	for so in names:
		before = flt(frappe.db.get_value("Sales Order", so, "custom_total_invoice_value"))
		value = _dispatched_value(so) or _picked_value(so)
		if flt(before) == flt(value):
			continue
		changed += 1
		if not sample or len(samples) < sample:
			samples.append({"sales_order": so, "old": before, "new": value})
		if apply:
			frappe.db.set_value(
				"Sales Order", so, "custom_total_invoice_value", value, update_modified=False
			)
	if apply:
		frappe.db.commit()

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"orders_picked_or_dispatched": len(names),
		"changed": changed,
		"sample": samples,
	}


@frappe.whitelist()
def backfill_post_dispatch(apply=0):
	"""Fill Total Invoice Value on Post Dispatch rows stamped before the value existed.

	The field is written once, when the row is created from the Delivery Note, so every
	row raised before that stamping went in sits at 0 even though its note has a total.
	Dry-run by default; apply=1 writes.

	  bench --site SITE execute alpinos.so_invoice_value.backfill_post_dispatch --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	rows = frappe.db.sql(
		"""
		SELECT pd.name, pd.delivery_note, pd.total_invoice_value AS old,
		       COALESCE(NULLIF(dn.grand_total, 0), dn.base_grand_total, 0) AS new
		FROM `tabPost Dispatch` pd
		JOIN `tabDelivery Note` dn ON dn.name = pd.delivery_note
		ORDER BY pd.name
		""",
		as_dict=True,
	)

	changed, samples = 0, []
	for r in rows:
		if flt(r.old) == flt(r.new):
			continue
		changed += 1
		if len(samples) < 25:
			samples.append({"post_dispatch": r.name, "delivery_note": r.delivery_note,
			                "old": flt(r.old), "new": flt(r.new)})
		if apply:
			frappe.db.set_value(
				"Post Dispatch", r.name, "total_invoice_value", flt(r.new), update_modified=False
			)
	if apply:
		frappe.db.commit()

	orphans = frappe.db.sql(
		"""SELECT COUNT(*) FROM `tabPost Dispatch` pd
		   WHERE IFNULL(pd.delivery_note, '') = ''
		      OR NOT EXISTS (SELECT 1 FROM `tabDelivery Note` dn WHERE dn.name = pd.delivery_note)"""
	)[0][0]

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"rows_with_delivery_notes": len(rows),
		"changed": changed,
		"rows_without_a_usable_delivery_note": orphans,
		"sample": samples,
	}
