"""Inventory module (FRD Phase 10): dashboards, Production Transfer, Inventory Adjustment.

    10.1  Dashboards       get_wip_dashboard / get_fg_dashboard (read-only)
    10.2  Transfer         Production Transfer -> Stock Entry "Material Transfer"
    10.3  Adjustment       Inventory Adjustment -> Stock Entry "Material Receipt" (Add) or
                           "Material Issue" (Deduct); a deduction above the approval threshold
                           waits for the Plant Head (10.4.3 / 13.2)
    10.4  Negative stock   checked here on save AND by inventory_rules on the Stock Entry

Every Stock Entry posted here carries custom_entry_kind (Production Transfer / Inventory
Adjustment) and custom_inventory_reference, and the flags alpinos_material (so the Material
Management hooks do not re-check store roles) and alpinos_inventory.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, get_fullname, getdate, now_datetime, nowdate

from alpinos.production import inventory_common as IC

WORK_ORDER = "Work Order"


# =================================================================== stock entries

def _make_entry(kind, purpose, company, posting_date, rows, reference, remarks=""):
	"""Insert and submit one Stock Entry. rows: dicts of item_code, qty, s_warehouse,
	t_warehouse, batch_no, basic_rate (optional)."""
	se = frappe.new_doc(IC.SE)
	se.purpose = purpose
	se.stock_entry_type = purpose
	se.company = company
	se.posting_date = posting_date or nowdate()
	se.set_posting_time = 1 if getdate(se.posting_date) != getdate(nowdate()) else 0
	se.remarks = remarks or ""
	if se.meta.has_field("custom_entry_kind"):
		se.set("custom_entry_kind", kind)
	if se.meta.has_field(IC.REFERENCE_FIELD):
		se.set(IC.REFERENCE_FIELD, reference)
	info = IC.item_meta([r["item_code"] for r in rows])
	zero_rate = False
	for r in rows:
		meta = info.get(r["item_code"]) or frappe._dict()
		row = {
			"item_code": r["item_code"],
			"qty": flt(r["qty"]),
			"transfer_qty": flt(r["qty"]),
			"uom": meta.get("stock_uom"),
			"stock_uom": meta.get("stock_uom"),
			"conversion_factor": 1,
			"s_warehouse": r.get("s_warehouse"),
			"t_warehouse": r.get("t_warehouse"),
		}
		if r.get("batch_no"):
			row["batch_no"] = r["batch_no"]
			row["use_serial_batch_fields"] = 1
		if purpose == "Material Receipt":
			rate = flt(r.get("basic_rate"))
			row["basic_rate"] = rate
			if not rate:
				row["allow_zero_valuation_rate"] = 1
				zero_rate = True
		se.append("items", row)
	se.flags.alpinos_material = True
	se.flags.alpinos_inventory = True
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	if zero_rate:
		frappe.msgprint(_("No valuation rate was found for some items; they were received at zero value."),
		                indicator="orange", alert=True)
	return se.name


def cancel_linked_entry(doc):
	"""Cancel the Stock Entry a Production Transfer / Inventory Adjustment posted."""
	name = doc.get("stock_entry")
	if not name or not frappe.db.exists(IC.SE, name):
		return
	se = frappe.get_doc(IC.SE, name)
	if cint(se.docstatus) != 1:
		return
	se.flags.alpinos_material = True
	se.flags.alpinos_inventory = True
	se.flags.ignore_permissions = True
	se.cancel()
	IC.audit(doc.doctype, doc.name, "Cancelled", _("Stock Entry {0} cancelled").format(name))


def _valuation_rate(item_code, warehouse):
	rate = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse},
	                               "valuation_rate"))
	if not rate:
		rate = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
	return rate


# ============================================================ shared row validation

def _check_warehouse(warehouse, label):
	if not warehouse:
		frappe.throw(_("Please choose the {0}.").format(label), title=_("{0} Required").format(label))
	wh = frappe.db.get_value("Warehouse", warehouse, ["is_group", "disabled", "company"], as_dict=True)
	if not wh:
		frappe.throw(_("Warehouse {0} does not exist.").format(warehouse), title=_("Unknown Warehouse"))
	if cint(wh.is_group):
		frappe.throw(_("{0} is a group warehouse; choose a warehouse that holds stock.").format(warehouse),
		             title=_("Group Warehouse"))
	if cint(wh.disabled):
		frappe.throw(_("Warehouse {0} is disabled.").format(warehouse), title=_("Disabled Warehouse"))
	return wh


def _check_rows(doc, source_warehouse, need_stock, label_qty):
	"""Item/batch sanity on every row; fills names/UOM/status and, when need_stock, the
	stock at the source and the FRD 10.4.1 negative-stock block."""
	rows = doc.get("items") or []
	if not rows:
		frappe.throw(_("Add at least one item."), title=_("No Items"))
	info = IC.item_meta([r.item_code for r in rows])
	status = IC.fg_status_map([r.batch_no for r in rows if r.get("batch_no")])
	claimed = {}
	for r in rows:
		meta = info.get(r.item_code)
		if not meta:
			frappe.throw(_("Row {0}: item {1} does not exist.").format(r.idx, r.item_code),
			             title=_("Unknown Item"))
		if flt(r.qty) <= 0:
			frappe.throw(_("Row {0}: the {1} of {2} must be greater than 0.").format(
				r.idx, label_qty, r.item_code), title=_("Quantity Required"))
		if meta.has_batch_no and not r.get("batch_no"):
			frappe.throw(_("Row {0}: {1} is batch-tracked; choose the Batch Code.").format(
				r.idx, r.item_code), title=_("Batch Required"))
		if not meta.has_batch_no and r.get("batch_no"):
			r.batch_no = None
		if r.get("batch_no"):
			batch_item = frappe.db.get_value("Batch", r.batch_no, "item")
			if batch_item and batch_item != r.item_code:
				frappe.throw(_("Row {0}: batch {1} belongs to {2}, not {3}.").format(
					r.idx, r.batch_no, batch_item, r.item_code), title=_("Wrong Batch"))
		r.item_name = meta.item_name
		r.uom = meta.stock_uom
		if r.meta.has_field("fg_status"):
			r.fg_status = (status.get(r.get("batch_no")) or frappe._dict()).get("fg_status") or ""
		if r.meta.has_field("qty_kg"):
			r.qty_kg = flt(IC.qty_in_kg(r.qty, meta), 3)
		if source_warehouse:
			available = IC.available_qty(r.item_code, source_warehouse, r.get("batch_no"))
			if r.meta.has_field("available_qty"):
				r.available_qty = available
			if r.meta.has_field("current_qty"):
				r.current_qty = available
			if need_stock:
				key = (r.item_code, r.get("batch_no") or "")
				claimed[key] = flt(claimed.get(key)) + flt(r.qty)
				if claimed[key] > available + 0.0000001:
					frappe.throw(
						_("Row {0}: {1}{2} -- only {3} {4} available at {5}. {6}").format(
							r.idx, r.item_code,
							(" / " + r.batch_no) if r.get("batch_no") else "",
							flt(available), meta.stock_uom or "", source_warehouse,
							_(IC.MSG_INSUFFICIENT)),
						title=_("Insufficient Stock"))
	return info


# ======================================================== Production Transfer (10.2)

def validate_transfer(doc):
	if not doc.flags.get("alpinos_inventory"):
		IC.assert_roles(IC.TRANSFER_WRITE_ROLES, _("create a Production Transfer"))
	if doc.transfer_type not in IC.TRANSFER_TYPES:
		frappe.throw(_("Choose a Transfer Type: {0}.").format(", ".join(IC.TRANSFER_TYPES)),
		             title=_("Transfer Type Required"))
	if doc.transfer_reason not in IC.TRANSFER_REASONS:
		frappe.throw(_("Choose a Transfer Reason: {0}.").format(", ".join(IC.TRANSFER_REASONS)),
		             title=_("Transfer Reason Required"))
	if doc.transfer_reason == IC.TRANSFER_REASON_OTHER and not (doc.remarks or "").strip():
		frappe.throw(_("The reason is Other, so please write a remark saying why."),
		             title=_("Remark Required"))
	src = _check_warehouse(doc.source_warehouse, _("Source Location"))
	tgt = _check_warehouse(doc.target_warehouse, _("Target Location"))
	if doc.source_warehouse == doc.target_warehouse:
		frappe.throw(_("The Source and Target Location cannot be the same."), title=_("Same Location"))
	if src.company != tgt.company:
		frappe.throw(_("{0} and {1} belong to different companies.").format(
			doc.source_warehouse, doc.target_warehouse), title=_("Different Companies"))
	doc.company = src.company
	if doc.posting_date and getdate(doc.posting_date) > getdate(nowdate()):
		frappe.throw(_("The Transfer Date cannot be in the future."), title=_("Invalid Date"))
	# FRD 10.4.2: FG-Hold / QC-Rejected batches MAY be moved; their status is not changed
	# and they stay blocked from dispatch wherever they sit (dispatch_rules).
	_check_rows(doc, doc.source_warehouse, need_stock=True, label_qty=_("Transfer Qty"))
	doc.total_qty = flt(sum(flt(r.qty) for r in doc.items), 3)


def post_transfer(doc):
	rows = [{"item_code": r.item_code, "qty": flt(r.qty), "batch_no": r.get("batch_no"),
	         "s_warehouse": doc.source_warehouse, "t_warehouse": doc.target_warehouse}
	        for r in doc.items]
	name = _make_entry(IC.KIND_TRANSFER, "Material Transfer", doc.company, doc.posting_date, rows,
	                   doc.name, remarks=_("{0}: {1} ({2})").format(doc.name, doc.transfer_type,
	                                                                doc.transfer_reason))
	doc.db_set("stock_entry", name)
	IC.audit(doc.doctype, doc.name, "Transferred",
	         _("{0} -> {1}, Stock Entry {2}").format(doc.source_warehouse, doc.target_warehouse, name))


# ======================================================= Inventory Adjustment (10.3)

def validate_adjustment(doc):
	if not doc.flags.get("alpinos_inventory"):
		IC.assert_roles(IC.ADJUSTMENT_WRITE_ROLES, _("create an Inventory Adjustment"))
	if doc.adjustment_type not in IC.ADJUSTMENT_TYPES:
		frappe.throw(_("Choose Add Stock or Deduct Stock."), title=_("Adjustment Type Required"))
	if doc.reason_code not in IC.ADJUSTMENT_REASONS:
		frappe.throw(_("Choose a Reason Code: {0}.").format(", ".join(IC.ADJUSTMENT_REASONS)),
		             title=_("Reason Code Required"))
	if not (doc.admin_remarks or "").strip():
		frappe.throw(_("Admin Remarks are mandatory: explain the adjustment."),
		             title=_("Remarks Required"))
	wh = _check_warehouse(doc.warehouse, _("Warehouse"))
	doc.company = wh.company
	if doc.posting_date and getdate(doc.posting_date) > getdate(nowdate()):
		frappe.throw(_("The Adjustment Date cannot be in the future."), title=_("Invalid Date"))
	deduct = doc.adjustment_type == IC.ADJ_DEDUCT
	_check_rows(doc, doc.warehouse, need_stock=deduct, label_qty=_("Quantity"))
	doc.total_kg = flt(sum(flt(r.qty_kg) for r in doc.items), 3)
	# FRD 13.2: a deduction of more than the threshold (default 500 KG) needs the Plant Head.
	doc.requires_approval = 1 if deduct and doc.total_kg > IC.approval_threshold_kg() else 0
	if cint(doc.docstatus) == 0:
		doc.approval_status = IC.ADJ_DRAFT


def _post_adjustment(doc):
	deduct = doc.adjustment_type == IC.ADJ_DEDUCT
	rows = []
	for r in doc.items:
		row = {"item_code": r.item_code, "qty": flt(r.qty), "batch_no": r.get("batch_no")}
		if deduct:
			row["s_warehouse"] = doc.warehouse
		else:
			row["t_warehouse"] = doc.warehouse
			row["basic_rate"] = _valuation_rate(r.item_code, doc.warehouse)
		rows.append(row)
	purpose = "Material Issue" if deduct else "Material Receipt"
	name = _make_entry(IC.KIND_ADJUSTMENT, purpose, doc.company, doc.posting_date, rows, doc.name,
	                   remarks=_("{0}: {1} -- {2}. {3}").format(doc.name, doc.adjustment_type,
	                                                            doc.reason_code, doc.admin_remarks or ""))
	doc.db_set("stock_entry", name)
	doc.db_set("approval_status", IC.ADJ_POSTED)
	return name


def on_submit_adjustment(doc):
	if cint(doc.requires_approval):
		doc.db_set("approval_status", IC.ADJ_PENDING)
		IC.notify(IC.ADJUSTMENT_NOTIFY_ROLES,
		          _("Approval Required: Inventory Adjustment {0} deducts {1} KG from {2} ({3}). "
		            "Click to review.").format(doc.name, flt(doc.total_kg, 3), doc.warehouse,
		                                       doc.reason_code),
		          doctype=doc.doctype, name=doc.name, email=True)
		IC.audit(doc.doctype, doc.name, "Sent For Approval",
		         _("{0} KG deduction exceeds the {1} KG threshold").format(
			         flt(doc.total_kg, 3), IC.approval_threshold_kg()))
		frappe.msgprint(_("This deduction exceeds {0} KG, so it is waiting for Plant Head approval. "
		                  "No stock has been deducted yet.").format(IC.approval_threshold_kg()),
		                title=_("Pending Approval"), indicator="orange")
		return
	name = _post_adjustment(doc)
	IC.audit(doc.doctype, doc.name, "Posted", _("Stock Entry {0}").format(name))


def on_cancel_adjustment(doc):
	cancel_linked_entry(doc)
	doc.db_set("approval_status", IC.ADJ_CANCELLED)


# ================================================================= list helpers

def _paging(start, page_length):
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or 50, 1), 500)
	return start, page_length


def _date_filter(filters, field, date_from, date_to):
	if date_from and date_to:
		filters[field] = ("between", [date_from, date_to])
	elif date_from:
		filters[field] = (">=", date_from)
	elif date_to:
		filters[field] = ("<=", date_to)


def _status_label(docstatus):
	return {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(cint(docstatus), "Draft")


# =================================================================== dashboards

def _assert_read():
	IC.assert_roles(IC.INVENTORY_READ_ROLES, _("open the Inventory screens"))


@frappe.whitelist()
def get_wip_dashboard(item=None, category=None, warehouse=None):
	"""10.1 (1) Production (WIP) Inventory: RM / PM / Additive and baked bulk on the floor."""
	_assert_read()
	floor = [w for w in dict.fromkeys([IC.setting("wip_warehouse"), IC.baked_wip_wh()]) if w]
	if warehouse:
		floor = [w for w in floor if w == warehouse] or [warehouse]
	out = {"warehouses": floor, "stock": [], "baked": [], "message": ""}
	if not floor:
		out["message"] = _("Set the WIP warehouse in Production Settings.")
		return out

	filters = {"warehouse": ("in", floor), "actual_qty": ("!=", 0)}
	if item:
		filters["item_code"] = item
	bins = frappe.get_all("Bin", filters=filters,
	                      fields=["item_code", "warehouse", "actual_qty", "stock_value"],
	                      order_by="item_code asc", limit_page_length=5000)
	info = IC.item_meta([b.item_code for b in bins])
	bulk_items = set()
	if bins:
		bulk_items = set(frappe.get_all(
			WORK_ORDER, filters={"production_item": ("in", list({b.item_code for b in bins})),
			                     "custom_parent_production_order": ("is", "set")},
			pluck="production_item", distinct=True)) if IC.has_field(
			WORK_ORDER, "custom_parent_production_order") else set()
	baked_wh = IC.baked_wip_wh()
	for b in bins:
		meta = info.get(b.item_code) or frappe._dict()
		cat = meta.get("material_type") or ""
		if cat not in ("RM", "PM", "Additive"):
			cat = "Baked / Semi-finished" if (b.item_code in bulk_items or b.warehouse == baked_wh) \
				else (cat or "Other")
		if category and category != cat:
			continue
		out["stock"].append({
			"item_code": b.item_code, "item_name": meta.get("item_name"), "category": cat,
			"warehouse": b.warehouse, "qty": flt(b.actual_qty), "uom": meta.get("stock_uom"),
			"value": flt(b.stock_value, 2),
		})

	if IC.has_field(WORK_ORDER, "custom_wip_qty") and (not category or category == "Baked / Semi-finished"):
		subs = frappe.get_all(
			WORK_ORDER,
			filters={"custom_wip_qty": (">", 0), "docstatus": ("<", 2),
			         "custom_parent_production_order": ("is", "set")},
			fields=["name", "custom_parent_production_order as parent", "custom_batch_number as batch",
			        "production_item", "item_name", "custom_wip_qty as wip_qty",
			        "custom_execution_status as status"],
			order_by="name asc", limit_page_length=2000)
		if item:
			subs = [s for s in subs if s.production_item == item]
		last = _last_manufacture([s.name for s in subs])
		today = nowdate()
		for s in subs:
			baked_on = last.get(s.name)
			s["last_baked_on"] = baked_on
			s["aging_days"] = date_diff(today, baked_on) if baked_on else None
			out["baked"].append(s)
	return out


def _last_manufacture(sub_names):
	if not sub_names:
		return {}
	rows = frappe.db.sql(
		"""select work_order, max(posting_date) as d from `tabStock Entry`
		   where docstatus = 1 and purpose = 'Manufacture' and work_order in %(subs)s
		   group by work_order""", {"subs": tuple(sub_names)}, as_dict=True)
	return {r.work_order: r.d for r in rows}


@frappe.whitelist()
def get_fg_dashboard(status=None, item=None, warehouse=None, batch=None):
	"""10.1 (2) FG Inventory by SKU / batch. Only FG-Cleared stock in the FG warehouse
	counts as Available for Dispatch."""
	_assert_read()
	out = {"rows": [], "totals": {}, "tracked": int(IC.batch_fg_tracked()), "message": "",
	       "fg_warehouse": IC.setting("fg_warehouse")}
	if not IC.has_field("Item", "custom_material_type"):
		out["message"] = _("Items carry no Material Type yet, so FG items cannot be identified.")
		return out
	item_filters = {"custom_material_type": "FG", "is_stock_item": 1}
	if item:
		item_filters["name"] = item
	fg_items = frappe.get_all("Item", filters=item_filters, pluck="name", limit_page_length=0)
	if not fg_items:
		return out
	info = IC.item_meta(fg_items)
	batched = [i for i in fg_items if info.get(i) and info[i].has_batch_no]
	plain = [i for i in fg_items if i not in set(batched)]
	whs = [warehouse] if warehouse else None
	rows = IC.batch_stock(batched, whs, [batch] if batch else None) if batched else []
	if plain and not batch:
		bf = {"item_code": ("in", plain), "actual_qty": ("!=", 0)}
		if warehouse:
			bf["warehouse"] = warehouse
		for b in frappe.get_all("Bin", filters=bf, fields=["item_code", "warehouse", "actual_qty"],
		                        limit_page_length=0):
			rows.append(frappe._dict(item_code=b.item_code, batch_no="", warehouse=b.warehouse,
			                         qty=b.actual_qty))
	status_map = IC.fg_status_map([r.batch_no for r in rows if r.batch_no])
	fg_wh = out["fg_warehouse"]
	totals = {}
	for r in rows:
		st = status_map.get(r.batch_no) or frappe._dict()
		fg_status = st.get("fg_status") or ""
		if status and fg_status != status:
			continue
		qty = flt(r.qty)
		available = qty if (fg_status == IC.FG_CLEARED and fg_wh and r.warehouse == fg_wh and qty > 0) else 0
		meta = info.get(r.item_code) or frappe._dict()
		out["rows"].append({
			"item_code": r.item_code, "item_name": meta.get("item_name"), "batch_no": r.batch_no,
			"warehouse": r.warehouse, "qty": qty, "uom": meta.get("stock_uom"),
			"fg_status": fg_status, "sub_order": st.get("sub_order"), "parent": st.get("parent"),
			"mfg_date": st.get("mfg"), "expiry_date": st.get("expiry"),
			"available_for_dispatch": available,
		})
		key = fg_status or _("Not tracked")
		totals[key] = flt(totals.get(key)) + qty
	totals["Available for Dispatch"] = sum(flt(r["available_for_dispatch"]) for r in out["rows"])
	out["totals"] = totals
	return out


# ============================================================ pickers (both screens)

@frappe.whitelist()
def source_batches(item_code, warehouse):
	"""Batches of this item that actually exist at the source (FRD 10.2 'Crucial Link'),
	earliest expiry first, with their FG status."""
	_assert_read()
	if not (item_code and warehouse):
		return []
	rows = IC.batch_stock([item_code], [warehouse])
	status = IC.fg_status_map([r.batch_no for r in rows])
	out = []
	for r in rows:
		if flt(r.qty) <= 0:
			continue
		st = status.get(r.batch_no) or frappe._dict()
		out.append({"batch_no": r.batch_no, "qty": flt(r.qty), "fg_status": st.get("fg_status") or "",
		            "expiry_date": st.get("expiry"), "mfg_date": st.get("mfg")})
	out.sort(key=lambda x: (x["expiry_date"] is None, str(x["expiry_date"] or ""), x["batch_no"]))
	return out


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def batch_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for Batch: only batches of filters.item_code that have stock at
	filters.warehouse (any batch of the item when filters.any_batch is set -- Add Stock)."""
	filters = filters or {}
	item_code, warehouse = filters.get("item_code"), filters.get("warehouse")
	if not item_code:
		return []
	if cint(filters.get("any_batch")) or not warehouse:
		return frappe.db.sql(
			"""select name, expiry_date from `tabBatch` where item = %(i)s and disabled = 0
			   and name like %(t)s order by expiry_date is null, expiry_date, name
			   limit %(s)s, %(p)s""",
			{"i": item_code, "t": f"%{txt or ''}%", "s": cint(start), "p": cint(page_len) or 20})
	rows = [r for r in source_batches(item_code, warehouse)
	        if (txt or "").lower() in r["batch_no"].lower()]
	return [(r["batch_no"], _("Qty {0}").format(flt(r["qty"])), r["fg_status"] or "",
	         str(r["expiry_date"] or "")) for r in rows[cint(start):cint(start) + (cint(page_len) or 20)]]


