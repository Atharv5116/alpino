"""Machine Run — several Sub POs merged onto one machine on one day.

Created and changed only by the Store Planning board (alpinos.production.store_planning),
which is where the merge rules (same FG item, same process, machine capacity) are checked.
The controller keeps the one thing that must always hold whoever saves it: the total is
the sum of its rows.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

STATUS_PLANNED = "Planned"
STATUS_CANCELLED = "Cancelled"


class MachineRun(Document):
	def validate(self):
		seen = set()
		for row in self.get("sub_orders") or []:
			if row.sub_order in seen:
				frappe.throw(
					_("{0} appears twice in this Machine Run.").format(row.sub_order),
					title=_("Duplicate Sub PO"),
				)
			seen.add(row.sub_order)
		self.total_qty = flt(sum(flt(row.qty) for row in self.get("sub_orders") or []), 3)
		if not self.status:
			self.status = STATUS_PLANNED
