"""Pick List Item: MFG / Expiry must not be mandatory on client (filled from Batch)."""

import frappe


def execute():
	from alpinos.pick_list_custom_fields import setup_pick_list_custom_fields

	setup_pick_list_custom_fields()