@frappe.whitelist()
def item_stock(item_code, warehouse, batch_no=None):
	_assert_read()
	info = IC.item_meta([item_code]).get(item_code) or frappe._dict()
	return {"item_name": info.get("item_name"), "uom": info.get("stock_uom"),
	        "has_batch_no": cint(info.get("has_batch_no")),
	        "qty": IC.available_qty(item_code, warehouse, batch_no or None),
	        "fg_status": (IC.fg_status_map([batch_no]).get(batch_no) or {}).get("fg_status") if batch_no else ""}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def items_at_warehouse(doctype, txt, searchfield, start, page_len, filters):
	"""Link query: items with stock in filters.warehouse."""
	warehouse = (filters or {}).get("warehouse")
	if not warehouse:
		return frappe.db.sql(
			"""select name, item_name from `tabItem` where disabled = 0 and is_stock_item = 1
			   and (name like %(t)s or item_name like %(t)s) order by name limit %(s)s, %(p)s""",
			{"t": f"%{txt or ''}%", "s": cint(start), "p": cint(page_len) or 20})
	return frappe.db.sql(
		"""select b.item_code, i.item_name, b.actual_qty from `tabBin` b
		   join `tabItem` i on i.name = b.item_code
		   where b.warehouse = %(w)s and b.actual_qty > 0
		     and (b.item_code like %(t)s or i.item_name like %(t)s)
		   order by b.item_code limit %(s)s, %(p)s""",
		{"w": warehouse, "t": f"%{txt or ''}%", "s": cint(start), "p": cint(page_len) or 20})


