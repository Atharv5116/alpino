"""Stock by Item, Batch, MRP and Location (Purchase Inward draft "MRP-Wise and Batch-Wise
Inventory", sections 1, 8 and 10).

ERPNext keeps stock by Item and Warehouse. The draft wants it by Item, Batch, MRP and
Warehouse, so that 40 units at MRP 199 and 60 at MRP 210 of the same item never merge.

How it is held
--------------
Each batch + MRP of an item is one `MRP Batch` record (a "lot"), and ERPNext's own Inventory
Dimension carries it: the "MRP Batch" dimension adds an `mrp_batch` link to the Stock Ledger
Entry and to every stock document's rows (Stock Entry, Purchase Receipt, Delivery Note,
Stock Reconciliation, Purchase / Sales Invoice ...), copies it onto the ledger, refuses any
movement that would take a lot below zero (validate_negative_stock), and lets the standard
Stock Balance / Stock Ledger reports show and filter stock by it.

ERPNext's batch tracking (Item.has_batch_no) is deliberately NOT used: it cannot be switched on
for an item that already has submitted transactions (Item.cant_change), which is every stocked
item on production, and this app keeps batch codes as free text on the Pick List and the
Delivery Note.

Stock that came in before lots existed has no lot. It is "unassigned": the ledger rows with no
mrp_batch. It stays usable, it is never mixed into a lot by accident, and
`assign_existing_stock` (the Stock by Batch and MRP report's Assign button) moves it into a
lot with a same-warehouse transfer once someone knows which batch and MRP it is.

Keeping the two consistent
--------------------------
A lot's balance is checked by ERPNext. Unassigned stock is not (a blank dimension is not
validated), so `validate_outward_sle` holds the line for it: stock leaving a warehouse with no
lot may only come out of the unassigned balance. Without that a Delivery Note with no lot would
ship lot stock under no name, and the lot would keep reporting stock that is gone.

To keep users from meeting that error, the documents that move stock out choose lots by
themselves when nobody did (`allocate`): Pick List (preferring the Sales Order's MRP), Stock
Entry (issues, transfers, production) and, as a fallback, Delivery Note.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime

DOCTYPE = "MRP Batch"
DIMENSION = "MRP Batch"
FIELD = "mrp_batch"
# What ERPNext names the transfer-side fields of the dimension.
TO_FIELD = "to_mrp_batch"
FROM_FIELD = "from_mrp_batch"
REJECTED_FIELD = "rejected_mrp_batch"

_EPS = 1e-6


# ------------------------------------------------------------------ naming


def clean_batch(batch_no):
	return re.sub(r"\s+", " ", (batch_no or "").strip())


def fmt_mrp(mrp):
	"""249.0 -> '249', 249.5 -> '249.5' -- for names and labels."""
	value = flt(mrp, 2)
	text = ("%.2f" % value).rstrip("0").rstrip(".")
	return text or "0"


def lot_name(item_code, batch_no, mrp):
	"""'PB-CR-350:B2410:249'. Slashes would break the desk route, so they become dashes."""
	safe = lambda value: re.sub(r"[/\\<>]+", "-", value or "")
	base = "{0}:{1}:{2}".format(safe(item_code), safe(clean_batch(batch_no)) or "NB", fmt_mrp(mrp))
	name, n = base, 1
	while frappe.db.exists(DOCTYPE, name):
		n += 1
		name = f"{base}-{n}"
	return name


def lot_title(batch_no, mrp):
	parts = []
	if clean_batch(batch_no):
		parts.append(clean_batch(batch_no))
	if flt(mrp):
		parts.append(_("MRP {0}").format(fmt_mrp(mrp)))
	return " · ".join(parts)


# ------------------------------------------------------------------ setup


def setup():
	"""after_migrate: the dimension, and the lot column on the rows ERPNext leaves out."""
	_ensure_dimension()
	_ensure_pick_list_field()


def _ensure_dimension():
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	name = frappe.db.get_value("Inventory Dimension", {"reference_document": DOCTYPE}, "name")
	if name:
		if not cint(frappe.db.get_value("Inventory Dimension", name, "validate_negative_stock")):
			frappe.db.set_value("Inventory Dimension", name, "validate_negative_stock", 1)
		return
	doc = frappe.new_doc("Inventory Dimension")
	doc.dimension_name = DIMENSION
	doc.reference_document = DOCTYPE
	doc.apply_to_all_doctypes = 1
	# A lot can never go below zero; ERPNext checks it on every outward ledger row.
	doc.validate_negative_stock = 1
	doc.insert(ignore_permissions=True)
	print(f"[mrp_batch] Inventory Dimension {doc.name} created")


def _ensure_pick_list_field():
	"""ERPNext skips Pick List Item when it adds a dimension (it posts no stock), but the
	Pick List is where a lot is chosen for the Delivery Note that follows."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	insert_after = "custom_batch_code" if frappe.get_meta("Pick List Item").has_field("custom_batch_code") else "batch_no"
	create_custom_fields(
		{
			"Pick List Item": [
				dict(
					fieldname=FIELD,
					label="Batch / MRP",
					fieldtype="Link",
					options=DOCTYPE,
					insert_after=insert_after,
					allow_on_submit=0,
				),
				dict(
					fieldname="custom_lot_mrp",
					label="Batch MRP",
					fieldtype="Currency",
					insert_after=FIELD,
					read_only=1,
					fetch_from=f"{FIELD}.mrp",
				),
			],
		},
		update=True,
	)


