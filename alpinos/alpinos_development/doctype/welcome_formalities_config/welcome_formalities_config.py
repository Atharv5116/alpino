# Copyright (c) 2026, Essence ERP Development and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WelcomeFormalitiesConfig(Document):
	def validate(self):
		# Ensure TAT days is positive
		if self.tat_days < 0:
			frappe.throw("TAT Days must be a positive number")
