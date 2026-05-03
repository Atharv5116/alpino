"""Python API for the Offline Buyer Catalog page."""

import json

import frappe
from frappe import _
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
			IFNULL(bcust.customer_name, '') AS buyer_customer_name,
			obi.modified,
			(
				SELECT COUNT(obil.name)
				FROM `tabOffline Buyer Item` obil
				WHERE obil.parent = obi.name
			) AS item_count,
			obm.name AS offline_buyer_master,
			obm.site_name,
			obm.customer,
			obm.customer_business_name,
			obm.customer_type,
			obm.payment_term,
			obm.payment_term_days,
			obm.party_owner
		FROM `tabOffline Buyer Items` obi
		LEFT JOIN `tabCustomer` bcust ON bcust.name = obi.buyer
		LEFT JOIN `tabOffline Buyer Master` obm ON obm.customer = obi.buyer
		ORDER BY obi.modified DESC
		""",
		as_dict=True,
	)
	return records


@frappe.whitelist()
def get_buyer_items(record_name):
	"""Return active variant items for the catalog grid, merged with saved rows and Offline Buyer Master margins.

	When this catalog's **buyer** (Customer) has an Offline Buyer Master with margin rows, the page only lists
	SKUs that appear on that master (plus any SKUs already saved on this catalog). Default **margin %** and
	**MRP** match the master (and Sales Order Entry): MRP from Item ``standard_rate``, margin from
	``Offline Buyer Margin``; saved child rows still win if present.
	"""
	# All active, saleable variant items from Item master
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

	saved: dict = {}
	buyer = None
	if frappe.db.exists("Offline Buyer Items", record_name):
		doc = frappe.get_doc("Offline Buyer Items", record_name)
		buyer = doc.buyer
		for row in doc.get("items") or []:
			if row.item_code:
				saved[row.item_code] = row

	obm_margin_by_sku: dict = {}
	if buyer:
		obm_name = frappe.db.get_value("Offline Buyer Master", {"customer": buyer}, "name")
		if obm_name:
			for r in frappe.get_all(
				"Offline Buyer Margin",
				filters={"parent": obm_name, "parenttype": "Offline Buyer Master"},
				fields=["sku", "margin_percent"],
			):
				if r.sku:
					obm_margin_by_sku[r.sku] = flt(r.margin_percent)

	# Restrict grid to master SKUs (+ saved lines) when the master defines at least one margin row
	allowed_skus = None
	if obm_margin_by_sku:
		allowed_skus = set(obm_margin_by_sku.keys()) | set(saved.keys())

	result = []
	for item in items:
		if allowed_skus is not None and item.name not in allowed_skus:
			continue
		row = saved.get(item.name)
		mrp = flt(row.mrp if row else item.standard_rate)
		if row:
			margin_pct = flt(row.margin_percent)
		else:
			margin_pct = flt(obm_margin_by_sku.get(item.name, 0))
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
def create_record(title, buyer=None, offline_buyer_master=None, description=None):
	"""Create a new Offline Buyer Items record and return its name.

	Prefer ``offline_buyer_master`` (desk page): resolves to the auto-created Customer on that master.
	Legacy ``buyer`` (Customer name) is still accepted for API callers.
	"""
	cust = None
	if offline_buyer_master:
		cust = frappe.db.get_value("Offline Buyer Master", offline_buyer_master, "customer")
		if not cust:
			# Customer not yet linked — auto-save OBM to trigger customer creation
			obm_doc = frappe.get_doc("Offline Buyer Master", offline_buyer_master)
			obm_doc.save(ignore_permissions=True)
			frappe.db.commit()
			cust = obm_doc.customer
		if not cust:
			frappe.throw(
				_("Could not auto-create a Customer for Offline Buyer Master {0}. Please open the record and save it manually.").format(
					frappe.bold(offline_buyer_master)
				)
			)
	elif buyer:
		cust = buyer
	if not cust:
		frappe.throw(_("Choose an Offline Buyer Master (or Customer) for this catalog."))

	if not offline_buyer_master and not frappe.db.exists("Offline Buyer Master", {"customer": cust}):
		frappe.throw(_("The selected Customer must have an Offline Buyer Master."))

	doc = frappe.new_doc("Offline Buyer Items")
	doc.title = title
	doc.buyer = cust
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


@frappe.whitelist()
def get_offline_buyer_master_details(obm_name):
	"""Return all editable fields of an Offline Buyer Master for the catalog edit dialog."""
	doc = frappe.get_doc("Offline Buyer Master", obm_name)
	return {
		"customer_business_name": doc.customer_business_name,
		"site_name": doc.site_name or "",
		"customer_type": doc.customer_type or "",
		"gst_type": doc.gst_type or "",
		"gst_no": doc.gst_no or "",
		"pan_no": doc.pan_no or "",
		"payment_term": doc.payment_term or "",
		"payment_term_days": doc.payment_term_days,
		"email": doc.email or "",
		"contact_no": doc.contact_no or "",
		"alternate_no": doc.alternate_no or "",
		"contact_person": doc.contact_person or "",
		"shipping_same_as_profile": int(doc.shipping_same_as_profile or 0),
		"addresses": [
			{
				"address_label": r.get("address_label") or "",
				"address_line": r.address_line or "",
				"pincode": r.pincode or "",
				"country": r.country or "",
				"state": r.state or "",
				"city": r.city or "",
				"area": r.area or "",
				"sub_area": r.get("sub_area") or "",
				"is_primary": int(r.get("is_primary") or 0),
				"is_shipping": int(r.get("is_shipping") or 0),
			}
			for r in (doc.addresses or [])
		],
	}


@frappe.whitelist()
def update_offline_buyer_master(obm_name, updates, addresses):
	"""Save scalar fields and the full addresses child table for an Offline Buyer Master."""
	import json as _json

	if isinstance(updates, str):
		updates = _json.loads(updates)
	if isinstance(addresses, str):
		addresses = _json.loads(addresses)

	doc = frappe.get_doc("Offline Buyer Master", obm_name)

	editable = [
		"customer_business_name", "site_name", "customer_type", "level", "gst_type",
		"gst_no", "pan_no", "payment_term", "payment_term_days",
		"email", "contact_no", "alternate_no", "contact_person",
		"shipping_same_as_profile",
	]
	for f in editable:
		if f in updates:
			doc.set(f, updates[f])

	# Replace entire addresses child table
	doc.addresses = []
	for addr in addresses:
		doc.append("addresses", {
			"address_label": addr.get("address_label") or "",
			"address_line": addr.get("address_line") or "",
			"pincode": addr.get("pincode") or "",
			"country": addr.get("country") or "",
			"state": addr.get("state") or "",
			"city": addr.get("city") or "",
			"area": addr.get("area") or "",
			"sub_area": addr.get("sub_area") or "",
			"is_primary": int(addr.get("is_primary") or 0),
			"is_shipping": int(addr.get("is_shipping") or 0),
		})

	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return doc.customer_business_name


@frappe.whitelist()
def quick_create_offline_buyer(
	business_name,
	customer_type,
	gst_type,
	payment_term,
	email,
	contact_no,
	contact_person,
	address_line,
	pincode,
	country,
	state,
	city,
	area,
	site_name=None,
	level=None,
):
	"""Create a minimal Offline Buyer Master from the Catalog quick-create dialog.

	Returns the new OBM name so the caller can pre-fill the catalog form.
	"""
	obm = frappe.new_doc("Offline Buyer Master")
	obm.customer_business_name = (business_name or "").strip()
	obm.site_name = (site_name or "").strip()
	obm.customer_type = customer_type
	obm.level = level or ""
	obm.gst_type = gst_type
	obm.payment_term = payment_term
	obm.email = email
	obm.contact_no = contact_no
	obm.contact_person = contact_person

	obm.append(
		"addresses",
		{
			"is_primary": 1,
			"address_line": address_line,
			"pincode": pincode,
			"country": country,
			"state": state,
			"city": city,
			"area": area,
		},
	)
	obm.insert(ignore_permissions=True)
	# Ensure the customer link is persisted — read_only fields can be skipped by some
	# Frappe internals during insert, so we force an explicit db_set after insert.
	if obm.customer:
		frappe.db.set_value("Offline Buyer Master", obm.name, "customer", obm.customer, update_modified=False)
	frappe.db.commit()
	return obm.name
