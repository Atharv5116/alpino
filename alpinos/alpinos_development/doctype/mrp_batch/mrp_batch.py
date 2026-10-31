# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""MRP Batch -- one batch and printed MRP of an item, held as a stock balance of its own.

Purchase Inward draft "MRP-Wise and Batch-Wise Inventory", section 8: stock is kept by Item,
Batch, MRP and Location. ERPNext keeps it by Item and Warehouse; this record is the third
key, carried on every stock transaction through the "MRP Batch" Inventory Dimension
(alpinos.mrp_batch). The item's own batch tracking is not used: ERPNext refuses to switch it
on for an item with past transactions, and batch codes stay free text on the Pick List and
Delivery Note (project memory: batch free text).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class MRPBatch(Document):
	def autoname(self):
		from alpinos.mrp_batch import lot_name

		self.name = lot_name(self.item_code, self.batch_no, self.mrp)

	def validate(self):
		from alpinos.mrp_batch import clean_batch, lot_title

		self.batch_no = clean_batch(self.batch_no)
		self.mrp = flt(self.mrp, 2)
		if not self.batch_no and not self.mrp:
			frappe.throw(_("An MRP Batch needs a Batch No., an MRP, or both."))
		if self.mrp < 0:
			frappe.throw(_("MRP cannot be negative."))
		if (
			self.manufacturing_date
			and self.expiry_date
			and getdate(self.expiry_date) < getdate(self.manufacturing_date)
		):
			frappe.throw(_("Expiry Date cannot be before the Manufacturing Date."))
		clash = frappe.db.get_value(
			"MRP Batch",
			{
				"item_code": self.item_code,
				"batch_no": self.batch_no or "",
				"mrp": self.mrp,
				"name": ("!=", self.name or ""),
			},
			"name",
		)
		if clash:
			frappe.throw(
				_("{0} already has batch {1} at MRP {2}: {3}.").format(
					self.item_code, self.batch_no or "-", self.mrp, clash
				),
				frappe.DuplicateEntryError,
			)
		self.title = lot_title(self.batch_no, self.mrp)
