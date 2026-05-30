"""Batch master hooks for Alpinos."""

import frappe
from frappe.utils import add_days


def compute_expiry_from_shelf_life(doc, method=None):
	"""Auto-fill `expiry_date` from `manufacturing_date + Item.shelf_life_in_days`.

	Runs only when expiry is blank, so manually entered values stick.
	"""
	if not doc.get("manufacturing_date") or doc.get("expiry_date"):
		return
	if not doc.get("item"):
		return
	shelf_life = frappe.db.get_value("Item", doc.item, "shelf_life_in_days")
	if not shelf_life or int(shelf_life) <= 0:
		return
	doc.expiry_date = add_days(doc.manufacturing_date, int(shelf_life))
