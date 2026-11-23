"""Set up another company to work like Alpino Health Foods, bringing over the Item Master only.

Ancient Mills on UAT (Hetvi, 23 Nov 2026):
  "Replicate all existing modules from Alpino Health Foods Pvt. Ltd. to the Ancient Mills.
   Transfer only Item Master data and its related linked masters ... Do not migrate any other
   transactional or master data."

What it does for the target company (each step is skipped when already done, so it can be
run again):
  1. Series Code = its abbreviation, so its documents are numbered SOR-AM-2627-... and not in
     Alpino Health Foods' series (the rule every other company follows).
  2. Its own main warehouses: the warehouses the source items default to and Production
     Settings' main / WIP warehouse ("B2B Warehouse - 1 - AM", "Prod WIP - AM").
  3. A Production Settings row with those warehouses.
  4. Company defaults that point to an Account, Cost Center or Warehouse are filled with the
     target's own record of the same name; a Holiday List is shared. Text such as the print
     address, GSTIN and bank details is the company's own and is left alone.
  5. Its own price lists ("Standard Selling - AM", "Standard Buying - AM") with the source
     prices copied. Customer, supplier or batch specific prices are not copied.
  6. Every item of the source tagged to the target as well (same item codes, MRPs, UOMs,
     variants and bundle mappings), with an Item Default row whose warehouse / price list is
     the target's own.

Not touched: customers, suppliers, Buyer Masters, employees, users and their access, stock,
batches and every transaction. Item Groups, UOMs, HSN codes, Item Attributes and Product
Bundles are shared by all companies already.

Dry run (default) / apply:
  bench --site <site> execute alpinos.company_scope.replicate.run --kwargs '{"target": "Ancient Mills"}'
  bench --site <site> execute alpinos.company_scope.replicate.run --kwargs '{"target": "Ancient Mills", "apply": 1}'
"""

import frappe
from frappe.utils import cint, now

from alpinos.company_scope import registry
from alpinos.company_scope.tags import scope_string

SOURCE = "Alpino Health Foods Pvt. Ltd."

#: Source warehouse names that carry a typo of the source abbreviation in the name itself.
_CLEAN_NAMES = {"Prod WIP -AHFL": "Prod WIP"}

#: Item Price fields that point at another company's masters; such prices are not copied.
_PARTY_PRICE_FIELDS = ("customer", "supplier", "batch_no")

_ITEM_DEFAULT_FIELDS = (
	"default_warehouse", "default_price_list", "buying_cost_center", "selling_cost_center",
	"expense_account", "income_account", "default_supplier", "default_discount_account",
	"deferred_revenue_account", "deferred_expense_account", "default_provisional_account",
)


def run(target, source=SOURCE, apply=0):
	apply = cint(apply)
	if not frappe.db.exists("Company", target) or not frappe.db.exists("Company", source):
		frappe.throw(f"Company {target!r} or {source!r} not found.")
	if target == source:
		frappe.throw("Source and target are the same company.")
	ctx = frappe._dict(
		source=source, target=target, apply=apply,
		s_abbr=frappe.db.get_value("Company", source, "abbr"),
		t_abbr=frappe.db.get_value("Company", target, "abbr"),
		report={}, warehouse_map={}, price_list_map={},
	)
	real_commit = frappe.db.commit
	if not apply:
		# a dry run saves nothing, even where a hook commits on its own
		frappe.db.commit = lambda *a, **k: None
	try:
		_series_code(ctx)
		_warehouses(ctx)
		_production_settings(ctx)
		_company_defaults(ctx)
		_price_lists(ctx)
		_items(ctx)
	except Exception:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		raise
	frappe.db.commit = real_commit
	if apply:
		frappe.db.commit()
		frappe.clear_cache()
	else:
		frappe.db.rollback()
	ctx.report["mode"] = "applied" if apply else "dry run (nothing saved)"
	return ctx.report


# ── 1. numbering ─────────────────────────────────────────────────────────────
def _series_code(ctx):
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	code = (frappe.db.get_value("Company", ctx.target, "custom_series_code") or "").strip()
	if code or ctx.target == default:
		ctx.report["series_code"] = f"unchanged ({code or 'default company'})"
		return
	frappe.db.set_value("Company", ctx.target, "custom_series_code", ctx.t_abbr, update_modified=False)
	ctx.report["series_code"] = f"set to {ctx.t_abbr}"


# ── 2. warehouses ────────────────────────────────────────────────────────────
def _source_warehouses(ctx):
	"""The source warehouses the item defaults and Production Settings rely on."""
	names = set(frappe.db.sql_list(
		"""SELECT DISTINCT default_warehouse FROM `tabItem Default`
		   WHERE parenttype = 'Item' AND company = %s AND IFNULL(default_warehouse, '') != ''""",
		ctx.source,
	))
	for field in ("main_warehouse", "wip_warehouse", "baked_wip_warehouse", "fg_warehouse",
	              "fg_hold_warehouse", "rejected_warehouse"):
		value = frappe.db.get_single_value("Production Settings", field) if _has_single_field("Production Settings", field) else None
		if value and frappe.db.get_value("Warehouse", value, "company") == ctx.source:
			names.add(value)
	return sorted(names)


