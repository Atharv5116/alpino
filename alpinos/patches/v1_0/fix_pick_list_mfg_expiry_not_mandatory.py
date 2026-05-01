"""Clear stuck reqd=1 on Pick List Item MFG/Expiry custom fields (client blocked save before batch sync)."""

import frappe


def execute():
	from alpinos.pick_list_custom_fields import ensure_pick_list_item_date_fields_optional

	ensure_pick_list_item_date_fields_optional()
	frappe.db.commit()