def enabled():
	return bool(frappe.db.exists("Inventory Dimension", {"reference_document": DOCTYPE}))


# ------------------------------------------------------------------ lots


def get_or_create(item_code, batch_no=None, mrp=None, manufacturing_date=None, expiry_date=None, **source):
	"""The lot for item + batch + MRP, created on first use. None when there is neither."""
	batch_no = clean_batch(batch_no)
	mrp = flt(mrp, 2)
	if not item_code or (not batch_no and not mrp):
		return None
	name = frappe.db.get_value(DOCTYPE, {"item_code": item_code, "batch_no": batch_no, "mrp": mrp}, "name")
	if name:
		# Dates a later receipt knows and the lot does not yet.
		have = frappe.db.get_value(DOCTYPE, name, ["manufacturing_date", "expiry_date"], as_dict=True)
		fill = {}
		if manufacturing_date and not have.manufacturing_date:
			fill["manufacturing_date"] = getdate(manufacturing_date)
		if expiry_date and not have.expiry_date:
			fill["expiry_date"] = getdate(expiry_date)
		if fill:
			frappe.db.set_value(DOCTYPE, name, fill, update_modified=False)
		return name
	doc = frappe.new_doc(DOCTYPE)
	doc.update(
		{
			"item_code": item_code,
			"batch_no": batch_no,
			"mrp": mrp,
			"manufacturing_date": manufacturing_date or None,
			"expiry_date": expiry_date or None,
		}
	)
	for key in ("source", "supplier", "purchase_inward", "purchase_receipt", "purchase_rate", "reference_doctype", "reference_name"):
		if source.get(key):
			doc.set(key, source[key])
	doc.insert(ignore_permissions=True)
	return doc.name


def lot_details(names):
	names = [n for n in set(names or []) if n]
	if not names:
		return {}
	return {
		row.name: row
		for row in frappe.get_all(
			DOCTYPE,
			filters={"name": ("in", names)},
			fields=["name", "item_code", "batch_no", "mrp", "manufacturing_date", "expiry_date", "title", "creation"],
		)
	}


def titles(names):
	"""{lot: "B101 · MRP 199"} for the screens that show which Batch / MRP a row moved."""
	return {name: (d.title or name) for name, d in lot_details(names).items()}


# --------------------------------------------------------------- balances