# ======================================================= Production Transfer screens

@frappe.whitelist()
def get_transfer_list(search=None, status=None, transfer_type=None, source_warehouse=None,
                      target_warehouse=None, date_from=None, date_to=None, start=0, page_length=50):
	_assert_read()
	start, page_length = _paging(start, page_length)
	filters = {}
	if status:
		filters["docstatus"] = {"Draft": 0, "Submitted": 1, "Cancelled": 2}.get(status, 0)
	for k, v in (("transfer_type", transfer_type), ("source_warehouse", source_warehouse),
	             ("target_warehouse", target_warehouse)):
		if v:
			filters[k] = v
	_date_filter(filters, "posting_date", date_from, date_to)
	or_filters = {"name": ("like", f"%{search}%"), "remarks": ("like", f"%{search}%")} if search else None
	rows = frappe.get_all(IC.TRANSFER, filters=filters, or_filters=or_filters,
	                      fields=["name", "posting_date", "transfer_type", "transfer_reason",
	                              "source_warehouse", "target_warehouse", "total_qty", "docstatus",
	                              "stock_entry", "owner"],
	                      order_by="posting_date desc, name desc", start=start,
	                      page_length=page_length + 1)
	more = len(rows) > page_length
	rows = rows[:page_length]
	for r in rows:
		r["status"] = _status_label(r.docstatus)
		r["by"] = get_fullname(r.owner)
	return {"rows": rows, "has_more": int(more), "start": start, "page_length": page_length,
	        "can_create": int(IC.has_any(IC.TRANSFER_WRITE_ROLES))}


