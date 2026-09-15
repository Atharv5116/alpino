# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""One rule for how Item/SKU rows look on chosen reports and pages (Changes(HP) #39).

Colour from the Item's Color field, order from its Sequence. Applied in the browser by
public/js/item_display.js, and only on the reports and pages a configuration names.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ItemDisplayConfiguration(Document):
	def validate(self):
		self.sku_field = (self.sku_field or "").strip()
		if not (self.reports or self.pages):
			frappe.throw(_("Choose at least one report or page."), title=_("Nothing To Apply To"))
		if not (self.apply_item_color or self.apply_item_sequence):
			frappe.throw(
				_("Tick Apply Item Master Color, Apply Item Master Sequence, or both."),
				title=_("Nothing To Apply"),
			)
		if self.apply_item_color and not self.color_display:
			self.color_display = "Entire row"
		if self.apply_item_sequence and not self.sort_direction:
			self.sort_direction = "Ascending"
		self._no_overlap()

	def _no_overlap(self):
		"""A report or page follows ONE configuration, or two rules would fight over it."""
		if not self.enabled:
			return
		mine = {("Report", r.report) for r in self.reports} | {("Page", p.page) for p in self.pages}
		for other in frappe.get_all(
			"Item Display Configuration",
			filters={"enabled": 1, "name": ("!=", self.name or "")},
			pluck="name",
		):
			doc = frappe.get_doc("Item Display Configuration", other)
			theirs = {("Report", r.report) for r in doc.reports} | {("Page", p.page) for p in doc.pages}
			clash = sorted(mine & theirs)
			if clash:
				frappe.throw(
					_("{0} already follow the configuration {1}. Remove them there first.").format(
						", ".join(f"{kind} {name}" for kind, name in clash), frappe.bold(other)
					),
					title=_("Already Configured"),
				)

	def on_update(self):
		from alpinos.item_display_config import clear_cache

		clear_cache()

	def on_trash(self):
		from alpinos.item_display_config import clear_cache

		clear_cache()
