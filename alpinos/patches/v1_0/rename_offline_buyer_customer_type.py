"""Rename the 'Offline Buyer Customer Type' DocType to 'Alpino Customer Type'.

Runs in pre_model_sync so the DB DocType + its table + all Link references are renamed
BEFORE the new 'Alpino Customer Type' JSON is synced. Record names (and therefore the
values stored in customer_type / custom_offline_buyer_customer_type link fields) are
unchanged, so existing links keep pointing to the same rows. The new `channel` field is
added by the normal doctype sync afterwards.
"""

import frappe


def execute():
	old, new = "Offline Buyer Customer Type", "Alpino Customer Type"
	if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
		frappe.rename_doc("DocType", old, new, force=True)
		frappe.clear_cache()
		print(f"✅ Renamed DocType '{old}' → '{new}'")
