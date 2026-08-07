# Bulk-restore Sales Orders from a Frappe report-export CSV, preserving the exact
# Sales Order ID (name), stored values, docstatus and Workflow Status.
#
# "Force exact" restore: fields are set straight from the CSV and the doc is inserted
# with validation/recompute bypassed, so rate/amount/tax/totals stay exactly as
# exported. Submitted orders are flipped to docstatus 1 (Cancelled to 2) directly,
# WITHOUT running submit side effects (no stock reservation / workflow engine / email).
#
# Fresh-create only: any ID that already exists is reported and skipped (never
# overwritten). Dry run by default.
#
#   bench --site <site> execute alpinos.so_bulk_restore.run --kwargs "{'csv_path': '/path/Sales Order (9).csv'}"
#   bench --site <site> execute alpinos.so_bulk_restore.run --kwargs "{'csv_path': '...', 'apply': 1}"

import csv
import re

import frappe
from frappe.utils import cint, flt

PARENT_DT = "Sales Order"

# CSV child-table suffix -> child doctype
CHILD_TABLES = {
	"Order Items": "Sales Order Item",
	"Sales Taxes and Charges": "Sales Taxes and Charges",
	"Marketing Freebies": "Sales Order Marketing Freebie",
	"Scheme Items": "Sales Order Scheme Item",
	"Additional Units - Damage Items": "Sales Order Additional Units Item",
	"Payment Schedule": "Payment Schedule",
}
# a child row exists on a CSV line when this (suffix-stripped) column is non-empty
CHILD_KEY = {
	"Order Items": "SKU",
	"Sales Taxes and Charges": "Account Head",
	"Marketing Freebies": "Item",
	"Scheme Items": "SKU",
	"Additional Units - Damage Items": "SKU",
	"Payment Schedule": "Payment Term",
}
# CSV item-column label -> Sales Order Item fieldname (labels that don't round-trip)
ITEM_LABEL_OVERRIDE = {"Delivery Warehouse": "warehouse"}

# never set these from the CSV — handled specially or system-managed
SKIP_FIELDS = {
	"name", "docstatus", "status", "idx", "owner", "creation", "modified",
	"modified_by", "amended_from", "_user_tags", "_comments", "_assign",
	"_liked_by", "_seen",
}

# parent monetary fields force-written after insert (belt-and-suspenders vs any
# before_save recompute); only those present in the CSV are written
FORCE_PARENT = [
	"total", "base_total", "net_total", "base_net_total",
	"total_taxes_and_charges", "base_total_taxes_and_charges",
	"grand_total", "base_grand_total", "rounded_total", "base_rounded_total",
	"rounding_adjustment", "base_rounding_adjustment", "total_qty",
]


def _fieldmap(dt):
	"""label -> (fieldname, fieldtype) for non-layout, non-table fields."""
	fm = {}
	for df in frappe.get_meta(dt).fields:
		if df.fieldtype in ("Section Break", "Column Break", "HTML", "Tab Break", "Button", "Table", "Table MultiSelect"):
			continue
		if df.label:
			fm.setdefault(df.label, (df.fieldname, df.fieldtype))
	return fm


def _to_ymd(v):
	v = (v or "").strip()
	if not v:
		return None
	datepart = v.split(" ")[0]
	m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", datepart)
	if m:  # DD-MM-YYYY -> YYYY-MM-DD (keep any time component)
		ymd = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
		return ymd + v[len(datepart):]
	return v


def _coerce(fieldtype, val):
	if val is None or str(val).strip() == "":
		return None
	if fieldtype in ("Int", "Check"):
		return cint(val)
	if fieldtype in ("Float", "Currency", "Percent"):
		return flt(val)
	if fieldtype in ("Date", "Datetime"):
		return _to_ymd(val)
	return val


def _load(csv_path):
	with open(csv_path, newline="", encoding="utf-8-sig") as fh:
		rows = list(csv.reader(fh))
	return rows[0], rows[1:]


