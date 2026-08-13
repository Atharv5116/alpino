# Copyright (c) 2026, Alpinos and contributors
"""Freeze the pre-per-user invoice downloads.

Invoice downloads used to be tracked with a single flag on the Sales Order, so
there is no record of WHO downloaded what. Now that Pending Invoice Downloads is
per user, those orders would reappear on everybody's list — including invoices
pulled months ago.

Stamp them once as legacy so they stay off everyone's list. Anything downloaded
from here on is recorded per user in Alpino Invoice Download.
"""

import frappe


def execute():
	if not frappe.db.has_column("Sales Order", "custom_invoice_downloaded_legacy"):
		# The custom field is created on migrate before patches run; if it isn't
		# there yet, the next migrate will pick this up.
		return

	frappe.db.sql(
		"""
		UPDATE `tabSales Order`
		SET custom_invoice_downloaded_legacy = 1
		WHERE IFNULL(custom_invoice_downloaded, 0) = 1
			AND IFNULL(custom_invoice_downloaded_legacy, 0) = 0
		"""
	)
	frappe.db.commit()
