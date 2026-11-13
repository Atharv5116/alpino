"""after_migrate step for the Offline Sales build: permissions and settings defaults."""

import frappe

from alpinos.offline_sales import SETTINGS


#: The document's "System Defaults: Parth Bharti, Dipraj Chaudhary" (Section 4, 3.3).
DEFAULT_PRIMARY_POC_NAMES = ("Parth Bharti", "Dipraj Chaudhary")


def execute():
	from alpinos.offline_sales import roles

	roles.setup_permissions()
	roles.setup_page_roles()
	seed_settings()
	backfill_quotation_buyers()
	frappe.db.commit()


def backfill_quotation_buyers():
	"""Quotations raised before custom_buyer_master existed get their Buyer (and its Secondary POC)."""
	if not frappe.db.has_column("Quotation", "custom_buyer_master"):
		return
	from alpinos.offline_sales.catalog_gate import quotation_buyer

	for q in frappe.get_all(
		"Quotation",
		filters={"custom_buyer_master": ("is", "not set")},
		fields=["name", "quotation_to", "party_name", "custom_resolved_customer"],
	):
		buyer = quotation_buyer(q)
		if buyer:
			frappe.db.set_value(
				"Quotation", q.name,
				{"custom_buyer_master": buyer, "custom_secondary_poc": frappe.db.get_value("Buyer Master", buyer, "secondary_poc")},
				update_modified=False,
			)


def seed_settings():
	"""Fill the defaults once; after that the settings are the business's to change."""
	if not frappe.db.exists("DocType", SETTINGS):
		return
	if frappe.db.get_single_value(SETTINGS, "escalation_hours"):
		return  # already set up (escalation_hours is never 0 once saved)
	settings = frappe.get_single(SETTINGS)
	settings.escalation_hours = 48
	from alpinos.buyer_assignment import PRIMARY_POC_ROLES

	for name in DEFAULT_PRIMARY_POC_NAMES:
		employee = frappe.db.get_value("Employee", {"employee_name": name, "status": "Active"}, "name")
		user = frappe.db.get_value("Employee", employee, "user_id") if employee else None
		if user and set(PRIMARY_POC_ROLES) & set(frappe.get_roles(user)):
			settings.append("default_primary_pocs", {"employee": employee})
	settings.flags.ignore_permissions = True
	settings.save()
