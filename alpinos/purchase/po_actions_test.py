"""Which Purchase Order actions each role is offered (BRD 1.4 / 3.3).

The suites around this one check that an action DOES the right thing. None of them ask
the question a user actually hits first: would the button have been there at all, for
the role the BRD names? BRD 3.3 gives both "Draft -> Submit" and "Approved -> Send to
Supplier" to the "Purchase Team", and a buyer holding only ERPNext's core Purchase User
/ Purchase Manager roles was offered neither -- so an order could only be moved by a
System Manager, which read on screen as "only the approver can send to supplier".

The grid endpoint and the Purchase Inward line guard are covered by
regression_test.run_wave_h, which builds its own fixtures; they are deliberately not
repeated here.

Run: bench --site <site> execute alpinos.purchase.po_actions_test.run
"""

import frappe

from alpinos.purchase import constants as C
from alpinos.purchase import purchase_order_approval as A


def _actions_for(roleset, doc):
	"""available_actions as a user holding exactly `roleset` would see it.

	Roles are swapped rather than users created: the transition table is pure, and a
	fixture user would only add a permission surface that is not what is under test.
	"""
	original = frappe.get_roles
	frappe.get_roles = lambda user=None, _r=roleset: _r
	try:
		return [a["action"] for a in A.available_actions(doc)]
	finally:
		frappe.get_roles = original


def _po(status, docstatus):
	return frappe._dict({"docstatus": docstatus, A.STATUS_FIELD: status})


def run():
	results = []

	def check(label, fn):
		try:
			fn()
			results.append(("PASS", label, ""))
		except AssertionError as exc:
			results.append(("FAIL", label, str(exc)))
		except Exception as exc:  # noqa: BLE001
			results.append(("ERROR", label, f"{type(exc).__name__}: {exc}"))

	def _assert(cond, msg=""):
		if not cond:
			raise AssertionError(msg)

	draft = _po(C.PO_DRAFT, 0)
	pending = _po(C.PO_PENDING_APPROVAL, 0)
	approved = _po(C.PO_APPROVED, 1)
	sent = _po(C.PO_SENT_TO_SUPPLIER, 1)
	rejected = _po(C.PO_REJECTED, 0)

	# BRD 3.3, "Performed By: Purchase Team".
	check(
		"BRD 3.3 a core Purchase User may Submit for Approval",
		lambda: _assert(
			"Submit for Approval" in _actions_for(["Purchase User"], draft),
			f"core Purchase User sees {_actions_for(['Purchase User'], draft)}",
		),
	)
	check(
		"BRD 3.3 a core Purchase Manager may Send to Supplier",
		lambda: _assert(
			"Send to Supplier" in _actions_for(["Purchase Manager"], approved),
			f"core Purchase Manager sees {_actions_for(['Purchase Manager'], approved)}",
		),
	)
	check(
		"BRD 3.3 the module Purchase role may Submit for Approval",
		lambda: _assert(
			"Submit for Approval" in _actions_for([C.ROLE_PURCHASE_USER], draft),
			f"{C.ROLE_PURCHASE_USER} sees {_actions_for([C.ROLE_PURCHASE_USER], draft)}",
		),
	)
	# BRD 3.3 "Rejected -> Edit -> Draft -> Submit": a corrected order goes back the same way.
	check(
		"BRD 3.3 a rejected order can be resubmitted by the Purchase Team",
		lambda: _assert(
			"Submit for Approval" in _actions_for(["Purchase User"], rejected),
			f"core Purchase User sees {_actions_for(['Purchase User'], rejected)}",
		),
	)

	# BR-PO-04 has to survive widening the submitter set: approving is still the
	# Authorized Approver's alone.
	def buyer_cannot_approve():
		acts = _actions_for(["Purchase User"], pending)
		_assert("Approve" not in acts, f"a plain buyer can approve: {acts}")
		_assert("Reject" not in acts, f"a plain buyer can reject: {acts}")
		_assert("Return for Correction" not in acts, f"a plain buyer can return: {acts}")

	check("BR-PO-04 a plain buyer cannot Approve, Reject or Return", buyer_cannot_approve)
	check(
		"BR-PO-04 the Authorized Approver can Approve",
		lambda: _assert(
			"Approve" in _actions_for(["Purchase Manager"], pending),
			f"the approver sees {_actions_for(['Purchase Manager'], pending)}",
		),
	)

	# BRD 1.4: a sent order carries no further transition. Create Purchase Inward is
	# drawn from the status and the inward count, not from the transition table.
	check(
		"BRD 1.4 a Sent to Supplier order offers no further transition",
		lambda: _assert(
			_actions_for(["Purchase Manager"], sent) == [],
			f"a sent order still offers {_actions_for(['Purchase Manager'], sent)}",
		),
	)

	width = max(len(r[1]) for r in results)
	print("\nPurchase Order action availability by role")
	print("=" * (width + 12))
	for state, label, detail in results:
		print(f"[{state}] {label.ljust(width)} {detail}")
	passed = sum(1 for r in results if r[0] == "PASS")
	print("-" * (width + 12))
	print(f"{passed}/{len(results)} passed")
	return results