def _transfer_payload(doc):
	return {
		"name": doc.name, "posting_date": doc.posting_date, "transfer_type": doc.transfer_type,
		"transfer_reason": doc.transfer_reason, "source_warehouse": doc.source_warehouse,
		"target_warehouse": doc.target_warehouse, "company": doc.company, "remarks": doc.remarks,
		"total_qty": doc.total_qty, "stock_entry": doc.stock_entry, "docstatus": doc.docstatus,
		"status": _status_label(doc.docstatus), "by": get_fullname(doc.owner),
		"items": [{"item_code": r.item_code, "item_name": r.item_name, "batch_no": r.batch_no,
		           "fg_status": r.fg_status, "available_qty": r.available_qty, "qty": r.qty,
		           "uom": r.uom} for r in doc.items],
	}


@frappe.whitelist()
def get_transfer_context(name=None):
	_assert_read()
	ctx = {"types": list(IC.TRANSFER_TYPES), "reasons": list(IC.TRANSFER_REASONS),
	       "wip_warehouse": IC.setting("wip_warehouse"), "baked_wip_warehouse": IC.baked_wip_wh(),
	       "fg_hold_warehouse": IC.setting("fg_hold_warehouse"),
	       "fg_warehouse": IC.setting("fg_warehouse"), "main_warehouse": IC.setting("main_warehouse"),
	       "can_write": int(IC.has_any(IC.TRANSFER_WRITE_ROLES)),
	       "can_cancel": 0, "doc": None}
	if name:
		doc = frappe.get_doc(IC.TRANSFER, name)
		ctx["doc"] = _transfer_payload(doc)
		ctx["can_cancel"] = int(cint(doc.docstatus) == 1 and IC.has_any(IC.TRANSFER_MANAGE_ROLES))
		ctx["can_write"] = int(cint(doc.docstatus) == 0 and ctx["can_write"])
	return ctx