def _has_single_field(doctype, field):
	return bool(frappe.get_meta(doctype).get_field(field))


def _label(ctx, warehouse_name):
	"""A source warehouse's name without the source abbreviation some of them carry in the
	name itself ("B2B Warehouse - 1 - AHFPL" is its warehouse_name, not only its ID)."""
	label = _CLEAN_NAMES.get(warehouse_name, warehouse_name)
	suffix = f" - {ctx.s_abbr}"
	while label.endswith(suffix):
		label = label[: -len(suffix)]
	return _CLEAN_NAMES.get(label, label)


def _target_warehouse_for(ctx, source_wh):
	"""(name it has in the target, warehouse_name, parent) for a source warehouse."""
	src = frappe.db.get_value("Warehouse", source_wh, ["warehouse_name", "parent_warehouse", "warehouse_type", "is_group"], as_dict=True)
	label = _label(ctx, src.warehouse_name)
	name = f"{label} - {ctx.t_abbr}"
	parent = None
	if src.parent_warehouse:
		parent_label = frappe.db.get_value("Warehouse", src.parent_warehouse, "warehouse_name")
		candidate = f"{_label(ctx, parent_label)} - {ctx.t_abbr}"
		if frappe.db.exists("Warehouse", {"name": candidate, "company": ctx.target, "is_group": 1}):
			parent = candidate
	if not parent:
		parent = frappe.db.get_value("Warehouse", {"company": ctx.target, "is_group": 1, "parent_warehouse": ["in", ["", None]]}, "name")
	return name, label, parent, src


def _warehouses(ctx):
	created, existing = [], []
	for source_wh in _source_warehouses(ctx):
		name, label, parent, src = _target_warehouse_for(ctx, source_wh)
		ctx.warehouse_map[source_wh] = name
		if frappe.db.exists("Warehouse", name):
			existing.append(name)
			continue
		wh = frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": label, "company": ctx.target,
			"parent_warehouse": parent, "is_group": src.is_group, "warehouse_type": src.warehouse_type,
		})
		wh.flags.ignore_permissions = True
		wh.insert()
		if wh.name != name:
			ctx.warehouse_map[source_wh] = wh.name
		created.append(wh.name)
	ctx.report["warehouses"] = {"created": created, "already there": existing}


# ── 3. Production Settings ───────────────────────────────────────────────────
def _production_settings(ctx):
	ps = frappe.get_single("Production Settings")
	if not ps.meta.get_field("company_warehouses"):
		ctx.report["production_settings"] = "no per-company table"
		return
	if any(r.company == ctx.target for r in ps.company_warehouses):
		ctx.report["production_settings"] = "row already there"
		return
	row = {"company": ctx.target}
	for field in ("main_warehouse", "wip_warehouse", "baked_wip_warehouse", "fg_warehouse", "fg_hold_warehouse", "rejected_warehouse"):
		value = ps.get(field)
		if value and value in ctx.warehouse_map:
			row[field] = ctx.warehouse_map[value]
	ps.append("company_warehouses", row)
	ps.flags.ignore_permissions = True
	ps.save()
	ctx.report["production_settings"] = {k: v for k, v in row.items() if k != "company"}


# ── 4. Company defaults ──────────────────────────────────────────────────────
def _same_record(ctx, doctype, value):
	"""The target's own Account / Cost Center / Warehouse matching a source one, or None."""
	if doctype == "Warehouse":
		if value in ctx.warehouse_map:
			return ctx.warehouse_map[value]
		label = frappe.db.get_value("Warehouse", value, "warehouse_name")
		return frappe.db.get_value("Warehouse", f"{_label(ctx, label)} - {ctx.t_abbr}", "name") if label else None
	label_field = {"Account": "account_name", "Cost Center": "cost_center_name"}[doctype]
	label = frappe.db.get_value(doctype, value, label_field)
	return frappe.db.get_value(doctype, {label_field: label, "company": ctx.target}, "name") if label else None


def _company_defaults(ctx):
	source = frappe.get_doc("Company", ctx.source)
	target = frappe.get_doc("Company", ctx.target)
	filled, skipped = {}, []
	for df in source.meta.fields:
		if df.fieldtype != "Link" or df.options not in ("Account", "Cost Center", "Warehouse", "Holiday List"):
			continue
		value = source.get(df.fieldname)
		if not value or target.get(df.fieldname):
			continue
		mapped = value if df.options == "Holiday List" else _same_record(ctx, df.options, value)
		if mapped:
			filled[df.fieldname] = mapped
		else:
			skipped.append(df.fieldname)
	if filled:
		frappe.db.set_value("Company", ctx.target, filled, update_modified=False)
	ctx.report["company_defaults"] = {"filled": filled, "no matching record in target": skipped}


