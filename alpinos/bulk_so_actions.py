"""Changes(HP) #105: bulk Reject and bulk Cancel of Sales Orders for the Admin (BA team).

The BA team works as System Manager, so that is the role these run for. Each order goes
through the same function its own screen uses, so every rule still applies one order at a
time (a reason is mandatory, a rejection only before a Pick List is submitted, a cancellation
blocked while a Pick List / Delivery Note is active, a Rejected order is never cancelled);
one order's refusal does not stop the others, and each result is reported.
"""

import frappe
from frappe import _

ADMIN_ROLE = "System Manager"


def _names(sales_orders):
	names = frappe.parse_json(sales_orders) if isinstance(sales_orders, str) else sales_orders
	return [n for n in (names or []) if n]


def _run(names, act):
	done, failed = [], []
	for i, name in enumerate(names):
		# one order's failure undoes that order only
		savepoint = f"so_bulk_{i}"
		frappe.db.savepoint(savepoint)
		try:
			act(name)
			frappe.db.commit()
			done.append(name)
		except Exception as e:
			frappe.db.rollback(save_point=savepoint)
			frappe.clear_messages()
			failed.append({"name": name, "error": frappe.utils.strip_html(str(e)) or type(e).__name__})
	return {"done": done, "failed": failed, "counts": {"done": len(done), "failed": len(failed)}}


@frappe.whitelist(methods=["POST"])
def bulk_reject(sales_orders, reason):
	# company-scope: n/a (each order goes through workflow_engine.reject_sales_order, which checks its company)
	frappe.only_for(ADMIN_ROLE)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Enter the reason for rejection."), title=_("Reason Required"))
	from alpinos.workflow_engine import reject_sales_order

	return _run(_names(sales_orders), lambda so: reject_sales_order(so, reason))


@frappe.whitelist(methods=["POST"])
def bulk_cancel(sales_orders, reason):
	# company-scope: n/a (each order goes through cancel_document / cancel_draft_sales_order)
	frappe.only_for(ADMIN_ROLE)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Please enter a reason for cancellation."), title=_("Reason Required"))
	from alpinos.sales_order_actions import cancel_draft_sales_order
	from alpinos.workflow_engine import cancel_document

	def cancel(so):
		docstatus = frappe.db.get_value("Sales Order", so, "docstatus")
		if docstatus is None:
			frappe.throw(_("No such Sales Order."))
		if docstatus == 0:
			cancel_draft_sales_order(so, reason)
		elif docstatus == 1:
			cancel_document("Sales Order", so, reason)
		else:
			frappe.throw(_("Already cancelled."))

	return _run(_names(sales_orders), cancel)
