"""Machine Type — the vocabulary of machine categories the factory runs.

Admin-owned on purpose (Machine Master 2.1): every other screen picks from this list,
so letting anyone add to it would let anyone invent a category that no process maps to.
The DocPerm rows carry that rule; nothing extra is enforced here.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class MachineType(Document):
	def before_naming(self):
		self._normalise_code()

	def autoname(self):
		"""TYP- plus the short code the user types, per the FRD naming table.

		Falls back to the old TYP-.#### counter only when no code is given, so the eight
		Machine Types created before this field existed can still be edited and saved
		rather than being refused for something they never had a chance to fill in.
		"""
		from frappe.model.naming import make_autoname

		self._normalise_code()
		if self.type_code:
			self.name = f"TYP-{self.type_code}"
		else:
			self.name = make_autoname("TYP-.####", doc=self)

	def validate(self):
		self._normalise_code()
		self.machine_type_name = (self.machine_type_name or "").strip()
		self._validate_unique_name()
		self._validate_deactivation()

	def _validate_deactivation(self):
		"""MT-05 -- a type cannot be retired while Active machines still carry it.

		Deactivating hides the type from every picker, so the machines under it would stay
		Active and assignable while the category they belong to had quietly vanished from
		the vocabulary. Retiring the machines first is the honest order.
		"""
		# cint(), not raw truthiness. frappe.client.set_value passes the value straight
		# through from the HTTP form, so deactivating from the API arrives as the STRING
		# "0" -- which is truthy, so `if self.is_active` read it as "still active" and
		# returned before checking anything. The form and a full save send a real 0 and
		# were blocked correctly, which is why this only ever showed up through the API.
		if self.is_new() or cint(self.is_active):
			return
		before = self.get_doc_before_save()
		if not before or not cint(before.is_active):
			return  # already inactive; nothing is changing

		from alpinos.production import constants as C

		machines = frappe.get_all(
			"Machine",
			filters={"machine_type": self.name, "status": C.MACHINE_ACTIVE},
			pluck="machine_name",
			limit=5,
		)
		if machines:
			frappe.throw(
				_("Deactivate or move its machines first: {0}.").format(", ".join(machines)),
				title=_("Machine Type Still In Use"),
			)

	def _normalise_code(self):
		# Left completely alone when empty. type_code is set_only_once, and turning a
		# stored NULL into "" counts as a change -- which made every one of the Machine
		# Types created before this field existed unsaveable with
		# "Value cannot be changed for Type Code".
		if not self.type_code:
			return
		# Upper case and no spaces: the code becomes part of the ID, so "mix" and "MIX"
		# must not make two types that read the same on screen.
		self.type_code = self.type_code.strip().upper().replace(" ", "")

	def _validate_unique_name(self):
		"""The field is `unique`, so the database refuses a repeat anyway -- but as a raw
		"Duplicate entry ... for key 'machine_type_name'", which names no record."""
		if not self.machine_type_name:
			return
		clash = frappe.db.exists(
			"Machine Type",
			{"machine_type_name": self.machine_type_name, "name": ("!=", self.name)},
		)
		if clash:
			frappe.throw(
				_("Machine Type {0} is already called {1}.").format(
					clash, self.machine_type_name
				),
				title=_("Duplicate Machine Type"),
			)

	def on_trash(self):
		"""A type still in use cannot be removed, or its machines and processes would
		point at nothing. Frappe's own link check covers Machine (a Link field), but the
		Process Master holds its types in a child table, which that check does not reach."""
		linked = frappe.get_all(
			"Process Machine Type",
			filters={"machine_type": self.name},
			fields=["parent"],
			limit=5,
		)
		if not linked:
			return
		names = ", ".join(sorted({row.parent for row in linked}))
		frappe.throw(
			_("This Machine Type is used by the Process Master: {0}").format(names),
			title=_("Machine Type In Use"),
		)