# ── 5. Price lists ───────────────────────────────────────────────────────────
def _tagged_to(doctype, company):
	return frappe.get_all(doctype, filters={registry.SCOPE_FIELD: ["like", f"%|{company}|%"]}, pluck="name")


def _tag_rows(doctype, name, companies):
	"""Add company tags to a tagged master straight in the child table (no full save)."""
	have = set(frappe.db.sql_list(
		f"SELECT company FROM `tab{registry.TAG_DOCTYPE}` WHERE parent = %s AND parenttype = %s", (name, doctype)
	))
	idx = len(have)
	stamp = now()
	for company in companies:
		if company in have:
			continue
		idx += 1
		frappe.get_doc({
			"doctype": registry.TAG_DOCTYPE, "parent": name, "parenttype": doctype, "parentfield": registry.TAG_FIELD,
			"company": company, "idx": idx, "owner": "Administrator", "modified_by": "Administrator",
			"creation": stamp, "modified": stamp,
		}).db_insert()
		have.add(company)
	frappe.db.set_value(doctype, name, registry.SCOPE_FIELD, scope_string(have), update_modified=False)


def _price_lists(ctx):
	out = {}
	copy_skip = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "price_list", "price_list_name"}
	for pl in _tagged_to("Price List", ctx.source):
		src = frappe.get_doc("Price List", pl)
		new_name = f"{pl} - {ctx.t_abbr}"
		ctx.price_list_map[pl] = new_name
		if not frappe.db.exists("Price List", new_name):
			doc = frappe.get_doc({
				"doctype": "Price List", "price_list_name": new_name, "currency": src.currency,
				"enabled": src.enabled, "buying": src.buying, "selling": src.selling,
				"price_not_uom_dependent": src.get("price_not_uom_dependent"),
				registry.TAG_FIELD: [{"company": ctx.target}],
			})
			doc.flags.ignore_permissions = True
			doc.insert()
		copied = skipped = already = 0
		for p in frappe.get_all("Item Price", filters={"price_list": pl}, fields=["*"]):
			if any(p.get(f) for f in _PARTY_PRICE_FIELDS):
				skipped += 1
				continue
			# a copy without a start date was given today's on insert, so match it on item and UOM
			same = {"price_list": new_name, "item_code": p.item_code, "uom": p.uom}
			if p.valid_from:
				same["valid_from"] = p.valid_from
			if frappe.db.exists("Item Price", same):
				already += 1
				continue
			values = {k: v for k, v in p.items() if k not in copy_skip}
			doc = frappe.get_doc({"doctype": "Item Price", **values, "price_list": new_name})
			doc.flags.ignore_permissions = True
			doc.insert()
			copied += 1
		out[new_name] = {"copied": copied, "already there": already, "customer / supplier / batch prices not copied": skipped}
	ctx.report["price_lists"] = out


# ── 6. Items ─────────────────────────────────────────────────────────────────
def _items(ctx):
	items = _tagged_to("Item", ctx.source)
	tagged = defaults = 0
	stamp = now()
	for name in items:
		scope = frappe.db.get_value("Item", name, registry.SCOPE_FIELD) or ""
		if f"|{ctx.target}|" not in scope:
			_tag_rows("Item", name, [ctx.target])
			tagged += 1
		if frappe.db.exists("Item Default", {"parent": name, "parenttype": "Item", "company": ctx.target}):
			continue
		src = frappe.db.get_value("Item Default", {"parent": name, "parenttype": "Item", "company": ctx.source},
		                          list(_ITEM_DEFAULT_FIELDS), as_dict=True) or {}
		row = {"company": ctx.target}
		if src.get("default_warehouse"):
			row["default_warehouse"] = ctx.warehouse_map.get(src.default_warehouse)
		if src.get("default_price_list"):
			row["default_price_list"] = ctx.price_list_map.get(src.default_price_list)
		for field, doctype in (("buying_cost_center", "Cost Center"), ("selling_cost_center", "Cost Center"),
		                       ("expense_account", "Account"), ("income_account", "Account"),
		                       ("default_discount_account", "Account"), ("deferred_revenue_account", "Account"),
		                       ("deferred_expense_account", "Account"), ("default_provisional_account", "Account")):
			if src.get(field):
				row[field] = _same_record(ctx, doctype, src.get(field))
		idx = frappe.db.count("Item Default", {"parent": name, "parenttype": "Item"}) + 1
		frappe.get_doc({
			"doctype": "Item Default", "parent": name, "parenttype": "Item", "parentfield": "item_defaults",
			"idx": idx, "owner": "Administrator", "modified_by": "Administrator", "creation": stamp, "modified": stamp,
			**{k: v for k, v in row.items() if v},
		}).db_insert()
		defaults += 1
	for name in items:
		frappe.clear_document_cache("Item", name)
	ctx.report["items"] = {"source items": len(items), "tagged to target": tagged, "item default rows added": defaults}
