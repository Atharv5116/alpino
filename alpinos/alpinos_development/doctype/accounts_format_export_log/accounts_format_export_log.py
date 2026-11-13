# Copyright (c) 2026, Alpinos and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AccountsFormatExportLog(Document):
	"""One Accounts Format Report row (a Sales Order part) included in one successful Excel
	export (Changes(HP) #110). Written by alpinos.afr_export, never by hand."""