@frappe.whitelist()
def save_transfer(payload, submit=0):
	IC.assert_roles(IC.TRANSFER_WRITE_ROLES, _("create a Production Transfer"))
	p = IC.parse(payload)
	if p.get("name"):
		doc = frappe.get_doc(IC.TRANSFER, p.name)
		if cint(doc.docstatus) != 0:
			frappe.throw(_("{0} is already submitted.").format(p.name), title=_("Not A Draft"))
	else:
		doc = frappe.new_doc(IC.TRANSFER)
	for f in ("posting_date", "transfer_type", "transfer_reason", "source_warehouse",
	          "target_warehouse", "remarks"):
		doc.set(f, p.get(f))
	doc.posting_date = doc.posting_date or nowdate()
	doc.set("items", [])
	for r in p.get("items") or []:
		r = frappe._dict(r or {})
		if not r.get("item_code"):
			continue
		doc.append("items", {"item_code": r.item_code, "batch_no": r.get("batch_no") or None,
		                     "qty": flt(r.get("qty"))})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	if cint(submit):
		doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def submit_transfer(name):
	IC.assert_roles(IC.TRANSFER_WRITE_ROLES, _("submit a Production Transfer"))
	doc = frappe.get_doc(IC.TRANSFER, name)
	if cint(doc.docstatus) != 0:
		frappe.throw(_("{0} is not a draft.").format(name), title=_("Not A Draft"))
	doc.flags.ignore_permissions = True
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def cancel_transfer(name):
	IC.assert_roles(IC.TRANSFER_MANAGE_ROLES, _("cancel a Production Transfer"))
	doc = frappe.get_doc(IC.TRANSFER, name)
	if cint(doc.docstatus) != 1:
		frappe.throw(_("{0} is not submitted.").format(name), title=_("Not Submitted"))
	doc.flags.ignore_permissions = True
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def delete_transfer(name):
	IC.assert_roles(IC.TRANSFER_WRITE_ROLES, _("delete a Production Transfer"))
	if cint(frappe.db.get_value(IC.TRANSFER, name, "docstatus")) != 0:
		frappe.throw(_("Only a draft can be deleted."), title=_("Not A Draft"))
	frappe.delete_doc(IC.TRANSFER, name, ignore_permissions=True)
	frappe.db.commit()
	return {"deleted": name}


