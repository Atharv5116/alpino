"""Master-data changes that an open sub order must veto.

The rule behind all of these is one thing said three ways: a plan on the floor points at a
machine, a process and a machine type, and quietly changing what those MEAN while the plan
is running leaves the plan pointing at something else. So the master is frozen for as long
as an open sub order depends on it, and it is the master that refuses -- not the screen,
because a REST call or an import would walk straight past a screen.

"Open" means a sub order that is not cancelled and has not finished: work that somebody is
still going to do.
"""

import frappe
from frappe import _
from frappe.utils import cint

from alpinos.production import constants as C
from alpinos.production.work_order_fields import (
	ASSIGNED_MACHINE_FIELD,
	ASSIGNED_PROCESS_FIELD,
	PARENT_FIELD,
)

#: FRD Task 20, word for word.
CATEGORY_CHANGE_MESSAGE = "Cannot change machine category while active plans are running. Close plans first."

#: A sub order nobody is going to act on any more does not hold anything hostage.
_CLOSED_STATUSES = ("Completed", "Stopped", "Closed", "Cancelled")


def _open_sub_orders(**filters):
	filters.update({
		PARENT_FIELD: ("is", "set"),
		"docstatus": ("<", 2),
		"status": ("not in", _CLOSED_STATUSES),
	})
	return frappe.get_all("Work Order", filters=filters, pluck="name", limit=5)


def _changed(doc, fieldname):
	"""The stored value differs from the one being saved."""
	if doc.is_new():
		return False
	before = doc.get_doc_before_save()
	if not before:
		return False
	return (before.get(fieldname) or "") != (doc.get(fieldname) or "")


# ----------------------------------------------------------------- Machine

def guard_machine(doc, method=None):
	"""MM: a machine assigned to an open sub order is not repurposed underneath it.

	Three fields, one reason each:

	    status              taking it off Active un-plans work already scheduled on it
	    machine_type        the type decides which processes may use it at all
	    filling category    8.4 reads it to decide whether a machine may run an SKU

	Only a CHANGE is refused; saving the machine with everything else edited is fine.
	"""
	fields = {
		"status": _("status"),
		"machine_type": _("machine type"),
		"filling_process_category": _("filling category"),
	}
	changing = [f for f in fields if _changed(doc, f)]
	if not changing:
		return
	# Moving a machine to Active is only ever making it more available.
	if changing == ["status"] and doc.status == C.MACHINE_ACTIVE:
		return

	busy = _open_sub_orders(**{ASSIGNED_MACHINE_FIELD: doc.name})
	if not busy:
		return

	if "filling_process_category" in changing:
		# The exact wording the FRD asks for.
		frappe.throw(_(CATEGORY_CHANGE_MESSAGE), title=_("Machine Is In Use"))

	frappe.throw(
		_("{0} is assigned to sub orders that have not finished: {1}. Its {2} cannot be "
		  "changed until those are closed.").format(
			doc.name, ", ".join(busy), " and ".join(fields[f] for f in changing)),
		title=_("Machine Is In Use"),
	)


# ---------------------------------------------------------- Process Master

def guard_process_machine_types(doc, method=None):
	"""PR-03/PR-04: a process may only be built from Machine Types that are still live.

	An inactive type is a category the factory has retired. Linking one gives the process a
	pool of machines that no screen will ever offer -- Assign Process filters its machine
	picker by the linked types and by Active status -- so the process looks configured and
	then quietly matches nothing.

	Forward-only: a row that was already there when the type was retired is left alone, so
	retiring a type does not lock every process that ever used it. Only a row being ADDED
	now is refused.
	"""
	rows = doc.get("machine_types") or []
	if not rows:
		return

	before = doc.get_doc_before_save() if not doc.is_new() else None
	already = {
		row.machine_type for row in (before.get("machine_types") or [])
	} if before else set()

	added = [row.machine_type for row in rows if row.machine_type and row.machine_type not in already]
	if not added:
		return

	inactive = frappe.get_all(
		"Machine Type",
		filters={"name": ("in", added), "is_active": 0},
		pluck="name",
	)
	if inactive:
		frappe.throw(
			_("These Machine Types are inactive, so they cannot be linked to a process: {0}.").format(
				frappe.bold(", ".join(sorted(inactive)))),
			title=_("Inactive Machine Type"),
		)


def guard_process(doc, method=None):
	"""PR-08: a process assigned to an open sub order cannot be deactivated."""
	guard_process_machine_types(doc, method)
	if doc.is_new() or cint(doc.is_active):
		return
	before = doc.get_doc_before_save()
	if not before or not cint(before.is_active):
		return  # already inactive; nothing is changing

	busy = _open_sub_orders(**{ASSIGNED_PROCESS_FIELD: doc.name})
	if busy:
		frappe.throw(
			_("{0} is assigned to sub orders that have not finished: {1}. Close those "
			  "before deactivating it.").format(doc.name, ", ".join(busy)),
			title=_("Process Is In Use"),
		)


# ------------------------------------------------------------ Machine Type

def guard_machine_type(doc, method=None):
	"""MT-05, and the sub orders behind it.

	The Machine Type doctype already refuses to deactivate while an Active machine carries
	it. This adds the other half: a machine of this type standing on an open sub order,
	even if that machine is no longer Active itself.
	"""
	if doc.is_new() or cint(doc.is_active):
		return
	before = doc.get_doc_before_save()
	if not before or not cint(before.is_active):
		return

	machines = frappe.get_all("Machine", filters={"machine_type": doc.name}, pluck="name")
	if not machines:
		return
	busy = _open_sub_orders(**{ASSIGNED_MACHINE_FIELD: ("in", machines)})
	if busy:
		frappe.throw(
			_("Machines of type {0} are assigned to sub orders that have not finished: {1}.").format(
				doc.name, ", ".join(busy)),
			title=_("Machine Type Is In Use"),
		)
