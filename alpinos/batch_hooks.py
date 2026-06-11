"""Batch master hooks for Alpinos."""

import frappe
from frappe.utils import add_days, getdate


def compute_expiry_from_shelf_life(doc, method=None):
	"""Auto-fill `expiry_date` from `manufacturing_date + Item.shelf_life_in_days`,
	then guard against any user-entered expiry being earlier than manufacturing.

	Runs only when expiry is blank for the auto-fill (manually-entered values stick),
	but the validation kicks in either way.
	"""
	if doc.get("manufacturing_date") and not doc.get("expiry_date") and doc.get("item"):
		shelf_life = frappe.db.get_value("Item", doc.item, "shelf_life_in_days")
		if shelf_life and int(shelf_life) > 0:
			doc.expiry_date = add_days(doc.manufacturing_date, int(shelf_life))

	if doc.get("manufacturing_date") and doc.get("expiry_date"):
		if getdate(doc.expiry_date) < getdate(doc.manufacturing_date):
			frappe.throw(
				f"Expiry Date ({doc.expiry_date}) cannot be earlier than Manufacturing Date ({doc.manufacturing_date})."
			)
