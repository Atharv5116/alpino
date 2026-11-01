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

#: What a company's prints and emails say about it (Sales Order, Purchase Order, GRN, Purchase
#: Invoice, HR emails). Filled once for the default company with what the prints used to have
#: written into them; another company's prints show its own values, blank until set.
PRINT_FIELDS = [
	{"fieldname": "custom_print_section", "fieldtype": "Section Break", "label": "Print Details",
	 "insert_after": "default_letter_head", "collapsible": 1, "module": MODULE},
	{"fieldname": "custom_print_gstin", "fieldtype": "Data", "label": "GSTIN on Prints",
	 "insert_after": "custom_print_section", "module": MODULE},
	{"fieldname": "custom_print_address", "fieldtype": "Small Text", "label": "Address on Prints",
	 "insert_after": "custom_print_gstin", "module": MODULE},
	{"fieldname": "custom_print_tax_block", "fieldtype": "Small Text", "label": "Registration Lines (Purchase Order)",
	 "insert_after": "custom_print_address", "description": "GSTIN, CIN, State / Code, PAN, one per line.", "module": MODULE},
	{"fieldname": "custom_print_bill_to", "fieldtype": "Small Text", "label": "Invoice To Block (Purchase Order)",
	 "insert_after": "custom_print_tax_block", "module": MODULE},
	{"fieldname": "custom_print_delivery", "fieldtype": "Small Text", "label": "Default Delivery Block (Purchase Order)",
	 "insert_after": "custom_print_bill_to", "description": "Printed when an order has no delivery address.", "module": MODULE},
	{"fieldname": "custom_print_col", "fieldtype": "Column Break", "insert_after": "custom_print_delivery", "module": MODULE},
	{"fieldname": "custom_bank_name", "fieldtype": "Data", "label": "Bank Name", "insert_after": "custom_print_col", "module": MODULE},
	{"fieldname": "custom_bank_branch", "fieldtype": "Data", "label": "Bank Branch", "insert_after": "custom_bank_name", "module": MODULE},
	{"fieldname": "custom_bank_account_name", "fieldtype": "Data", "label": "Bank Account Name", "insert_after": "custom_bank_branch", "module": MODULE},
	{"fieldname": "custom_bank_account_no", "fieldtype": "Data", "label": "Bank Account Number", "insert_after": "custom_bank_account_name", "module": MODULE},
	{"fieldname": "custom_bank_ifsc", "fieldtype": "Data", "label": "IFSC Code", "insert_after": "custom_bank_account_no", "module": MODULE},
	{"fieldname": "custom_jurisdiction", "fieldtype": "Data", "label": "Jurisdiction (City)", "insert_after": "custom_bank_ifsc", "module": MODULE},
	{"fieldname": "custom_hr_email", "fieldtype": "Data", "options": "Email", "label": "HR Email",
	 "insert_after": "custom_jurisdiction", "description": "Onboarding reminders and job application copies go here.", "module": MODULE},
]

#: The default company's values, exactly as the prints and emails had them written in.
DEFAULT_COMPANY_PRINT = {
	"custom_print_gstin": "24AASCA1881A1ZV",
	"custom_print_address": "Plot No. 123-125, GIDC\nIndustrial Estate, Sachana\nSurat, Gujarat - 395023, India",
	"custom_print_tax_block": "GSTIN: 24AAACA1234A1Z1\nCIN: U15400GJ2020PTC112233\nState / Code: Gujarat / 24\nPAN: AAACA1234A",
	"custom_print_bill_to": "ALPINO HEALTH FOODS PVT. LTD.\nFinance &amp; Procurement Central Desk\nPlot No. 123-125, GIDC Industrial Estate\nSurat, Gujarat - 395023\nGSTIN: 24AAACA1234A1Z1\nEmail: ap.invoices@alpino.store",
	"custom_print_delivery": "Plant 1001 (Surat Central Plant)\nWarehouse Receipt Dock #02\nPlot No. 123-125, GIDC Industrial Area\nSurat, Gujarat - 395023",
	"custom_bank_name": "Axis Bank Ltd.",
	"custom_bank_branch": "Surat",
	"custom_bank_account_name": "Alpino Health Foods Pvt. Ltd.",
	"custom_bank_account_no": "919020040914629",
	"custom_bank_ifsc": "UTIB0000047",
	"custom_jurisdiction": "Surat",
	"custom_hr_email": "hr@alpinohealthfoods.com",
}

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
			},
			*PRINT_FIELDS,
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
	print_details_once()
	show_sales_order_company()
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


def print_details_once():
	"""The default company's print details, filled once from what the prints had built in."""
	key = "alpinos_cs_print_details"
	if frappe.db.get_default(key):
		return
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	if default and frappe.db.has_column("Company", "custom_print_gstin"):
		current = frappe.db.get_value("Company", default, list(DEFAULT_COMPANY_PRINT), as_dict=True) or {}
		missing = {k: v for k, v in DEFAULT_COMPANY_PRINT.items() if not current.get(k)}
		if missing:
			frappe.db.set_value("Company", default, missing, update_modified=False)
	frappe.db.set_default(key, "1")


def show_sales_order_company():
	"""Sales Order's Company is hidden by an old desk-layout property setter and mandatory;
	with the company default gone that combination makes Customize Form unsavable, and with
	several companies the order should say whose it is. Shown, read-only once submitted as
	ERPNext has it."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if frappe.db.get_value(
		"Property Setter", {"doc_type": "Sales Order", "field_name": "company", "property": "hidden"}, "value"
	) not in (None, "0"):
		make_property_setter("Sales Order", "company", "hidden", "0", "Check", validate_fields_for_doctype=False)
		frappe.clear_cache(doctype="Sales Order")


def remove_company_from_session_defaults():
	settings = frappe.get_single("Session Default Settings")
	keep = [r for r in settings.session_defaults if r.ref_doctype != "Company"]
	if len(keep) != len(settings.session_defaults):
		settings.set("session_defaults", keep)
		settings.save(ignore_permissions=True)
