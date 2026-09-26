"""Starter data for the Production masters (run on migrate).

The BRD hands us its worked example as the initial dataset: three processes in their
running order, and the machine categories they run on. Seeding it from code rather than
by hand means a fresh bench, staging and production all start from the same floor plan.

Nothing here ever overwrites a record that already exists. Once the factory has edited a
process -- renamed it, re-sequenced it, added a machine type -- that edit is the truth,
and a later migrate must not quietly undo it.

The machines are the exception in kind, not in that rule: the BRD names none, so they are
examples rather than master data, and they are written only to a Machine table that is
still empty. See `seed_machines` for why that guard has to be different.
"""

import frappe
from frappe.utils import cint

MACHINE_TYPE_DOCTYPE = "Machine Type"
MACHINE_DOCTYPE = "Machine"
PROCESS_DOCTYPE = "Process Master"

#: Set once the example machines have been offered, so the offer is never repeated. See
#: `seed_machines`.
MACHINES_SEEDED_FLAG = "alpinos_production_machines_seeded"

#: The three broad categories the client asked for by name (BRD 2.1, annotation "JYK":
#: "on machine type we need to add mixing machine, baking machine, and filling machine").
#: These are what the seeded processes map to -- a process is written against the KIND of
#: machine it needs, not against one model of it.
TYPE_MIXING = "Mixing Machine"
TYPE_BAKING = "Baking Machine"
TYPE_FILLING = "Filling Machine"

#: The specific machines the BRD names as examples (2.1). Seeded alongside the broad
#: categories so a machine can be filed under the model it actually is, and linked to the
#: same process as its category -- BRD 3.1 maps Mixing to Spiral Dough Mixer, Baking to
#: Rotary Rack Oven and Filling to VFFS, and rule 5 lets a process hold both.
MACHINE_TYPES = (
	# (machine_type_name, description)
	(TYPE_MIXING, "Machines that mix or knead the base dough."),
	(TYPE_BAKING, "Ovens and machines that bake the mixed dough."),
	(TYPE_FILLING, "Machines that fill and pack the finished product."),
	("Spiral Dough Mixer", "Spiral mixer for bulk dough batches."),
	("Rotary Rack Oven", "Rotary rack oven for baking."),
	("VFFS Packing Line", "Vertical form-fill-seal packing line."),
	("Semi-Automatic Filling Machine", "Semi-automatic filling machine."),
)

#: Starter machines, so the Machine screens have something to show on a fresh site and
#: the filters can be seen working. Between them they cover all three statuses and all
#: four capacity units.
#:
#: Every type gets an Active machine and a second one out of service, so the rule that
#: matters -- only an Active machine may be assigned -- can be SEEN working from any
#: process rather than merely asserted. Semi-Auto Filler 1 is the Inactive case, which is
#: a different exclusion from Under Maintenance and worth having one of.
#:
#: These are NOT from the BRD -- it names no machines, only the MAC-001 id format. They
#: are examples, and `seed_machines` only ever writes them to an empty Machine table for
#: exactly that reason: the moment the factory enters its real machines, this list stops
#: applying and must never come back.
MACHINES = (
	# (machine_name, machine_type_name, max_capacity, capacity_uom, status)
	("Spiral Mixer 1", "Spiral Dough Mixer", 200, "KG", "Active"),
	("Spiral Mixer 2", "Spiral Dough Mixer", 200, "KG", "Under Maintenance"),
	("Ribbon Blender 1", TYPE_MIXING, 500, "KG", "Active"),
	("Ribbon Blender 2", TYPE_MIXING, 500, "KG", "Under Maintenance"),
	("Rack Oven 1", "Rotary Rack Oven", 60, "Trays", "Active"),
	("Rack Oven 2", "Rotary Rack Oven", 60, "Trays", "Under Maintenance"),
	("Tunnel Oven 1", TYPE_BAKING, 120, "Trays", "Active"),
	("Tunnel Oven 2", TYPE_BAKING, 120, "Trays", "Under Maintenance"),
	("VFFS Line 1", "VFFS Packing Line", 2000, "Pieces", "Active"),
	("VFFS Line 2", "VFFS Packing Line", 2000, "Pieces", "Under Maintenance"),
	("Jar Filling Line 1", TYPE_FILLING, 1200, "Pieces", "Active"),
	("Jar Filling Line 2", TYPE_FILLING, 1200, "Pieces", "Under Maintenance"),
	("Semi-Auto Filler 1", "Semi-Automatic Filling Machine", 300, "Liters", "Inactive"),
)

