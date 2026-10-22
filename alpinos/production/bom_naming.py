"""BOM named BOM-0001, per the FRD naming table.

ERPNext names a BOM in code, not by a naming rule: BOM.autoname() builds
"BOM-<fg item>-<nnn>" and frappe's set_new_name() calls that controller method in
preference to anything on the doctype. So a Property Setter or a naming series on BOM
would be ignored, and the only way to change it is to override the class.

The subclass changes naming and the default-BOM bookkeeping (manage_default_bom); every other
BOM behaviour is inherited, including validate_main_item.

Existing BOMs keep the names they were created with; Frappe never renames on its own.
"""

from frappe.model.naming import make_autoname

from erpnext.manufacturing.doctype.bom.bom import BOM

#: The FRD's series. ".####" is a four-digit counter, so the first BOM is BOM-0001.
BOM_NAMING_SERIES = "BOM-.####"


class AlpinosBOM(BOM):
	def manage_default_bom(self):
		"""Keep Item.default_bom in step with Is Default, and nothing more.

		ERPNext's version, which runs on submit, cancel and every update after submit, does two
		things this module does not want: it untick the other defaults itself (so a default
		moved without a word), and it ticks a BOM as the default whenever the item has none
		(so an item could never be left without one). Here an item may have no default BOM,
		and only one BOM may be ticked at a time: ticking a second is refused by
		bom_rules._validate_single_default, and the planner unticks the old one first.
		"""
		import frappe

		item_default = frappe.db.get_value("Item", self.item, "default_bom")
		if self.is_default and self.is_active:
			if item_default != self.name:
				frappe.db.set_value("Item", self.item, "default_bom", self.name)
			return
		# An inactive BOM cannot be the default; an unticked one is not.
		if self.is_default:
			self.db_set("is_default", 0)
		if item_default == self.name:
			frappe.db.set_value("Item", self.item, "default_bom", None)

	def autoname(self):
		# An amended document keeps frappe's own "-1" suffix convention, which it applies
		# after naming; nothing extra is needed here for it.
		self.name = make_autoname(BOM_NAMING_SERIES, doc=self)
