"""The Offline Sales access matrix (document Section 1, 3 and 6-7), as DocPerm rows.

    Sales Officer   Buyer Master    read, create, write    which fields and when: buyer_rules
                    Opportunity     read, create, write    status changes through its actions only
                    Quotation       read, create, write    never submit or cancel (finalize)
                    Pick List       read only              of their Buyers' orders
                    Delivery Note   read only              of their Buyers' orders
                    Buyer Items     read only              no catalogue pricing
    Sales Manager   Buyer Items     read, create, write    maintains the Buyer Catalog (3.2)

Sales Admin, Sales Manager and System Manager already hold the rest (Buyer Master, Quotation,
Sales Order); Sales Order rights of the Sales Officer are sales_order_authority's.

Rows are written with purchase.roles._grant inside the company_scope.perm_seed window: a row
seen for the first time is kept as written, after that Role Permissions Manager owns it. The
one row that existed before this build (Buyer Master / Sales Officer, read only) is moved by
the patch offline_sales_build1, which runs before the window opens.
"""

import frappe

from alpinos.offline_sales import SALES_MANAGER, SALES_OFFICER, SETTINGS

PERMISSION_MATRIX = {
	"Buyer Master": {SALES_OFFICER: "CREATE_EDIT"},
	# Section 3 (Opportunity): SO / SM / SA create, edit while Draft and act on it; Sales
	# Manager and Sales Admin already hold their rows
	"Opportunity": {SALES_OFFICER: "CREATE_EDIT"},
	# ERPNext's new Opportunity sets Opportunity Type "Sales" in the browser, whose link check
	# refused a Sales Officer ("Insufficient Permission for Opportunity Type")
	"Opportunity Type": {SALES_OFFICER: "VIEW"},
	"Quotation": {SALES_OFFICER: "CREATE_EDIT"},
	"Pick List": {SALES_OFFICER: "VIEW"},
	"Delivery Note": {SALES_OFFICER: "VIEW"},
	"Buyer Items": {SALES_OFFICER: "VIEW", SALES_MANAGER: "CREATE_EDIT"},
	# Changes(HP) #77: the addresses and the buyer form link to these ("No permission for State")
	"State": {SALES_OFFICER: "VIEW"},
	"City": {SALES_OFFICER: "VIEW"},
	"Country": {SALES_OFFICER: "VIEW"},
	"Alpino Customer Type": {SALES_OFFICER: "VIEW"},
	"Channel": {SALES_OFFICER: "VIEW"},
	SETTINGS: {"System Manager": "SETTINGS_MANAGE"},
}


def setup_permissions():
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	from alpinos.purchase.roles import _grant

	for doctype, role_levels in PERMISSION_MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for role, level in role_levels.items():
			if frappe.db.exists("Role", role):
				try:
					_grant(doctype, role, level)
				except frappe.ValidationError:
					# Frappe's add_permission validates the doctype's EXISTING rows too, and a row
					# someone else owns may not pass (State's System Manager row has Import on a
					# doctype that is not importable). Write ours directly instead.
					frappe.clear_messages()
					_grant_direct(doctype, role, level)
		try:
			validate_permissions_for_doctype(doctype)
		except frappe.ValidationError:
			# a row someone else owns may not pass Frappe's own check (State's System Manager
			# row carries Import on a doctype that is not importable); ours are written right
			frappe.clear_messages()
			frappe.log_error(title=f"Offline Sales: permissions of {doctype} not validated")
		frappe.clear_cache(doctype=doctype)


def _grant_direct(doctype, role, level):
	"""The same row _grant writes, without Frappe validating the doctype's other rows."""
	from frappe.permissions import setup_custom_perms

	from alpinos.purchase.roles import _MANAGED_PTYPES, _level_ptypes

	setup_custom_perms(doctype)
	granted = _level_ptypes(level)
	key = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
	name = frappe.db.get_value("Custom DocPerm", key, "name")
	values = {ptype: 1 if ptype in granted else 0 for ptype in _MANAGED_PTYPES}
	if name:
		frappe.db.set_value("Custom DocPerm", name, values, update_modified=False)
	else:
		frappe.get_doc(
			dict(doctype="Custom DocPerm", parenttype="DocType", parentfield="permissions", **key, **values)
		).db_insert()


#: Pages a Sales Officer works in. Changes(HP) #66 / #68 / #70: the Sales Order entry, list and
#: view pages (the 3 Oct amendment gave the role Sales Order rights, but the pages themselves
#: never listed it, so the screens refused it), and the Order Fulfilment Report. The Pick List
#: and Delivery Note pages list no roles at all, so they are open to every desk user already.
PAGE_ROLES = {
	"sales-order-entry": (SALES_OFFICER,),
	"sales-order-entry-list": (SALES_OFFICER,),
	"sales-order-entry-view": (SALES_OFFICER,),
	"invoice-download-queue": (SALES_OFFICER,),
}


def setup_page_roles():
	"""Add the role to the page once; seeded by company_scope.perm_seed like any new row."""
	for page, page_roles in PAGE_ROLES.items():
		if not frappe.db.exists("Page", page):
			continue
		have = set(frappe.get_all("Has Role", filters={"parent": page, "parenttype": "Page"}, pluck="role"))
		if not have:
			continue  # a page with no roles is open to everyone; adding one would close it
		for role in page_roles:
			if role not in have and frappe.db.exists("Role", role):
				frappe.get_doc(
					{"doctype": "Has Role", "parent": page, "parenttype": "Page", "parentfield": "roles", "role": role}
				).db_insert()
		frappe.clear_cache()