# ===================================================== Inventory Adjustment screens

@frappe.whitelist()
def get_adjustment_list(search=None, approval_status=None, adjustment_type=None, warehouse=None,
                        date_from=None, date_to=None, start=0, page_length=50):
	_assert_read()
	start, page_length = _paging(start, page_length)
	filters = {}
	for k, v in (("approval_status", approval_status), ("adjustment_type", adjustment_type),
	             ("warehouse", warehouse)):
		if v:
			filters[k] = v
	_date_filter(filters, "posting_date", date_from, date_to)
	or_filters = {"name": ("like", f"%{search}%"), "admin_remarks": ("like", f"%{search}%")} \
		if search else None
	rows = frappe.get_all(IC.ADJUSTMENT, filters=filters, or_filters=or_filters,
	                      fields=["name", "posting_date", "adjustment_type", "reason_code", "warehouse",
	                              "total_kg", "approval_status", "docstatus", "stock_entry", "owner"],
	                      order_by="posting_date desc, name desc", start=start,
	                      page_length=page_length + 1)
	more = len(rows) > page_length
	rows = rows[:page_length]
	for r in rows:
		r["by"] = get_fullname(r.owner)
	return {"rows": rows, "has_more": int(more), "start": start, "page_length": page_length,
	        "can_create": int(IC.has_any(IC.ADJUSTMENT_WRITE_ROLES)),
	        "can_approve": int(IC.has_any(IC.ADJUSTMENT_APPROVE_ROLES)),
	        "threshold_kg": IC.approval_threshold_kg()}


