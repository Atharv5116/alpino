"""Python API for the Offline Buyer Catalog page."""

import json

import frappe
from frappe.utils import flt, now_datetime

ALLOWED_OFFLINE_BUYER_ITEM_GROUPS = [
	"Super Vital",
	"SuperOne",
	"Vinegar",
	"Peanut Crackers",
	"Cornflakes",
	"Protein",
	"Peanut Butter",
	"Oats",
	"Muesli",
	"Bar",
]


@frappe.whitelist()
def get_all_records():
	"""Return all Offline Buyer Items records for the list view (incl. Offline Buyer Master context)."""
	records = frappe.db.sql(
		"""
		SELECT
			obi.name,
			obi.title,
			obi.buyer,
			obi.modified,
			(
				SELECT COUNT(obil.name)
				FROM `tabOffline Buyer Item` obil
				WHERE obil.parent = obi.name
			) AS item_count,
			obm.site_name,
			obm.customer,
			obm.customer_business_name,
			obm.customer_type,
			obm.payment_term,
			obm.payment_term_days,
			obm.party_owner
		FROM `tabOffline Buyer Items` obi
		LEFT JOIN `tabOffline Buyer Master` obm ON obm.name = obi.buyer
		ORDER BY obi.modified DESC
		""",
		as_dict=True,
	)
	return records


@frappe.whitelist()
def get_buyer_items(record_name):
	"""Return every active sales item merged with saved data from a specific record.

	Each row: item_code, item_name, item_group, mrp, margin_percent, selling_rate, selected
	"""
	# All active, saleable items from Item master
	items = frappe.get_all(
		"Item",
		filters={
			"disabled": 0,
			"is_sales_item": 1,
			"variant_of": ["!=", ""],
		},
		fields=["name", "item_name", "item_group", "standard_rate", "variant_of"],
		order_by="item_group, item_name",
	)

	# Load saved rows from the specific record (keyed by item_code)
	saved: dict = {}
	if frappe.db.exists("Offline Buyer Items", record_name):
		doc = frappe.get_doc("Offline Buyer Items", record_name)
		for row in doc.get("items") or []:
			if row.item_code:
				saved[row.item_code] = row

	result = []
	for item in items:
		row = saved.get(item.name)
		mrp = flt(row.mrp if row else item.standard_rate)
		margin_pct = flt(row.margin_percent if row else 0)
		selling_rate = flt(mrp * (1 - margin_pct / 100), 2) if mrp else 0

		result.append(
			{
				"item_code": item.name,
				"item_name": item.item_name,
				"item_group": item.item_group or "",
				"mrp": mrp,
				"margin_percent": margin_pct,
				"selling_rate": selling_rate,
				"selected": bool(row),
			}
		)

	return result


@frappe.whitelist()
def save_buyer_items(record_name, items):
	"""Save selected items back to the specified Offline Buyer Items record."""
	if isinstance(items, str):
		items = json.loads(items)

	if not frappe.db.exists("Offline Buyer Items", record_name):
		frappe.throw(f"Record {record_name} not found")

	doc = frappe.get_doc("Offline Buyer Items", record_name)
	doc.set("items", [])

	for item in items:
		if not item.get("selected"):
			continue
		mrp = flt(item.get("mrp", 0))
		margin_pct = flt(item.get("margin_percent", 0))
		selling_rate = flt(mrp * (1 - margin_pct / 100), 2) if mrp else 0

		doc.append(
			"items",
			{
				"item_code": item["item_code"],
				"item_name": item.get("item_name", ""),
				"item_group": item.get("item_group", ""),
				"mrp": mrp,
				"margin_percent": margin_pct,
				"selling_rate": selling_rate,
			},
		)

	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"saved": len(doc.items)}


@frappe.whitelist()
def create_record(title, buyer=None, description=None):
	"""Create a new Offline Buyer Items record and return its name."""
	doc = frappe.new_doc("Offline Buyer Items")
	doc.title = title
	if buyer:
		doc.buyer = buyer
	if description:
		doc.description = description
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