def balances(item_code, warehouse, upto=None):
	"""{lot or None: qty in stock UOM} in one warehouse, from the stock ledger.

	None is the unassigned balance -- ledger rows with no lot."""
	conditions = ""
	values = {"item_code": item_code, "warehouse": warehouse}
	if upto:
		conditions = " AND posting_datetime <= %(upto)s"
		values["upto"] = upto
	rows = frappe.db.sql(
		f"""
		SELECT `{FIELD}` AS lot, SUM(actual_qty) AS qty
		FROM `tabStock Ledger Entry`
		WHERE item_code = %(item_code)s AND warehouse = %(warehouse)s AND is_cancelled = 0{conditions}
		GROUP BY `{FIELD}`
		""",
		values,
		as_dict=True,
	)
	out = {}
	for row in rows:
		key = row.lot or None
		out[key] = flt(out.get(key)) + flt(row.qty)
	return out


def has_lots(item_code, warehouse):
	return bool(
		frappe.db.sql(
			f"""SELECT 1 FROM `tabStock Ledger Entry`
			WHERE item_code=%s AND warehouse=%s AND is_cancelled=0 AND IFNULL(`{FIELD}`, '') != ''
			LIMIT 1""",
			(item_code, warehouse),
		)
	)


def pick_list_holds(item_code, warehouse, exclude_pick_lists=()):
	"""{lot: stock qty} that open Pick Lists have already chosen and not yet shipped.

	A Pick List names its lot before the Delivery Note moves the stock, so without this two
	Pick Lists raised one after the other would both be offered the same units."""
	if not frappe.get_meta("Pick List Item").has_field(FIELD):
		return {}
	exclude = [p for p in (exclude_pick_lists or []) if p]
	cond = ""
	values = {"item_code": item_code, "warehouse": warehouse}
	if exclude:
		cond = " AND pl.name NOT IN %(exclude)s"
		values["exclude"] = tuple(exclude)
	rows = frappe.db.sql(
		f"""
		SELECT pli.`{FIELD}` AS lot,
			SUM(GREATEST(IFNULL(pli.stock_qty, pli.qty) - IFNULL(pli.delivered_qty, 0), 0)) AS qty
		FROM `tabPick List Item` pli
		JOIN `tabPick List` pl ON pl.name = pli.parent
		WHERE pli.item_code = %(item_code)s AND pli.warehouse = %(warehouse)s
			AND IFNULL(pli.`{FIELD}`, '') != ''
			AND pl.docstatus < 2 AND IFNULL(pl.status, '') NOT IN ('Completed', 'Cancelled'){cond}
		GROUP BY pli.`{FIELD}`
		""",
		values,
		as_dict=True,
	)
	return {row.lot: flt(row.qty) for row in rows}


def available(item_code, warehouse, exclude_pick_lists=(), respect_holds=True):
	"""[{lot, qty, ...lot details}] with stock to give, best first, and the unassigned qty."""
	bal = balances(item_code, warehouse)
	holds = pick_list_holds(item_code, warehouse, exclude_pick_lists) if respect_holds else {}
	details = lot_details([k for k in bal if k])
	lots = []
	for lot, qty in bal.items():
		if not lot:
			continue
		free = flt(qty) - flt(holds.get(lot))
		if free > _EPS and lot in details:
			lots.append(frappe._dict(details[lot], lot=lot, qty=free))
	far = getdate("2999-12-31")
	lots.sort(
		key=lambda d: (
			getdate(d.expiry_date) if d.expiry_date else far,
			getdate(d.manufacturing_date) if d.manufacturing_date else far,
			d.creation,
		)
	)
	return lots, max(flt(bal.get(None)), 0.0)


