"""Production Settings: the store warehouses and the planning switches.

Read through alpinos.production.production_settings, never directly, so every screen agrees
on what "available stock" means.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class ProductionSettings(Document):
	def validate(self):
		if self.main_warehouse and self.wip_warehouse and self.main_warehouse == self.wip_warehouse:
			frappe.throw(_("The Main Warehouse and the WIP Warehouse must be different warehouses."),
			             title=_("Same Warehouse Twice"))
		for fieldname, label in (("main_warehouse", _("Main Warehouse")),
		                         ("wip_warehouse", _("WIP Warehouse"))):
			name = self.get(fieldname)
			if not name:
				continue
			row = frappe.db.get_value("Warehouse", name, ["is_group", "disabled"], as_dict=True)
			if not row:
				continue
			if cint(row.is_group):
				frappe.throw(_("{0} {1} is a group warehouse. Choose a warehouse that holds stock.").format(
					label, frappe.bold(name)), title=_("Group Warehouse"))
			if cint(row.disabled):
				frappe.throw(_("{0} {1} is disabled.").format(label, frappe.bold(name)),
				             title=_("Disabled Warehouse"))
