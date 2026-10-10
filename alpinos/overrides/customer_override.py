"""Customer: ERPNext v16's primary-contact/address "ensure" without the permission check.

On every Customer update, v16 marks the primary Contact and Address as primary through
frappe.set_value, which is a full save of that Contact or Address checked against the
current user. v15 had no such step. A user who may save the Customer but not edit
Contacts or Addresses -- every Buyer Master editor, since saving a Buyer Master saves its
Customer -- was refused with a PermissionError. This makes the same change as a system
step: the same document save, minus the permission check. v15 keeps ERPNext's own code.
"""

import frappe
from erpnext.selling.doctype.customer.customer import Customer

from alpinos.query_compat import IS_V16


def _ensure_flag(doctype, name, fieldname):
	doc = frappe.get_doc(doctype, name)
	if not doc.get(fieldname):
		doc.set(fieldname, 1)
		doc.flags.ignore_permissions = True
		doc.save()


class CustomCustomer(Customer):
	def create_primary_contact(self):
		if IS_V16 and self.customer_primary_contact:
			_ensure_flag("Contact", self.customer_primary_contact, "is_primary_contact")
			return
		super().create_primary_contact()

	def create_primary_address(self):
		if IS_V16 and self.customer_primary_address and not (self.flags.is_new_doc and self.get("address_line1")):
			_ensure_flag("Address", self.customer_primary_address, "is_primary_address")
			return
		super().create_primary_address()
