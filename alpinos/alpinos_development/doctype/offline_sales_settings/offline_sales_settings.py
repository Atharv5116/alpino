# Copyright (c) 2026, Alpinos and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class OfflineSalesSettings(Document):
	def validate(self):
		from alpinos.offline_sales.settings import validate_settings

		validate_settings(self)
