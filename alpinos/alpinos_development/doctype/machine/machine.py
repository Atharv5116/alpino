"""Machine — one physical machine on the factory floor.

The status is the whole point of the record: production planning asks this doctype
"may I use you?", and only an Active machine may answer yes (Machine Master rules 2/3).
`assignable_machines` is that question in code, so no caller has to re-derive it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from alpinos.production import constants as C


class Machine(Document):
	def validate(self):
		self.machine_name = (self.machine_name or "").strip()
		self._validate_unique_name()
		self._validate_machine_type()
		self._validate_capacity()

	def _validate_machine_type(self):
		"""MT-03 on the server, not only in the picker.

		Both screens filter their Machine Type picker to `is_active`, but a picker is not a
		rule: the REST API, a data import and a script all set the field directly, and an
		inactive type is a category the factory has retired. A machine filed under one is
		invisible to every screen that lists types and cannot be planned.

		Only checked when the type is new or being changed, so a machine already filed
		under a type that was retired afterwards stays editable -- otherwise retiring a
		type would silently lock every machine under it.
		"""
		if not self.machine_type:
			return
		if not self.is_new():
			before = self.get_doc_before_save()
			if before and before.machine_type == self.machine_type:
				return
		if not cint(frappe.db.get_value("Machine Type", self.machine_type, "is_active")):
			frappe.throw(
				_("Machine Type {0} is inactive, so a machine cannot be filed under it.").format(
					self.machine_type
				),
				title=_("Inactive Machine Type"),
			)

	def _validate_unique_name(self):
		"""Same reason as Machine Type: `unique` alone gives a raw database error that
		names no record, and two machines on a floor must be tellable apart by name."""
		if not self.machine_name:
			return
		clash = frappe.db.exists(
			"Machine", {"machine_name": self.machine_name, "name": ("!=", self.name)}
		)
		if clash:
			frappe.throw(
				_("Machine {0} is already called {1}.").format(clash, self.machine_name),
				title=_("Duplicate Machine"),
			)

	def _validate_capacity(self):
		# On a Float column a blank IS zero -- frappe stores None as 0.0 -- so a machine
		# saved with no capacity came back with max_capacity = 0 on the next load. Treating
		# 0 as "too small" therefore made that machine permanently unsaveable: the first
		# save accepted the blank, and every save afterwards refused the document's own
		# stored value. Three machines here are in that state.
		#
		# So 0 means "not recorded", which is the only reading a Float allows, and it is
		# normalised back to None so nothing downstream reads it as a real capacity of zero.
		if not flt(self.max_capacity):
			self.max_capacity = None
			return
		if flt(self.max_capacity) < 0:
			frappe.throw(
				_("Max Capacity cannot be negative. Leave it blank if it is not known."),
				title=_("Invalid Max Capacity"),
			)
		# A number with no unit cannot be compared against a batch size, so the pair is
		# demanded together or not at all -- rather than made mandatory, which the BRD
		# does not ask for.
		if not self.capacity_uom:
			frappe.throw(
				_("Please choose the Capacity UOM that Max Capacity is measured in."),
				title=_("Capacity UOM Missing"),
			)


@frappe.whitelist()
def assignable_machines(machine_type=None):
	"""The machines production may actually be given, newest rule first: Active only.

	Rule 4 of the Machine Master falls out of this for free -- a machine added under an
	existing type is returned here the moment it is saved Active, with nothing to
	re-map on the processes that use that type.
	"""
	filters = {"status": ("in", list(C.MACHINE_ASSIGNABLE_STATUSES))}
	if machine_type:
		filters["machine_type"] = machine_type
	return frappe.get_all(
		"Machine",
		filters=filters,
		fields=["name", "machine_name", "machine_type", "max_capacity", "capacity_uom"],
		order_by="machine_name asc",
	)
