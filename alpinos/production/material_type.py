"""What kind of item is this? Answered from the Item Group, not from a field on the Item.

An item is RM, PM, Additive or FG according to where its Item Group sits in the group tree:

    Raw Material         -> RM
    Packaging Material   -> PM
    Additive             -> Additive
    Finished Goods       -> FG

The group itself or any ancestor may carry one of those four names (Finished Goods > Oats >
Super Oats makes an item in Super Oats an FG); the nearest one wins. A group outside all four
(Marketing Material, Combos) gives "", the same "unclassified" the module has always treated a
blank Material Type as.

The old Item field `custom_material_type` is hidden and nothing reads it any more. Documents
that copied the type onto their own rows (BOM Item, Material Request Item, Stock Entry Detail,
Production Order Item) keep those copies as a snapshot of what the item was when the row was
made; new rows are filled from here.

SQL that used to compare `custom_material_type` uses `sql_type_expr()` / `sql_in_types()`, which
turn the same answer into a condition on `item_group`.
"""

import frappe
from frappe.utils import cstr

RM = "RM"
PM = "PM"
ADDITIVE = "Additive"
FG = "FG"
ALL = (RM, PM, ADDITIVE, FG)

#: The four category groups, by normalised name.
GROUP_NAMES = {
	"raw material": RM,
	"raw materials": RM,
	"packaging material": PM,
	"packaging materials": PM,
	"packing material": PM,
	"additive": ADDITIVE,
	"additives": ADDITIVE,
	"finished goods": FG,
	"finished good": FG,
}

#: The groups to create when missing, with their parent. Raw Material and Finished Goods
#: normally exist already.
CATEGORY_GROUPS = (
	("Raw Material", RM),
	("Packaging Material", PM),
	("Additive", ADDITIVE),
	("Finished Goods", FG),
)


def _norm(name):
	return " ".join(cstr(name).lower().split())


def group_types():
	"""{item group name: type} for every group that sits under (or is) a category group."""
	groups = frappe.db.sql("select name, lft, rgt from `tabItem Group` order by lft", as_dict=True)
	roots = [(g.lft, g.rgt, GROUP_NAMES[_norm(g.name)]) for g in groups if _norm(g.name) in GROUP_NAMES]
	out = {}
	for g in groups:
		best = None
		for lft, rgt, kind in roots:
			# the tightest enclosing category group (largest lft) is the nearest ancestor
			if lft <= g.lft and g.rgt <= rgt and (best is None or lft > best[0]):
				best = (lft, kind)
		if best:
			out[g.name] = best[1]
	return out


def type_of_group(item_group, _map=None):
	"""'RM' / 'PM' / 'Additive' / 'FG', or '' for a group outside the four categories."""
	if not item_group:
		return ""
	return (_map if _map is not None else group_types()).get(item_group, "")


def item_types(item_codes):
	"""{item code: type} for each code (unclassified -> ""), in one query."""
	codes = [c for c in set(item_codes or []) if c]
	if not codes:
		return {}
	gmap = group_types()
	return {
		r.name: type_of_group(r.item_group, gmap)
		for r in frappe.get_all("Item", filters={"name": ("in", codes)}, fields=["name", "item_group"])
	}


def item_type(item_code):
	return item_types([item_code]).get(item_code, "") if item_code else ""


def doc_type(item_doc):
	"""The type of an Item document (or any doc with `item_group`), without reloading it."""
	return type_of_group(item_doc.get("item_group")) if item_doc else ""


def groups_of_type(*types):
	"""Every Item Group whose items are of one of `types` (all four when none given)."""
	wanted = set(types or ALL)
	return sorted(g for g, t in group_types().items() if t in wanted)


# ------------------------------------------------------------------------------- SQL

def sql_in_types(alias, *types):
	"""A SQL condition: the item's group is one of `types`. `alias` is the Item table alias."""
	groups = groups_of_type(*types)
	if not groups:
		return "0"
	return "{}.item_group in ({})".format(alias, ", ".join(frappe.db.escape(g) for g in groups))


def sql_type_expr(alias):
	"""A SQL expression giving each item's type ('' when unclassified)."""
	gmap = group_types()
	by_type = {}
	for g, t in gmap.items():
		by_type.setdefault(t, []).append(g)
	if not by_type:
		return "''"
	whens = " ".join(
		"when {}.item_group in ({}) then {}".format(
			alias, ", ".join(frappe.db.escape(g) for g in sorted(groups)), frappe.db.escape(kind)
		)
		for kind, groups in by_type.items()
	)
	return "(case {} else '' end)".format(whens)


# --------------------------------------------------------------------------- setup / UI

def ensure_category_groups():
	"""Create the four category groups that are missing, under "All Item Groups".

	Only ever adds: an existing group is not touched, and no item is moved.
	"""
	root = frappe.db.get_value("Item Group", {"parent_item_group": ["is", "not set"], "is_group": 1}, "name") or "All Item Groups"
	existing = {_norm(n) for n in frappe.get_all("Item Group", pluck="name")}
	for name, kind in CATEGORY_GROUPS:
		if any(GROUP_NAMES.get(n) == kind for n in existing):
			continue
		frappe.get_doc({
			"doctype": "Item Group", "item_group_name": name, "parent_item_group": root, "is_group": 1,
		}).insert(ignore_permissions=True)
		existing.add(_norm(name))


@frappe.whitelist()
def get_group_type(item_group=None):
	"""For the Item form: which category does this Item Group belong to?"""
	return type_of_group(item_group)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link search: enabled items filed under the Item Groups of the given types.

	filters = {"types": ["RM", "Additive"]}. Used where a picker used to filter Item on
	custom_material_type.
	"""
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	types = filters.get("types") or ALL
	groups = groups_of_type(*types)
	if not groups:
		return []
	txt = "%{}%".format(txt or "")
	return frappe.db.sql(
		"""select name, item_name from `tabItem`
		where disabled = 0 and item_group in %(groups)s
		  and (name like %(txt)s or item_name like %(txt)s)
		order by name limit %(start)s, %(page_len)s""",
		{"groups": tuple(groups), "txt": txt, "start": int(start or 0), "page_len": int(page_len or 20)},
	)
