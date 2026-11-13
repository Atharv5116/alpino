"""The Offline Sales access matrix (document Section 1, 3 and 6-7), as DocPerm rows.

    Sales Officer   Buyer Master    read, create, write    which fields and when: buyer_rules
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
				_grant(doctype, role, level)
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)
