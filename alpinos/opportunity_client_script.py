"""The old "Opportunity - Alpinos Customization" Client Script, retired.

The Opportunity form's behaviour is now public/js/opportunity_offline.js (doctype_js), written
for Section 3 of "Opportunity to Sales Order v1.0.0": the Buyer Master party and its header,
read-only Buyer Catalog pricing from the server, Box without changing Quantity, the status
actions and the lock. The Client Script record is switched off rather than deleted, so a site
keeps its history; nothing re-enables it.
"""

import frappe

SCRIPT_NAME = "Opportunity - Alpinos Customization"


def create_opportunity_client_script():
	"""after_migrate: keep the retired Client Script switched off."""
	if frappe.db.exists("Client Script", SCRIPT_NAME) and frappe.db.get_value("Client Script", SCRIPT_NAME, "enabled"):
		frappe.db.set_value("Client Script", SCRIPT_NAME, "enabled", 0)
		frappe.clear_cache(doctype="Opportunity")