@frappe.whitelist()
def get_parent_group_filter_data(item_groups):
	"""For catalog rows, return parent Item Groups and each parent's subtree (all descendant group names).

	Used by Offline Buyer Catalog: filter by Parent Item Group so items in any child group match.
	"""
	if isinstance(item_groups, str):
		item_groups = json.loads(item_groups)
	item_groups = list({g for g in item_groups if g})
	if not item_groups:
		return {"parents": [], "descendants_map": {}}

	leaf_rows = frappe.db.sql(
		"""
		SELECT name, lft, rgt FROM `tabItem Group`
		WHERE name IN %s
		""",
		(item_groups,),
		as_dict=True,
	)
	if not leaf_rows:
		return {"parents": [], "descendants_map": {}}

	meta = frappe.get_meta("Item Group")
	has_is_group = meta.has_field("is_group")

	ancestors = set()
	for row in leaf_rows:
		if has_is_group:
			names = frappe.db.sql(
				"""
				SELECT name FROM `tabItem Group`
				WHERE lft <= %(lft)s AND rgt >= %(rgt)s AND IFNULL(`is_group`, 0) = 1
				""",
				{"lft": row.lft, "rgt": row.rgt},
				pluck="name",
			)
		else:
			names = frappe.db.sql(
				"""
				SELECT ig.name FROM `tabItem Group` ig
				INNER JOIN `tabItem Group` leaf ON leaf.name = %(leaf)s
				WHERE ig.lft <= leaf.lft AND ig.rgt >= leaf.rgt AND ig.name != leaf.name
				""",
				{"leaf": row.name},
				pluck="name",
			)
		ancestors.update(names)

	parents = sorted(ancestors)
	descendants_map = {}
	for name in parents:
		root = frappe.db.get_value("Item Group", name, ["lft", "rgt"], as_dict=True)
		if not root:
			continue
		descendants_map[name] = frappe.get_all(
			"Item Group",
			filters={"lft": [">=", root.lft], "rgt": ["<=", root.rgt]},
			pluck="name",
		)

	return {"parents": parents, "descendants_map": descendants_map}


@frappe.whitelist()
def get_allowed_item_groups():
	"""Return the fixed list of item groups allowed in Offline Buyer Margin."""
	return ALLOWED_OFFLINE_BUYER_ITEM_GROUPS


@frappe.whitelist()
def get_variant_items_for_group(item_group):
	"""Return variant items for selected group and all descendant groups."""
	if not item_group:
		return []

	if item_group not in ALLOWED_OFFLINE_BUYER_ITEM_GROUPS:
		frappe.throw(f"Item Group '{item_group}' is not allowed for Offline Buyer Margin")

	root = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not root:
		return []

	group_names = frappe.get_all(
		"Item Group",
		filters={
			"lft": [">=", root.lft],
			"rgt": ["<=", root.rgt],
		},
		pluck="name",
	)
	if not group_names:
		return []

	return frappe.get_all(
		"Item",
		filters={
			"disabled": 0,
			"variant_of": ["!=", ""],
			"item_group": ["in", group_names],
		},
		fields=["name", "item_name", "item_group", "variant_of"],
		order_by="item_group asc, item_name asc",
		limit_page_length=2000,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def party_owner_user_query(doctype, txt, searchfield, start, page_len, filters):
	"""Party Owner: only enabled Users tied to Sales Person (via Employee), or Sales roles as fallback."""
	doctype = "User"
	txt = txt or ""

	if frappe.db.exists("DocType", "Sales Person") and frappe.db.exists("DocType", "Employee"):
		rows = frappe.db.sql(
			"""
			SELECT DISTINCT u.name, u.full_name
			FROM `tabUser` u
			INNER JOIN `tabEmployee` e ON e.user_id = u.name AND IFNULL(e.status, 'Active') = 'Active'
			INNER JOIN `tabSales Person` sp ON sp.employee = e.name
				AND IFNULL(sp.enabled, 1) = 1
				AND IFNULL(sp.is_group, 0) = 0
			WHERE IFNULL(u.enabled, 0) = 1
				AND IFNULL(u.user_type, 'System User') = 'System User'
				AND (u.name LIKE %(txt)s OR IFNULL(u.full_name, '') LIKE %(txt)s)
			ORDER BY u.full_name ASC
			LIMIT %(page_len)s OFFSET %(start)s
			""",
			{"txt": f"%{txt}%", "start": int(start), "page_len": int(page_len)},
		)
		if rows:
			return rows

	return frappe.db.sql(
		"""
		SELECT DISTINCT u.name, u.full_name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
		WHERE hr.role IN ('Sales User', 'Sales Manager')
			AND IFNULL(u.enabled, 0) = 1
			AND (u.name LIKE %(txt)s OR IFNULL(u.full_name, '') LIKE %(txt)s)
		ORDER BY u.full_name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{"txt": f"%{txt}%", "start": int(start), "page_len": int(page_len)},
	)