def _group(hdr, data):
	ci = {c: i for i, c in enumerate(hdr)}
	id_i = ci.get("ID")
	groups, cur = [], None
	for r in data:
		idv = (r[id_i] if id_i is not None and id_i < len(r) else "").strip()
		if idv:
			cur = {"id": idv, "rows": [r]}
			groups.append(cur)
		elif cur:
			cur["rows"].append(r)
	return ci, groups


def _child_col_index(hdr, suffix, child_map):
	"""For one child suffix: {csv_col_index -> fieldname} + key-column index."""
	cols, key_i = {}, None
	key_label = CHILD_KEY[suffix]
	for i, c in enumerate(hdr):
		m = re.match(r"^(.*) \(" + re.escape(suffix) + r"\)$", c)
		if not m:
			continue
		label = m.group(1)
		if label == "ID":
			continue
		if label == key_label:
			key_i = i
		fn = ITEM_LABEL_OVERRIDE.get(label) if suffix == "Order Items" else None
		fn = fn or (child_map.get(label) or (None, None))[0]
		ft = (child_map.get(label) or (None, None))[1]
		if fn and fn not in SKIP_FIELDS:
			cols[i] = (fn, ft)
	return cols, key_i


def run(csv_path, apply=0, limit=None):
	apply = cint(apply)
	limit = cint(limit) if limit else None
	hdr, data = _load(csv_path)
	ci, groups = _group(hdr, data)
	if limit:
		groups = groups[:limit]

	parent_map = _fieldmap(PARENT_DT)
	# parent column index -> (fieldname, fieldtype) for non-child columns
	child_suffixes = set(CHILD_TABLES) | {"Sticker Attachments", "Packed Items", "Pricing Rule Detail", "Sales Team"}
	parent_cols = {}
	for i, c in enumerate(hdr):
		m = re.match(r"^.* \(([^()]+)\)$", c)
		if m and m.group(1) in child_suffixes:
			continue
		fld = parent_map.get(c)
		if fld and fld[0] not in SKIP_FIELDS:
			parent_cols[i] = fld
	# child column maps
	child_maps = {}
	for suf, dt in CHILD_TABLES.items():
		cols, key_i = _child_col_index(hdr, suf, _fieldmap(dt))
		child_maps[suf] = {"table_field": _table_field(suf), "cols": cols, "key_i": key_i, "dt": dt}

	# ---- pre-flight: conflicts + missing masters ----
	existing, missing = [], {"Customer": set(), "Item": set(), "Warehouse": set(),
							 "Buyer Master": set(), "Sales Taxes and Charges Template": set(),
							 "Alpino Customer Type": set()}
	status_ct = {}
	for gp in groups:
		if frappe.db.exists("Sales Order", gp["id"]):
			existing.append(gp["id"])
		prow = gp["rows"][0]
		st = (prow[ci["Status"]] if "Status" in ci else "").strip()
		status_ct[st] = status_ct.get(st, 0) + 1
		_collect_missing(gp, ci, child_maps, missing)

	print(f"orders: {len(groups)} | status: {status_ct}")
	if existing:
		print(f"ALREADY EXIST (will be skipped): {len(existing)} -> {existing[:10]}{'...' if len(existing)>10 else ''}")
	for dt, s in missing.items():
		s = sorted(x for x in s if x)
		if s:
			print(f"MISSING {dt} in this site ({len(s)}): {s[:15]}{'...' if len(s)>15 else ''}")

	if not apply:
		total_gt = sum(flt(gp["rows"][0][ci["Grand Total"]]) for gp in groups if "Grand Total" in ci and gp["rows"][0][ci["Grand Total"]])
		print(f"\nDRY RUN: would create {len(groups)-len(existing)} order(s) "
			  f"(skipping {len(existing)} existing), total grand ~{round(total_gt,2)}. "
			  "Re-run with 'apply': 1 to write.")
		return

	created, skipped, failed = 0, 0, []
	for gp in groups:
		if gp["id"] in existing:
			skipped += 1
			continue
		try:
			_create_one(gp, ci, parent_cols, child_maps)
			created += 1
		except Exception as e:
			failed.append((gp["id"], str(e)[:150]))
			frappe.db.rollback()
	frappe.db.commit()
	print(f"\nAPPLIED: created {created}, skipped {skipped} existing, failed {len(failed)}.")
	for fid, err in failed:
		print("  FAILED", fid, "->", err)


