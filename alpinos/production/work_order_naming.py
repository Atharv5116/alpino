"""A Sub PO named after its Parent: PO-001-A, PO-001-B, ...

ERPNext names a Work Order in code -- `WorkOrder.autoname()` is not defined, so frappe falls
back to `naming_series`, and the doctype ships "MFG-WO-.YYYY.-". A naming series on the
doctype therefore cannot produce a name that depends on the parent document. Overriding the
class is the same route `bom_naming.AlpinosBOM` already takes and for the same reason.

The suffix is a letter, not a number, because that is how the FRD writes it throughout
(PO-001-A / -B / -C) and how the Parent PO list is asked to display it.

A Work Order with no Parent keeps ERPNext's own name. Nothing else about Work Order is
touched: the Sub PO is where stock really moves, and its native behaviour is wanted.
"""

import string

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder

from alpinos.production.work_order_fields import PARENT_FIELD

#: A, B, C ... Z. A Parent needing a 27th split is a planning problem, not a naming one, so
#: it is refused with a message rather than silently rolling over to AA.
SUFFIXES = tuple(string.ascii_uppercase)


def next_suffix(parent_po):
	"""The first unused letter for this Parent.

	Read off the names that exist rather than counting the Sub POs: a deleted or cancelled
	B must not hand its letter to the next split, or two documents would have shared a name
	that the batch number and the Job Card were printed with.
	"""
	taken = set()
	for name in frappe.get_all(
		"Work Order", filters={PARENT_FIELD: parent_po}, pluck="name"
	):
		suffix = name.rsplit("-", 1)[-1]
		if suffix in SUFFIXES:
			taken.add(suffix)

	for letter in SUFFIXES:
		if letter not in taken:
			return letter
	return None


class AlpinosWorkOrder(WorkOrder):
	def before_validate(self):
		"""Make the numeric fields numeric before anything compares them.

		`frappe.client.set_value` hands every value through as a STRING -- it comes off an
		HTTP form -- and ERPNext's `validate_qty` then does `self.qty > 0`, which on this
		Python raises

		    TypeError: '>' not supported between instances of 'str' and 'int'

		and the caller gets a 500 with a traceback instead of a message. ERPNext casts this
		field in some paths and not in this one; casting here fixes every Work Order rather
		than only the sub orders, and a value that is not a number at all still ends up at 0
		and is refused by ERPNext's own check with its own wording.
		"""
		for df in self.meta.get("fields", {"fieldtype": ("in", ("Float", "Currency", "Percent"))}):
			value = self.get(df.fieldname)
			if isinstance(value, str):
				self.set(df.fieldname, flt(value))
		for df in self.meta.get("fields", {"fieldtype": "Int"}):
			value = self.get(df.fieldname)
			if isinstance(value, str):
				self.set(df.fieldname, cint(value))

	def set_required_items(self, reset_only_qty=False):
		"""A Sub PO takes its material quantities from its Parent, not from the BOM.

		ERPNext multiplies the BOM by `qty`, and this BOM is written for ONE BATCH -- so a
		3,000 KG order asked the floor for 12.5 x 3000 = 37,500 Kg of jaggery, a thousand
		times what the recipe means. The Parent already holds the real answer in its Total
		Required Qty column, so that is what the Sub PO inherits, scaled by its share of the
		Parent when a split has made it smaller.

		ERPNext still builds the rows -- it knows about warehouses, rates and UOMs -- and
		only the quantity is rewritten afterwards. Constructing the rows by hand would mean
		reimplementing all of that and getting one of them wrong.

		An ordinary Work Order with no Parent keeps ERPNext's behaviour untouched.
		"""
		super().set_required_items(reset_only_qty=reset_only_qty)

		parent_name = self.get(PARENT_FIELD)
		if not parent_name or not self.get("required_items"):
			return

		from frappe.utils import flt

		parent = frappe.get_cached_doc("Production Order", parent_name)
		parent_qty = flt(parent.production_qty_kg)
		if parent_qty <= 0:
			return
		# A split makes the Sub PO a fraction of the Parent; an unsplit one is the whole of it.
		share = flt(self.qty) / parent_qty

		required = {}
		for row in parent.get("items") or []:
			if row.item_code:
				required[row.item_code] = required.get(row.item_code, 0) + flt(row.total_required_qty)

		for row in self.get("required_items"):
			if row.item_code in required:
				row.required_qty = flt(required[row.item_code] * share, row.precision("required_qty"))
				row.amount = flt(row.rate) * flt(row.required_qty)

	def autoname(self):
		parent = self.get(PARENT_FIELD)
		if not parent:
			# Not a Sub PO, so leave the name unset and let frappe carry on. Neither
			# WorkOrder nor Document defines autoname, so there is no super() to call --
			# frappe's set_new_name (naming.py) runs autoname first and falls through to the
			# doctype naming_series when it comes back with no name, which is exactly the
			# MFG-WO- name a standalone Work Order should keep.
			return

		suffix = next_suffix(parent)
		if not suffix:
			frappe.throw(
				_("{0} already has {1} sub orders, which is as many as the naming allows.").format(
					parent, len(SUFFIXES)
				),
				title=_("Too Many Sub Orders"),
			)
		self.name = f"{parent}-{suffix}"
