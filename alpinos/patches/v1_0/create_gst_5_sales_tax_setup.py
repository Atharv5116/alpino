"""Create 5% GST templates and tax rules for Sales Order auto-taxing."""

import frappe


def _company_abbr(company):
	return frappe.db.get_value("Company", company, "abbr")


def _ensure_tax_account(company, account_label):
	"""Ensure tax account exists for company, e.g. CGST - A."""
	abbr = _company_abbr(company)
	if not abbr:
		return None

	account_name = f"{account_label} - {abbr}"
	if frappe.db.exists("Account", account_name):
		return account_name

	parent = f"Duties and Taxes - {abbr}"
	if not frappe.db.exists("Account", parent):
		return None

	doc = frappe.new_doc("Account")
	doc.account_name = account_label
	doc.company = company
	doc.parent_account = parent
	doc.account_type = "Tax"
	doc.root_type = "Liability"
	doc.is_group = 0
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_tax_category(name):
	if frappe.db.exists("Tax Category", name):
		return name
	doc = frappe.new_doc("Tax Category")
	doc.title = name
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_sales_tax_template(company, title, tax_category, rows):
	existing = frappe.db.get_value(
		"Sales Taxes and Charges Template",
		{"title": title, "company": company},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Sales Taxes and Charges Template", existing)
		doc.tax_category = tax_category
		doc.disabled = 0
		doc.set("taxes", [])
	else:
		doc = frappe.new_doc("Sales Taxes and Charges Template")
		doc.title = title
		doc.company = company
		doc.tax_category = tax_category
		doc.disabled = 0

	for row in rows:
		doc.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": row["account_head"],
				"description": row["description"],
				"rate": row["rate"],
			},
		)

	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_tax_rule(company, tax_category, template_name):
	existing = frappe.db.get_value(
		"Tax Rule",
		{"tax_type": "Sales", "company": company, "tax_category": tax_category},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Tax Rule", existing)
		doc.sales_tax_template = template_name
		doc.disabled = 0
		doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.new_doc("Tax Rule")
	doc.tax_type = "Sales"
	doc.company = company
	doc.tax_category = tax_category
	doc.sales_tax_template = template_name
	doc.priority = 10
	doc.disabled = 0
	doc.insert(ignore_permissions=True)
	return doc.name


def _setup_for_company(company):
	cgst = _ensure_tax_account(company, "CGST")
	sgst = _ensure_tax_account(company, "SGST")
	igst = _ensure_tax_account(company, "IGST")
	if not (cgst and sgst and igst):
		return

	in_state = _ensure_tax_category("In-State GST")
	out_state = _ensure_tax_category("Out-State GST")

	in_tmpl = _ensure_sales_tax_template(
		company=company,
		title="GST 5% In-State (CGST+SGST)",
		tax_category=in_state,
		rows=[
			{"account_head": cgst, "rate": 2.5, "description": "CGST 2.5%"},
			{"account_head": sgst, "rate": 2.5, "description": "SGST 2.5%"},
		],
	)
	out_tmpl = _ensure_sales_tax_template(
		company=company,
		title="GST 5% Out-State (IGST)",
		tax_category=out_state,
		rows=[
			{"account_head": igst, "rate": 5.0, "description": "IGST 5%"},
		],
	)

	_ensure_tax_rule(company, in_state, in_tmpl)
	_ensure_tax_rule(company, out_state, out_tmpl)


def execute():
	companies = frappe.get_all("Company", pluck="name") or []
	for company in companies:
		_setup_for_company(company)
	frappe.db.commit()
