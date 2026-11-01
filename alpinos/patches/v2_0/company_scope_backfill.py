"""Company-wise access, go-live data (1 Nov 2026):

1. every document that got a Company field fills it from where it belongs (its Production
   Order, Employee, Sales Order); the few with nowhere to read it from get the default
   company, which owns every such record today;
2. the tagged masters - Item, Customer, Supplier, Buyer Master, Price List, Machine, Process
   Master - are tagged to Alpino Health Foods (the default company), as decided.

Runs the field setup first, because after_migrate (which normally adds the fields) runs
after the patches.
"""

import frappe

#: doctype -> (link field, linked doctype) the company comes from; None = default company
SOURCES = {
	"Production QC": ("parent_production_order", "Production Order"),
	"Process Inward": ("parent_production_order", "Production Order"),
	"Filling Inward": ("parent_po", "Production Order"),
	"Final QC": ("parent_po", "Production Order"),
	"Filling Plan": ("parent_po", "Production Order"),
	"Production Run": ("parent_production_order", "Production Order"),
	"Production Yield Record": ("parent_po", "Production Order"),
	"Work From Home Request": ("employee", "Employee"),
	"Post Dispatch": ("sales_order", "Sales Order"),
	"Employee Checkin Log": ("employee", "Employee"),
	"Employee Checkin": ("employee", "Employee"),
	"Machine Run": None,
	"Alpino Product Sale": None,
	"Inward Planning": None,
}


def execute():
	from alpinos.company_scope import registry, setup, tags

	setup.setup()
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	for doctype, source in SOURCES.items():
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, "company"):
			continue
		if source:
			field, parent = source
			frappe.db.sql(
				f"""update `tab{doctype}` d join `tab{parent}` p on p.name = d.`{field}`
				set d.company = p.company where ifnull(d.company, '') = ''"""
			)
		if default:
			frappe.db.sql(
				f"update `tab{doctype}` set company = %s where ifnull(company, '') = ''", default
			)
	if default:
		for doctype in registry.TAGGED_DOCTYPES:
			if frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, registry.SCOPE_FIELD):
				count = tags.tag_all(doctype, default)
				print(f"Company-wise access: {count} {doctype} tagged to {default}")