def allocate(item_code, warehouse, qty, prefer_mrp=None, prefer_batch=None, exclude_pick_lists=(), respect_holds=True,
	prefer_lots=()):
	"""[(lot or None, qty)] covering `qty` stock units out of `warehouse`.

	Order: the lots named in `prefer_lots`, in that order (production consumes the lots issued
	for its own Sub PO first); a lot carrying the batch the user typed; then lots at the order's MRP (the Sales
	Order line's MRP, so an order for MRP 259 is not filled from MRP 249 stock while 259 stock
	exists); then stock with no lot, which came in before lots existed and is the oldest;
	then every other lot, earliest expiry first. Returns what it could cover; the caller
	decides what a shortfall means (ERPNext's own stock check still has the last word).
	"""
	need = flt(qty)
	if need <= _EPS:
		return []
	lots, unassigned = available(item_code, warehouse, exclude_pick_lists, respect_holds)
	batch = clean_batch(prefer_batch).lower()
	mrp = flt(prefer_mrp, 2)

	first = [lot for lot in (prefer_lots or ()) if lot]

	def rank(d):
		if d.lot in first:
			return -1 - (len(first) - first.index(d.lot)) / (len(first) + 1.0)
		if batch and (d.batch_no or "").lower() == batch:
			return 0 if (not mrp or flt(d.mrp, 2) == mrp) else 1
		if mrp and flt(d.mrp, 2) == mrp:
			return 2
		return 4

	ordered = sorted(lots, key=rank)  # stable: keeps expiry order inside each rank
	plan = []
	for d in ordered:
		if rank(d) >= 4:
			break
		take = min(need, d.qty)
		plan.append((d.lot, take))
		need -= take
		if need <= _EPS:
			return plan
	if unassigned > _EPS:
		take = min(need, unassigned)
		plan.append((None, take))
		need -= take
		if need <= _EPS:
			return plan
	for d in ordered:
		if rank(d) < 4:
			continue
		take = min(need, d.qty)
		plan.append((d.lot, take))
		need -= take
		if need <= _EPS:
			break
	return plan


# ------------------------------------------------------- unassigned guard


def validate_outward_sle(doc, method=None):
	"""Stock Ledger Entry validate: no-lot stock leaves only from the no-lot balance.

	ERPNext validates a lot's balance itself (validate_negative_stock on the dimension) but
	never a blank one, so a Delivery Note or Stock Entry with no lot could otherwise ship
	stock that belongs to a lot and leave the lot reporting units that are gone.
	"""
	if cint(doc.get("is_cancelled")) or flt(doc.get("actual_qty")) >= 0 or doc.get(FIELD):
		return
	if not doc.meta.has_field(FIELD):
		return
	if frappe.flags.in_migrate or frappe.flags.in_install:
		return
	if not has_lots(doc.item_code, doc.warehouse):
		return
	before = frappe.db.sql(
		f"""SELECT SUM(actual_qty) FROM `tabStock Ledger Entry`
		WHERE item_code=%s AND warehouse=%s AND is_cancelled=0 AND IFNULL(`{FIELD}`, '') = ''
			AND posting_datetime <= %s""",
		(doc.item_code, doc.warehouse, doc.posting_datetime or now_datetime()),
	)[0][0]
	after = flt(before) + flt(doc.actual_qty)
	if after >= -_EPS:
		return
	lots, _free = available(doc.item_code, doc.warehouse, respect_holds=False)
	listing = ", ".join("{0} ({1})".format(d.title or d.lot, flt(d.qty)) for d in lots[:6]) or _("none")
	frappe.throw(
		_(
			"{0} of {1} in {2} has no Batch / MRP, but only {3} units of it are not in a "
			"Batch / MRP. Choose the Batch / MRP on the row in {4}. In stock: {5}."
		).format(
			frappe.bold(abs(flt(doc.actual_qty))),
			frappe.bold(doc.item_code),
			frappe.bold(doc.warehouse),
			max(flt(before), 0),
			frappe.get_desk_link(doc.voucher_type, doc.voucher_no) if doc.voucher_no else doc.voucher_type,
			listing,
		),
		title=_("Batch / MRP Needed"),
	)


# ------------------------------------------------- assigning old stock


ASSIGN_ROLES = ("Stock Manager", "Warehouse Admin", "Purchase Inward Admin", "System Manager")