#: BRD 3.1, exactly as the list screen shows it. Mixing needs no quality check; baking
#: and filling do, because both can spoil a batch in a way the next step cannot fix.
PROCESSES = (
	{
		"process_code": "PRC-MIX",
		"process_name": "Mixing",
		"process_sequence": 1,
		"qc_required": 0,
		"allow_inward_entry": 1,
		"machine_types": (TYPE_MIXING, "Spiral Dough Mixer"),
		"description": "Mix the base raw materials into dough.",
	},
	{
		"process_code": "PRC-BAK",
		"process_name": "Baking",
		"process_sequence": 2,
		"qc_required": 1,
		"allow_inward_entry": 1,
		"machine_types": (TYPE_BAKING, "Rotary Rack Oven"),
		"description": "Bake the mixed dough.",
	},
	{
		"process_code": "PRC-FIL",
		"process_name": "Filling",
		"process_sequence": 3,
		"qc_required": 1,
		"allow_inward_entry": 1,
		"machine_types": (
			TYPE_FILLING,
			"VFFS Packing Line",
			"Semi-Automatic Filling Machine",
		),
		"description": "Fill and pack the baked product.",
	},
)


def _machine_type_id(machine_type_name):
	"""The TYP- id behind a readable type name.

	The seed speaks in names because that is what the BRD gives, but the child table
	stores the id -- the name is only the title field.
	"""
	return frappe.db.get_value(
		MACHINE_TYPE_DOCTYPE, {"machine_type_name": machine_type_name}, "name"
	)


def seed_machine_types():
	"""Create the missing categories. An existing one is left exactly as it is."""
	if not frappe.db.exists("DocType", MACHINE_TYPE_DOCTYPE):
		return

	for machine_type_name, description in MACHINE_TYPES:
		if _machine_type_id(machine_type_name):
			continue
		frappe.get_doc(
			{
				"doctype": MACHINE_TYPE_DOCTYPE,
				"machine_type_name": machine_type_name,
				"description": description,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


def seed_machines(force=0):
	"""Put the example machines on a site that has none.

	Guarded differently from the types and processes, and deliberately. Those are named
	by the BRD, so a missing one is a gap worth filling on every migrate. These are
	invented, so the per-record "create if absent" guard would be a trap: delete an
	example machine and the next migrate would raise it from the dead.

	An empty table is most of that signal, but not all of it: delete the examples once the
	real machines are in and the table is empty again, which would bring them back. So a
	flag records that this has run, and it is the flag -- not the row count -- that makes
	the decision permanent.

	`force` is for asking by hand, and is never passed by migrate. It skips both of those
	checks but not the per-name one, so calling it twice still cannot duplicate a machine.
	"""
	if not frappe.db.exists("DocType", MACHINE_DOCTYPE):
		return
	if not cint(force):
		if cint(frappe.db.get_default(MACHINES_SEEDED_FLAG)):
			return
		if frappe.db.count(MACHINE_DOCTYPE):
			# Somebody got here first. Record that, so emptying the table later does not
			# re-open the question.
			frappe.db.set_default(MACHINES_SEEDED_FLAG, "1")
			return

	for machine_name, type_name, capacity, uom, status in MACHINES:
		if frappe.db.exists(MACHINE_DOCTYPE, {"machine_name": machine_name}):
			continue
		type_id = _machine_type_id(type_name)
		if not type_id:
			# Rule 1 -- every machine belongs to a type -- so no type means no machine.
			continue
		frappe.get_doc(
			{
				"doctype": MACHINE_DOCTYPE,
				"machine_name": machine_name,
				"machine_type": type_id,
				"max_capacity": capacity,
				"capacity_uom": uom,
				"status": status,
			}
		).insert(ignore_permissions=True)

	frappe.db.set_default(MACHINES_SEEDED_FLAG, "1")


def seed_processes():
	"""Create the three BRD processes, each linked to the machine type it runs on."""
	if not frappe.db.exists("DocType", PROCESS_DOCTYPE):
		return

	for spec in PROCESSES:
		# Keyed on the code, which IS the record id -- but also checked by name, since
		# the name is unique too and a process added by hand may carry a different code.
		if frappe.db.exists(PROCESS_DOCTYPE, spec["process_code"]) or frappe.db.exists(
			PROCESS_DOCTYPE, {"process_name": spec["process_name"]}
		):
			continue

		type_ids = [t for t in map(_machine_type_id, spec["machine_types"]) if t]
		if not type_ids:
			# Rule 2 would reject the insert anyway; skipping quietly keeps a migrate
			# green rather than failing it over starter data.
			continue

		doc = frappe.get_doc(
			{
				"doctype": PROCESS_DOCTYPE,
				"process_code": spec["process_code"],
				"process_name": spec["process_name"],
				"process_sequence": spec["process_sequence"],
				"description": spec["description"],
				"qc_required": spec["qc_required"],
				"allow_inward_entry": spec["allow_inward_entry"],
				"allow_machine_assignment": 0,
				"is_active": 1,
			}
		)
		for type_id in type_ids:
			doc.append("machine_types", {"machine_type": type_id})
		doc.insert(ignore_permissions=True)


def execute():
	# Types first: both of the others resolve a type name to its TYP- id.
	seed_machine_types()
	seed_machines()
	seed_processes()
	frappe.db.commit()
