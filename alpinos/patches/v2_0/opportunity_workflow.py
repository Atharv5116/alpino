"""Offline Sales, Section 3: the Opportunities raised before the Opportunity workflow get its
Source (Direct Opportunity), Created By / On (their owner and creation) and an Opportunity
Status mapped from ERPNext's status (and their Buyer's Secondary POC, for the list default):

    Open, Replied          -> Pending (Draft)
    Quotation, Converted   -> Converted to Quotation, linked to their non-cancelled Quotation
                              (Pending (Submitted) when they have none, so Convert is offered)
    Lost                   -> Lost
    Closed                 -> Cancelled
"""

import frappe


def execute():
	if not frappe.db.has_column("Opportunity", "custom_opportunity_status"):
		from alpinos.opportunity_custom_fields import setup_opportunity_custom_fields

		setup_opportunity_custom_fields()
	if not frappe.db.has_column("Opportunity", "custom_opportunity_status"):
		return

	mapping = {
		"Open": "Pending (Draft)",
		"Replied": "Pending (Draft)",
		"Lost": "Lost",
		"Closed": "Cancelled",
	}
	for opp in frappe.get_all("Opportunity", fields=["name", "status", "owner", "creation"]):
		values = {
			"custom_opportunity_source": "Direct Opportunity",
			"custom_created_by": opp.owner if frappe.db.exists("User", opp.owner) else None,
			"custom_created_on": opp.creation,
		}
		if opp.status in ("Quotation", "Converted"):
			quotation = frappe.db.get_value(
				"Quotation", {"opportunity": opp.name, "docstatus": ("<", 2)}, "name", order_by="creation desc"
			)
			values["custom_opportunity_status"] = "Converted to Quotation" if quotation else "Pending (Submitted)"
			values["custom_linked_quotation"] = quotation
		else:
			values["custom_opportunity_status"] = mapping.get(opp.status, "Pending (Draft)")
		party = frappe.db.get_value("Opportunity", opp.name, ["opportunity_from", "party_name"], as_dict=True)
		if party.opportunity_from == "Buyer Master" and party.party_name:
			values["custom_secondary_poc"] = frappe.db.get_value("Buyer Master", party.party_name, "secondary_poc")
		frappe.db.set_value("Opportunity", opp.name, values, update_modified=False)
