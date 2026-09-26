"""BOM named BOM-0001, per the FRD naming table.

ERPNext names a BOM in code, not by a naming rule: BOM.autoname() builds
"BOM-<fg item>-<nnn>" and frappe's set_new_name() calls that controller method in
preference to anything on the doctype. So a Property Setter or a naming series on BOM
would be ignored, and the only way to change it is to override the class.

The subclass changes naming and nothing else -- every other BOM behaviour is inherited,
including manage_default_bom and validate_main_item.

Existing BOMs keep the names they were created with; Frappe never renames on its own.
"""

from frappe.model.naming import make_autoname

from erpnext.manufacturing.doctype.bom.bom import BOM

#: The FRD's series. ".####" is a four-digit counter, so the first BOM is BOM-0001.
BOM_NAMING_SERIES = "BOM-.####"


class AlpinosBOM(BOM):
	def autoname(self):
		# An amended document keeps frappe's own "-1" suffix convention, which it applies
		# after naming; nothing extra is needed here for it.
		self.name = make_autoname(BOM_NAMING_SERIES, doc=self)