@frappe.whitelist()
def assign_existing_stock(rows, posting_date=None, remarks=None):
	"""Put stock that has no Batch / MRP into one, once someone knows which it is.

	`rows`: [{item_code, warehouse, batch_no, mrp, qty, manufacturing_date, expiry_date}],
	qty in the item's stock UOM. Each company's rows become one Material Transfer that moves
	the quantity out of the warehouse's no-lot stock and back into the same warehouse under
	the lot, so the quantity and the value in the warehouse do not change -- only the lot.
	Returns the Stock Entries made.
	"""
	if not set(frappe.get_roles()) & set(ASSIGN_ROLES):
		frappe.throw(
			_("Only {0} may assign Batch / MRP to existing stock.").format(", ".join(ASSIGN_ROLES)),
			frappe.PermissionError,
		)
	if not enabled():
		frappe.throw(_("The Batch / MRP dimension is not set up yet. Run bench migrate first."))
	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	by_company, need = {}, {}
	for i, raw in enumerate(rows or [], start=1):
		row = frappe._dict(raw)
		qty = flt(row.qty)
		if not row.item_code or not row.warehouse or qty <= 0:
			frappe.throw(_("Row {0}: Item, Warehouse and a quantity above zero are needed.").format(i))
		if not clean_batch(row.batch_no) and not flt(row.mrp):
			frappe.throw(_("Row {0}: enter the Batch No., the MRP, or both.").format(i))
		key = (row.item_code, row.warehouse)
		need[key] = flt(need.get(key)) + qty
		company = frappe.get_cached_value("Warehouse", row.warehouse, "company")
		by_company.setdefault(company, []).append(row)
	for (item_code, warehouse), qty in need.items():
		free = flt(balances(item_code, warehouse).get(None))
		if qty - free > _EPS:
			frappe.throw(
				_("{0} has only {1} with no Batch / MRP in {2}; {3} cannot be assigned.").format(
					frappe.bold(item_code), free, frappe.bold(warehouse), qty
				),
				title=_("Not Enough Unassigned Stock"),
			)

	made = []
	for company, company_rows in by_company.items():
		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = "Material Transfer"
		entry.purpose = "Material Transfer"
		entry.company = company
		if posting_date:
			entry.set_posting_time = 1
			entry.posting_date = posting_date
		entry.remarks = remarks or _("Batch / MRP assigned to stock received before lots were kept.")
		for row in company_rows:
			lot = get_or_create(
				row.item_code, row.batch_no, row.mrp, row.manufacturing_date, row.expiry_date, source="Opening"
			)
			stock_uom = frappe.get_cached_value("Item", row.item_code, "stock_uom")
			entry.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": flt(row.qty),
					"uom": stock_uom,
					"stock_uom": stock_uom,
					"conversion_factor": 1.0,
					"s_warehouse": row.warehouse,
					"t_warehouse": row.warehouse,
					FIELD: None,
					TO_FIELD: lot,
				},
			)
		entry.insert()
		entry.submit()
		made.append(entry.name)
	return made


# --------------------------------------------------------- row splitting


def split_rows(doc, table, row, plan, qty_field, stock_qty_field=None, on_copy=None):
	"""Write `plan` [(lot, stock qty)] onto `row`, adding a copy of it for every further lot.

	The first part stays on the row itself, so links that point at it survive; the others
	are inserted right below it. `on_copy(new_row, part_qty)` fixes up whatever else a
	document keeps per row (boxes, amounts). Quantities are converted back to the row's UOM.
	"""
	factor = flt(row.get("conversion_factor")) or 1.0
	rows = []
	for i, (lot, stock_qty) in enumerate(plan):
		target = row
		if i:
			data = row.as_dict(no_default_fields=True)
			for key in ("name", "idx", "creation", "modified", "owner", "modified_by"):
				data.pop(key, None)
			data["doctype"] = row.doctype
			target = frappe.get_doc(data)
			target.parent, target.parenttype, target.parentfield = doc.name, doc.doctype, table
		target.set(FIELD, lot)
		target.set(qty_field, flt(stock_qty / factor, 6))
		if stock_qty_field:
			target.set(stock_qty_field, flt(stock_qty, 6))
		if on_copy:
			on_copy(target, stock_qty)
		rows.append(target)
	if len(rows) > 1:
		current = list(doc.get(table))
		at = current.index(row)
		doc.set(table, current[: at + 1] + rows[1:] + current[at + 1 :])
		for i, child in enumerate(doc.get(table), start=1):
			child.idx = i
	return rows


def describe(lot):
	if not lot:
		return _("no Batch / MRP")
	d = lot_details([lot]).get(lot)
	return (d.title or lot) if d else lot