@frappe.whitelist()
def get_adjustment_context(name=None):
	_assert_read()
	ctx = {"types": list(IC.ADJUSTMENT_TYPES), "reasons": list(IC.ADJUSTMENT_REASONS),
	       "threshold_kg": IC.approval_threshold_kg(),
	       "can_write": int(IC.has_any(IC.ADJUSTMENT_WRITE_ROLES)), "can_approve": 0,
	       "can_cancel": 0, "doc": None}
	if name:
		doc = frappe.get_doc(IC.ADJUSTMENT, name)
		ctx["doc"] = {
			"name": doc.name, "posting_date": doc.posting_date, "adjustment_type": doc.adjustment_type,
			"reason_code": doc.reason_code, "warehouse": doc.warehouse, "company": doc.company,
			"admin_remarks": doc.admin_remarks, "total_kg": doc.total_kg,
			"approval_status": doc.approval_status, "requires_approval": doc.requires_approval,
			"approved_by": get_fullname(doc.approved_by) if doc.approved_by else "",
			"approved_on": doc.approved_on,
			"rejected_by": get_fullname(doc.rejected_by) if doc.rejected_by else "",
			"rejected_on": doc.rejected_on, "rejection_reason": doc.rejection_reason,
			"stock_entry": doc.stock_entry, "docstatus": doc.docstatus, "by": get_fullname(doc.owner),
			"items": [{"item_code": r.item_code, "item_name": r.item_name, "batch_no": r.batch_no,
			           "current_qty": r.current_qty, "qty": r.qty, "uom": r.uom, "qty_kg": r.qty_kg}
			          for r in doc.items],
		}
		pending = cint(doc.docstatus) == 1 and doc.approval_status == IC.ADJ_PENDING
		ctx["can_approve"] = int(pending and IC.has_any(IC.ADJUSTMENT_APPROVE_ROLES))
		ctx["can_cancel"] = int(cint(doc.docstatus) == 1 and doc.approval_status in (IC.ADJ_PENDING, IC.ADJ_POSTED)
		                        and IC.has_any(IC.ADJUSTMENT_WRITE_ROLES))
		ctx["can_write"] = int(cint(doc.docstatus) == 0 and ctx["can_write"])
	return ctx


