"""Process Master — the production steps, their order, and the machines each may use.

The business rules that are not expressible as field properties live here:

    rule 2  a process must allow at least one Machine Type
    rule 5  one process may allow several, and duplicates are meaningless
    rule 3  only an Active process may be put on a Production Order

Rules 4 and 6 need no code at all: a process stores machine TYPES, never machines, so a
machine added later under an allowed type is usable immediately (see
`Machine.assignable_machines`). That indirection is the whole reason the mapping is by
type rather than by machine.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from alpinos.production import constants as C


class ProcessMaster(Document):
	def before_naming(self):
		# Normalised HERE, not in validate: the code becomes the record ID, and naming
		# runs before validate -- so normalising later left the ID holding the raw text
		# ("prc-mix") while the field itself read "PRC-MIX".
		self._normalise_code()

	def validate(self):
		# Again on every save, because a rename or an edit does not go through naming.
		self._normalise_code()
		self._validate_unique_name()
		self._validate_machine_types()
		self._validate_sequence()

	def _normalise_code(self):
		# A stray space or a difference in case would otherwise make two processes that
		# read identically on screen.
		self.process_code = (self.process_code or "").strip().upper()
		self.process_name = (self.process_name or "").strip()

	def _validate_unique_name(self):
		"""Rule 1, with a message that names the clash.

		The field is `unique`, so the database would refuse this anyway -- but as a raw
		"Duplicate entry ... for key 'process_name'", which tells the user nothing about
		which process already holds it.
		"""
		if not self.process_name:
			return
		clash = frappe.db.get_value(
			"Process Master",
			{"process_name": self.process_name, "name": ("!=", self.name)},
			["name", "process_code"],
			as_dict=True,
		)
		if clash:
			frappe.throw(
				_("Process {0} is already called {1}.").format(
					clash.process_code or clash.name, self.process_name
				),
				title=_("Duplicate Process Name"),
			)

	def _validate_machine_types(self):
		"""Rule 2, and de-duplication for rule 5."""
		seen = []
		for row in self.get("machine_types") or []:
			if not row.machine_type:
				continue
			if row.machine_type in seen:
				frappe.throw(
					_("Machine Type {0} is listed more than once.").format(row.machine_type),
					title=_("Duplicate Machine Type"),
				)
			seen.append(row.machine_type)

		if not seen:
			frappe.throw(
				_("Please link at least one Machine Type to this process."),
				title=_("Machine Type Required"),
			)

	def _validate_sequence(self):
		if cint(self.process_sequence) <= 0:
			frappe.throw(
				_("Process Sequence must be 1 or more."), title=_("Invalid Sequence")
			)

		# The sequence IS the running order, and "what runs after Baking?" has to have one
		# answer. Two processes sharing a number make the next step a coin toss and the
		# entry screen's next-free-number suggestion a lie, so the clash is refused here
		# rather than resolved arbitrarily later.
		clash = frappe.db.get_value(
			"Process Master",
			{"process_sequence": cint(self.process_sequence), "name": ("!=", self.name)},
			["name", "process_name"],
			as_dict=True,
		)
		if clash:
			frappe.throw(
				_("Sequence {0} is already used by process {1} ({2}).").format(
					cint(self.process_sequence), clash.process_name, clash.name
				),
				title=_("Duplicate Sequence"),
			)


@frappe.whitelist()
def active_processes():
	"""The processes a Production Order may use, in the order they run (rule 3)."""
	return frappe.get_all(
		"Process Master",
		filters={"is_active": 1},
		fields=[
			"name",
			"process_code",
			"process_name",
			"process_sequence",
			"qc_required",
			"allow_inward_entry",
			"allow_machine_assignment",
		],
		order_by="process_sequence asc, process_name asc",
	)


@frappe.whitelist()
def machines_for_process(process_master):
	"""Every Active machine whose type this process allows (rules 4, 5 and 6).

	Resolved at call time rather than stored, so a machine added under an allowed type
	after the process was written still turns up here.
	"""
	frappe.has_permission("Process Master", "read", throw=True)
	types = frappe.get_all(
		"Process Machine Type",
		filters={"parent": process_master, "parenttype": "Process Master"},
		pluck="machine_type",
	)
	if not types:
		return []
	return frappe.get_all(
		"Machine",
		filters={
			"machine_type": ("in", types),
			"status": ("in", list(C.MACHINE_ASSIGNABLE_STATUSES)),
		},
		fields=["name", "machine_name", "machine_type", "max_capacity", "capacity_uom"],
		order_by="machine_type asc, machine_name asc",
	)
