"""Link the BRD's named machine models to the processes that run on them.

The three seeded processes were first written against the broad categories only (Mixing
Machine, Baking Machine, Filling Machine), which left Spiral Dough Mixer, Rotary Rack
Oven, VFFS Packing Line and Semi-Automatic Filling Machine linked to nothing -- so a
machine filed under the model it actually is reached no process at all. BRD 3.1 maps each
process to its model, and rule 5 lets a process hold several types, so both belong.

A patch rather than part of `alpinos.production.seed`, deliberately: seed runs on every
migrate, and adding a row there would re-add a type the factory had chosen to remove.
This runs once.
"""

import frappe

from alpinos.production.seed import PROCESSES, _machine_type_id


def execute():
	if not frappe.db.exists("DocType", "Process Master"):
		return

	for spec in PROCESSES:
		name = spec["process_code"]
		if not frappe.db.exists("Process Master", name):
			continue

		doc = frappe.get_doc("Process Master", name)
		present = {row.machine_type for row in doc.machine_types}
		added = False
		for type_name in spec["machine_types"]:
			type_id = _machine_type_id(type_name)
			if not type_id or type_id in present:
				continue
			doc.append("machine_types", {"machine_type": type_id})
			present.add(type_id)
			added = True

		if added:
			# Saved through the document so ProcessMaster.validate still runs -- the
			# duplicate check in particular, which is the reason rows are appended rather
			# than written straight to the child table.
			doc.save(ignore_permissions=True)

	frappe.db.commit()