@frappe.whitelist()
def save_adjustment(payload, submit=0):
	IC.assert_roles(IC.ADJUSTMENT_WRITE_ROLES, _("create an Inventory Adjustment"))
	p = IC.parse(payload)
	if p.get("name"):
		doc = frappe.get_doc(IC.ADJUSTMENT, p.name)
		if cint(doc.docstatus) != 0:
			frappe.throw(_("{0} is already submitted.").format(p.name), title=_("Not A Draft"))
	else:
		doc = frappe.new_doc(IC.ADJUSTMENT)
	for f in ("posting_date", "adjustment_type", "reason_code", "warehouse", "admin_remarks"):
		doc.set(f, p.get(f))
	doc.posting_date = doc.posting_date or nowdate()
	doc.set("items", [])
	for r in p.get("items") or []:
		r = frappe._dict(r or {})
		if not r.get("item_code"):
			continue
		doc.append("items", {"item_code": r.item_code, "batch_no": r.get("batch_no") or None,
		                     "qty": flt(r.get("qty"))})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	if cint(submit):
		doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus, "approval_status": doc.approval_status}


@frappe.whitelist()
def submit_adjustment(name):
	IC.assert_roles(IC.ADJUSTMENT_WRITE_ROLES, _("submit an Inventory Adjustment"))
	doc = frappe.get_doc(IC.ADJUSTMENT, name)
	if cint(doc.docstatus) != 0:
		frappe.throw(_("{0} is not a draft.").format(name), title=_("Not A Draft"))
	doc.flags.ignore_permissions = True
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "approval_status": doc.approval_status}


def _pending(name):
	doc = frappe.get_doc(IC.ADJUSTMENT, name)
	if cint(doc.docstatus) != 1 or doc.approval_status != IC.ADJ_PENDING:
		frappe.throw(_("{0} is not waiting for approval.").format(name), title=_("Not Pending"))
	return doc


@frappe.whitelist()
def approve_adjustment(name):
	"""Plant Head approves: the Stock Entry is posted now (stock is re-checked)."""
	IC.assert_roles(IC.ADJUSTMENT_APPROVE_ROLES, _("approve an Inventory Adjustment"))
	doc = _pending(name)
	se = _post_adjustment(doc)
	doc.db_set("approved_by", frappe.session.user)
	doc.db_set("approved_on", now_datetime())
	IC.audit(doc.doctype, doc.name, "Approved", _("Ledger updated by Stock Entry {0}").format(se))
	try:
		from alpinos.production.notify import notify as _notify
		_notify([], _("Inventory Adjustment {0} approved by {1}.").format(doc.name, get_fullname()),
		        doctype=doc.doctype, name=doc.name, users=[doc.owner])
	except Exception:
		pass
	frappe.db.commit()
	return {"name": doc.name, "approval_status": IC.ADJ_POSTED, "stock_entry": se}


@frappe.whitelist()
def reject_adjustment(name, reason=None):
	"""Plant Head rejects: nothing is posted, the stock stays unchanged, audit logged."""
	IC.assert_roles(IC.ADJUSTMENT_APPROVE_ROLES, _("reject an Inventory Adjustment"))
	if not (reason or "").strip():
		frappe.throw(_("Please give a reason for rejecting."), title=_("Reason Required"))
	doc = _pending(name)
	doc.db_set("approval_status", IC.ADJ_REJECTED)
	doc.db_set("rejected_by", frappe.session.user)
	doc.db_set("rejected_on", now_datetime())
	doc.db_set("rejection_reason", reason.strip())
	IC.audit(doc.doctype, doc.name, "Rejected", _("Stock unchanged"), reason=reason.strip())
	try:
		from alpinos.production.notify import notify as _notify
		_notify([], _("Inventory Adjustment {0} rejected by {1}: {2}").format(
			doc.name, get_fullname(), reason.strip()), doctype=doc.doctype, name=doc.name,
			users=[doc.owner])
	except Exception:
		pass
	frappe.db.commit()
	return {"name": doc.name, "approval_status": IC.ADJ_REJECTED}


@frappe.whitelist()
def cancel_adjustment(name):
	IC.assert_roles(IC.ADJUSTMENT_WRITE_ROLES, _("cancel an Inventory Adjustment"))
	doc = frappe.get_doc(IC.ADJUSTMENT, name)
	if cint(doc.docstatus) != 1:
		frappe.throw(_("{0} is not submitted.").format(name), title=_("Not Submitted"))
	doc.flags.ignore_permissions = True
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name, "approval_status": IC.ADJ_CANCELLED}


@frappe.whitelist()
def delete_adjustment(name):
	IC.assert_roles(IC.ADJUSTMENT_WRITE_ROLES, _("delete an Inventory Adjustment"))
	if cint(frappe.db.get_value(IC.ADJUSTMENT, name, "docstatus")) != 0:
		frappe.throw(_("Only a draft can be deleted."), title=_("Not A Draft"))
	frappe.delete_doc(IC.ADJUSTMENT, name, ignore_permissions=True)
	frappe.db.commit()
	return {"deleted": name}
