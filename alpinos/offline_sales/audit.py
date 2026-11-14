"""The common Activity / Audit Trail (document Section 1, 5.1 and 5.2).

Field Change Log is the one trail for the whole Offline Sales workflow: the Sales Order trail
(sales_order_trail) already writes to it with action, role and SKU. This module is the shared
writer and reader for everything else, and the reader is what the forms' Activity panel calls.

An entry is immutable for business users: FieldChangeLog refuses an edit, and a delete by
anyone but Administrator.

Event families wired in build 1: Buyer creation, correction, approval, On Hold, Inactive,
Reactivation, Cancellation, approval escalation, assignment changes, Buyer Catalog setup and
changes (manual and from a submitted Sales Order). Sales Order creation, changes and submission
are logged by sales_order_trail; Opportunity events by offline_sales.opportunity. Link, Quotation,
payment and reminder events come with their modules.
"""

import frappe
from frappe import _

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import (
	acting_role,
	log_field_change,
)


def log(doctype, name, action, field=None, old=None, new=None, reason=None, item_code=None, after_submit=0, role=None):
	"""One trail entry. Never raises (a failed log must not undo the action it records).
	`role` overrides the acting user's role, e.g. "System" for what the system does on its own."""
	log_field_change(
		doctype,
		name,
		field or action,
		old,
		new,
		after_submit=after_submit,
		action=action,
		item_code=item_code,
		reason=reason,
		user_role=role or acting_role(),
	)


def status_change(doctype, name, action, old_status, new_status, reason=None):
	log(doctype, name, action, _("Status"), old_status or "", new_status, reason=reason)


@frappe.whitelist()
def get_trail(doctype, name, limit=500):
	"""Trail entries of one record, newest first, for anyone who may read the record."""
	# company-scope: n/a (reads the trail of one record after its own read permission check)
	if doctype not in ("Buyer Master", "Opportunity", "Quotation", "Sales Order"):
		frappe.throw(_("No Activity Trail for {0}.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	rows = frappe.get_all(
		"Field Change Log",
		filters={"reference_doctype": doctype, "reference_name": name},
		fields=[
			"changed_on", "action", "changed_by", "user_role", "field_label", "item_code",
			"previous_value", "new_value", "reason",
		],
		order_by="changed_on desc, creation desc",
		limit_page_length=int(limit or 500),
		ignore_permissions=True,
	)
	names = {r.changed_by for r in rows if r.changed_by}
	full = dict(frappe.get_all("User", filters={"name": ("in", list(names))}, fields=["name", "full_name"], as_list=True)) if names else {}
	for r in rows:
		r.changed_by_name = full.get(r.changed_by) or r.changed_by
	return rows
