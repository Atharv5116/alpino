"""after_migrate: the fields Company-wise access needs, and its one-time defaults.

- Role.custom_company_scoped ("Company-wise role"), with the starting classification below
  applied once; after that only Role Permissions Manager / the Company Access Manager change it.
- Company tags (Companies + its hidden mirror) on the tagged masters.
- Company.custom_series_code: blank keeps a company's document numbers as they are; a code
  (APC, EO, HH) goes into its numbers: SOR-APC-2627-00001.
- Employee Checkin.company, fetched from the Employee, so punches are company-wise too.
- Company out of Session Default Settings: Frappe clears that default on logout, and the
  switcher replaces the dialog.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alpinos.company_scope import registry

MODULE = "Alpinos Development"
_CLASSIFIED_KEY = "alpinos_cs_roles_classified"

#: Roles that start as company-wise (agreed for sign-off on 1 Nov 2026). Everything else is
#: global: Employee, approvers, HOD, Reporting Manager, System Manager, Raven, report and
#: workspace managers, portal roles.
COMPANY_WISE_ROLES = (
	"Accounts Manager", "Accounts User", "Auditor", "Alpino Product Sale",
	"Sales Admin", "Sales Manager", "Sales Officer", "Sales User",
	"E-Commerce Admin", "E-Commerce Coordinator", "E-Commerce Manager",
	"Delivery Manager", "Delivery User", "DN Manager", "DN User", "PL Manager", "PL User",
	"Fulfillment User", "Fleet Manager",
	"Stock Manager", "Stock User", "Item Manager", "Quality Manager",
	"Warehouse Admin", "Warehouse Manager", "Warehouse User",
	"Purchase Manager", "Purchase User", "Purchase Master Manager", "Purchase Accounts User",
	"Purchase Inward Admin", "Purchase Inward Manager", "Purchase Inward User",
	"Purchase QC Manager", "Purchase QC User",
	"Store Manager", "Store Planner", "Store Receiving Manager", "Store Receiving User", "Store User",
	"Manufacturing Manager", "Manufacturing User", "Plant Head",
	"Production Admin", "Production Manager", "Production Operator", "Production User",
	"QC Inspector", "QC Manager", "Maintenance Manager", "Maintenance User",
	"Projects Manager", "Projects User", "Marketing Manager",
	"HR Manager", "HR User",
)

#: Where the Companies field goes on each tagged master.
_TAG_AFTER = {
	"Item": "item_group",
	"Customer": "customer_group",
	"Supplier": "supplier_group",
	"Buyer Master": "customer_type",
	"Price List": "price_list_name",
	"Machine": "machine_type",
	"Process Master": "process_name",
}


def custom_fields():
	fields = {
		"Role": [
			{
				"fieldname": "custom_company_scoped",
				"fieldtype": "Check",
				"label": "Company-wise role",
				"insert_after": "desk_access",
				"description": "Given per company in Company Access: a user holds it only in the companies it is given in. Unticked, a role given on the User applies in every company.",
				"module": MODULE,
			}
		],
		"Company": [
			{
				"fieldname": "custom_series_code",
				"fieldtype": "Data",
				"label": "Series Code",
				"insert_after": "abbr",
				"length": 10,
				"description": "Goes into this company's document numbers, e.g. APC gives SOR-APC-2627-00001. Blank keeps the numbers as they are.",
				"module": MODULE,
			}
		],
		"Employee Checkin": [
			{
				"fieldname": "company",
				"fieldtype": "Link",
				"options": "Company",
				"label": "Company",
				"insert_after": "employee_name",
				"fetch_from": "employee.company",
				"read_only": 1,
				"search_index": 1,
				"in_standard_filter": 1,
				"module": MODULE,
			}
		],
	}
	for doctype, after in _TAG_AFTER.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		fields.setdefault(doctype, []).extend(
			[
				{
					"fieldname": registry.TAG_FIELD,
					"fieldtype": "Table MultiSelect",
					"options": registry.TAG_DOCTYPE,
					"label": "Companies",
					"insert_after": after,
					"description": "Companies that use this. Blank = every company.",
					"module": MODULE,
				},
				{
					"fieldname": registry.SCOPE_FIELD,
					"fieldtype": "Small Text",
					"label": "Company Scope",
					"insert_after": registry.TAG_FIELD,
					"hidden": 1,
					"read_only": 1,
					"module": MODULE,
				},
			]
		)
	return fields


def setup():
	create_custom_fields(custom_fields(), ignore_validate=True)
	classify_roles_once()
	series_codes_once()
	remove_company_from_session_defaults()
	from alpinos.company_scope import access

	access.clear_cache()


def classify_roles_once():
	if frappe.db.get_default(_CLASSIFIED_KEY):
		return
	for role in COMPANY_WISE_ROLES:
		if frappe.db.exists("Role", role):
			frappe.db.set_value("Role", role, "custom_company_scoped", 1, update_modified=False)
	frappe.db.set_default(_CLASSIFIED_KEY, "1")


def series_codes_once():
	"""Decided 1 Nov 2026: the default company keeps its numbers; every other company gets
	its abbreviation as Series Code (SOR-APC-2627-00001). Set once; Company then owns it."""
	key = "alpinos_cs_series_codes"
	if frappe.db.get_default(key):
		return
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	for company in frappe.get_all("Company", fields=["name", "abbr", "custom_series_code"]):
		if company.name != default and not company.custom_series_code and company.abbr:
			frappe.db.set_value("Company", company.name, "custom_series_code", company.abbr, update_modified=False)
	frappe.db.set_default(key, "1")


def remove_company_from_session_defaults():
	settings = frappe.get_single("Session Default Settings")
	keep = [r for r in settings.session_defaults if r.ref_doctype != "Company"]
	if len(keep) != len(settings.session_defaults):
		settings.set("session_defaults", keep)
		settings.save(ignore_permissions=True)