def _table_field(suffix):
	for df in frappe.get_meta(PARENT_DT).fields:
		if df.fieldtype in ("Table", "Table MultiSelect") and df.label == suffix:
			return df.fieldname
	return None


def _collect_missing(gp, ci, child_maps, missing):
	prow = gp["rows"][0]
	def val(col):
		return (prow[ci[col]] if col in ci and ci[col] < len(prow) else "").strip()
	for col, dt in [("Customer", "Customer"), ("Buyer Master", "Buyer Master"),
					("Sales Taxes and Charges Template", "Sales Taxes and Charges Template"),
					("Customer Type", "Alpino Customer Type")]:
		v = val(col)
		if v and not frappe.db.exists(dt if dt != "Sales Taxes and Charges Template" else "Sales Taxes and Charges Template", v):
			missing[dt].add(v)
	# items + warehouses
	im = child_maps["Order Items"]
	sku_i = None
	wh_i = None
	for i, (fn, ft) in im["cols"].items():
		if fn == "item_code":
			sku_i = i
		if fn == "warehouse":
			wh_i = i
	for r in gp["rows"]:
		if sku_i is not None and sku_i < len(r) and r[sku_i].strip():
			if not frappe.db.exists("Item", r[sku_i].strip()):
				missing["Item"].add(r[sku_i].strip())
		if wh_i is not None and wh_i < len(r) and r[wh_i].strip():
			if not frappe.db.exists("Warehouse", r[wh_i].strip()):
				missing["Warehouse"].add(r[wh_i].strip())


def _create_one(gp, ci, parent_cols, child_maps):
	prow = gp["rows"][0]
	doc = frappe.new_doc(PARENT_DT)

	# parent scalar fields
	for i, (fn, ft) in parent_cols.items():
		if i >= len(prow):
			continue
		v = _coerce(ft, prow[i])
		if v is not None:
			doc.set(fn, v)

	# child rows
	status = (prow[ci["Status"]] if "Status" in ci else "").strip()
	for suf, cfg in child_maps.items():
		tf, cols, key_i = cfg["table_field"], cfg["cols"], cfg["key_i"]
		if not tf or key_i is None:
			continue
		doc.set(tf, [])
		for r in gp["rows"]:
			if key_i >= len(r) or not r[key_i].strip():
				continue
			row = {}
			for i, (fn, ft) in cols.items():
				if i < len(r):
					v = _coerce(ft, r[i])
					if v is not None:
						row[fn] = v
			if row:
				doc.append(tf, row)

	# preserve the exact name + skip all recompute / validation / link checks
	doc.name = gp["id"]
	doc.flags.name_set = True
	doc.flags.ignore_validate = True
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	doc.flags.ignore_permissions = True
	doc.insert()

	# force exact parent monetary values (in case a before_save touched them)
	force = {}
	for i, (fn, ft) in parent_cols.items():
		if fn in FORCE_PARENT and i < len(prow):
			v = _coerce(ft, prow[i])
			if v is not None:
				force[fn] = v
	if force:
		frappe.db.set_value(PARENT_DT, doc.name, force, update_modified=False)

	# docstatus + status + workflow, matching the export (no submit side effects)
	target_ds = {"Draft": 0, "Cancelled": 2}.get(status, 1)
	wf = (prow[ci["Workflow Status"]] if "Workflow Status" in ci else "").strip()
	frappe.db.set_value(PARENT_DT, doc.name,
						{"docstatus": target_ds, "status": status or None,
						 "custom_workflow_status": wf or None}, update_modified=False)
	if target_ds != 0:
		for df in doc.meta.get_table_fields():
			frappe.db.sql(
				f"UPDATE `tab{df.options}` SET docstatus=%s WHERE parent=%s AND parenttype=%s",
				(target_ds, doc.name, PARENT_DT),
			)
