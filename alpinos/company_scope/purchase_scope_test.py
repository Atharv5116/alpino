"""Company-wise access on the purchase pages: lists, screens, pickers, reports, recipients.

	bench --site <test site> execute alpinos.company_scope.purchase_scope_test.run

Header-only copies of real purchase documents are made in the default company (A) and in
a second company (B), named CS-PURCHASE-...; two users work with them:

	cs.purchase.a@example.com    Purchase Inward Admin + Purchase QC Manager in A only
	cs.purchase.ab@example.com   Purchase Inward Admin in A, Purchase Inward User in B

Everything made here is removed again at the end.
"""

import frappe

from alpinos.company_scope.testing import (
	ALL,
	as_user,
	cleanup_user,
	companies,
	copy_header,
	delete_copies,
	ensure_enabled,
	make_user,
	set_active,
)

R = []

U_A = "cs.purchase.a@example.com"
U_AB = "cs.purchase.ab@example.com"
PREFIX = "CS-PURCHASE-"

PO, INWARD, QC, GRN, PINV, QRN = (
	"Purchase Order", "Purchase Inward", "Purchase QC", "Purchase Receipt", "Purchase Invoice",
	"Purchase Quarantine",
)
#: doctype -> name stem of its copies (CS-PURCHASE-<stem>-A / -B)
STEMS = {PO: "PO", INWARD: "PI", QC: "QC", GRN: "GRN", PINV: "INV", QRN: "QRN"}


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _raises(fn, contains=None):
	try:
		fn()
	except frappe.PermissionError as e:
		if contains and contains.lower() not in str(e).lower():
			raise AssertionError(f"raised, but '{contains}' not in: {e}")
		return
	raise AssertionError("did not raise")


def _name(doctype, side):
	return f"{PREFIX}{STEMS[doctype]}-{side}"


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R


# --- fixtures ------------------------------------------------------------------------------


def _templates(A):
	from alpinos.purchase.purchase_order_force_close import FORCE_CLOSED_FIELD

	def one(sql, *args):
		rows = frappe.db.sql(sql, args)
		return rows[0][0] if rows else None

	return {
		# open for inward: the pending-receipts report and the inward PO picker list it
		PO: one(
			f"""select name from `tabPurchase Order` where company = %s and docstatus = 1
			and ifnull(custom_direct_purchase_invoice, 0) = 0
			and status not in ('Closed', 'Completed', 'On Hold')
			and ifnull(custom_pending_inward_qty, total_qty) > 0 and ifnull(`{FORCE_CLOSED_FIELD}`, 0) = 0
			and name not like 'CS-%%' order by creation desc limit 1""",
			A,
		),
		INWARD: one(
			"select name from `tabPurchase Inward` where company = %s and docstatus = 1 "
			"and name not like 'CS-%%' order by creation desc limit 1",
			A,
		),
		QC: one(
			"select name from `tabPurchase QC` where company = %s and name not like 'CS-%%' "
			"order by creation desc limit 1",
			A,
		),
		# a finally submitted module GRN: the invoice GRN picker lists it
		GRN: one(
			"select name from `tabPurchase Receipt` where company = %s and docstatus = 1 and is_return = 0 "
			"and ifnull(custom_purchase_inward, '') != '' and name not like 'CS-%%' order by creation desc limit 1",
			A,
		),
		PINV: one(
			"select name from `tabPurchase Invoice` where company = %s and is_return = 0 "
			"and ifnull(custom_grn, '') != '' and name not like 'CS-%%' order by creation desc limit 1",
			A,
		),
		QRN: one(
			"select name from `tabPurchase Quarantine` where company = %s and name not like 'CS-%%' "
			"order by creation desc limit 1",
			A,
		),
	}


def _make_copies(templates, A, B):
	made = {}
	for doctype, template in templates.items():
		if not template:
			continue
		overrides = {}
		if doctype == QC:
			# open, so the QC Pending report lists it
			overrides = {"qc_status": "Pending QC", "docstatus": 0}
		for side, company in (("A", A), ("B", B)):
			copy_header(doctype, template, _name(doctype, side), company, **overrides)
		made[doctype] = True
	frappe.db.commit()
	return made


def _cleanup():
	for doctype in STEMS:
		delete_copies(doctype, [_name(doctype, "A"), _name(doctype, "B")])
	for user in (U_A, U_AB):
		cleanup_user(user)
	frappe.db.commit()


# --- helpers -------------------------------------------------------------------------------


def _ours(rows, key="name"):
	return {r.get(key) if isinstance(r, dict) else r[0] for r in rows or []} & {
		_name(dt, side) for dt in STEMS for side in ("A", "B")
	}


def _list_names(doctype):
	"""Our copies of `doctype` on its list screen, as the session user sees them."""
	from alpinos.purchase import (
		grn_list_api,
		invoice_list_api,
		inward_list_api,
		po_list_api,
		qc_list_api,
		quarantine_list_api,
	)

	stem = f"{PREFIX}{STEMS[doctype]}-"
	if doctype == PO:
		out = po_list_api.get_purchase_order_list(po_id=stem, page_length=100)
	elif doctype == INWARD:
		out = inward_list_api.get_purchase_inward_list(search=stem, page_length=100)
	elif doctype == QC:
		out = qc_list_api.get_purchase_qc_list(qc_id=stem, page_length=100)
	elif doctype == GRN:
		out = grn_list_api.get_grn_list(grn_id=stem, page_length=100, with_actions=1)
	elif doctype == PINV:
		out = invoice_list_api.get_invoice_list(invoice_id=stem, page_length=100)
	else:
		out = quarantine_list_api.get_quarantine_list(quarantine_id=stem, page_length=100)
	return _ours(out["data"])


def _sides(doctype, *sides):
	return {_name(doctype, s) for s in sides}


# --- the test ------------------------------------------------------------------------------


def run():
	R.clear()
	frappe.set_user("Administrator")
	ensure_enabled()
	A, B, _C = companies()
	_cleanup()
	try:
		made = _make_copies(_templates(A), A, B)
		make_user(U_A, {A: ["Purchase Inward Admin", "Purchase QC Manager"]})
		make_user(U_AB, {A: ["Purchase Inward Admin"], B: ["Purchase Inward User"]}, active_company=A)

		_lists(made, A, B)
		_screens(made, A, B)
		_pickers(made, A, B)
		_mutations(made, A, B)
		_reports(made, A, B)
		_recipients(A, B)
		_coverage()
	finally:
		frappe.set_user("Administrator")
		_cleanup()
	return _report()


def _lists(made, A, B):
	for doctype in STEMS:
		if not made.get(doctype):
			R.append(("SKIP", f"{doctype} list", "no template document"))
			continue
		label = f"{doctype} list"
		set_active(U_AB, A)
		check(f"{label}: a user of A only gets A's rows", lambda dt=doctype: _assert(
			as_user(U_A, lambda: _list_names(dt)) == _sides(dt, "A"), as_user(U_A, lambda: _list_names(dt))))
		check(f"{label}: working in A hides B's rows", lambda dt=doctype: _assert(
			as_user(U_AB, lambda: _list_names(dt)) == _sides(dt, "A"), as_user(U_AB, lambda: _list_names(dt))))
		set_active(U_AB, B)
		check(f"{label}: switching to B shows B's rows", lambda dt=doctype: _assert(
			as_user(U_AB, lambda: _list_names(dt)) == _sides(dt, "B"), as_user(U_AB, lambda: _list_names(dt))))
		set_active(U_AB, ALL)
		check(f"{label}: All my companies shows both", lambda dt=doctype: _assert(
			as_user(U_AB, lambda: _list_names(dt)) == _sides(dt, "A", "B"), as_user(U_AB, lambda: _list_names(dt))))
		check(f"{label}: Administrator unchanged", lambda dt=doctype: _assert(
			_list_names(dt) == _sides(dt, "A", "B"), _list_names(dt)))
	set_active(U_AB, A)


def _screens(made, A, B):
	from alpinos.purchase import grn_edit, purchase_invoice, purchase_order_approval, quarantine

	if made.get(GRN):
		set_active(U_AB, A)
		check("GRN screen: B's GRN opened while in A asks to switch", lambda: _raises(
			lambda: as_user(U_AB, lambda: grn_edit.get_grn_context(_name(GRN, "B"))), "switch"))
		check("GRN screen: a user of A only cannot open B's GRN", lambda: _raises(
			lambda: as_user(U_A, lambda: grn_edit.get_grn_context(_name(GRN, "B")))))
		check("GRN screen: the Admin role held in A offers Cancel on A's GRN", lambda: _assert(
			as_user(U_AB, lambda: grn_edit.get_grn_context(_name(GRN, "A")))["can_cancel"]))
		set_active(U_AB, B)
		check("GRN screen: in B it opens, without the Admin's buttons", lambda: _assert(
			not as_user(U_AB, lambda: grn_edit.get_grn_context(_name(GRN, "B")))["can_cancel"]))
		check("GRN screen: Administrator unchanged", lambda: _assert(
			grn_edit.get_grn_context(_name(GRN, "B"))["can_cancel"]))
	if made.get(PINV):
		set_active(U_AB, A)
		check("Invoice screen: B's invoice opened while in A asks to switch", lambda: _raises(
			lambda: as_user(U_AB, lambda: purchase_invoice.get_invoice_context(_name(PINV, "B"))), "switch"))
		set_active(U_AB, B)
		check("Invoice screen: opens after switching to B", lambda: _assert(
			as_user(U_AB, lambda: purchase_invoice.get_invoice_context(_name(PINV, "B")))["name"] == _name(PINV, "B")))
	if made.get(QRN):
		set_active(U_AB, A)
		check("Quarantine screen: B's opened while in A asks to switch", lambda: _raises(
			lambda: as_user(U_AB, lambda: quarantine.get_quarantine_context(_name(QRN, "B"))), "switch"))
		check("Quarantine screen: A's opens; release offered by the A role", lambda: _assert(
			"can_release" in as_user(U_AB, lambda: quarantine.get_quarantine_context(_name(QRN, "A")))))
	if made.get(PO):
		set_active(U_AB, A)
		check("PO actions: B's order asked for while in A asks to switch", lambda: _raises(
			lambda: as_user(U_AB, lambda: purchase_order_approval.get_available_actions(_name(PO, "B"))), "switch"))
		set_active(U_AB, B)
		check("PO actions: answered after switching to B", lambda: _assert(
			"actions" in as_user(U_AB, lambda: purchase_order_approval.get_available_actions(_name(PO, "B")))))
	set_active(U_AB, A)


def _pickers(made, A, B):
	from alpinos.purchase import inward_api, invoice_list_api

	if made.get(PO):
		def po_picker():
			return _ours(inward_api.inward_po_query("Purchase Order", f"{PREFIX}PO-", "name", 0, 50, {}))

		set_active(U_AB, A)
		check("Inward PO picker: a user of A only gets A's orders", lambda: _assert(
			as_user(U_A, po_picker) == _sides(PO, "A"), as_user(U_A, po_picker)))
		set_active(U_AB, B)
		check("Inward PO picker: in B only B's orders", lambda: _assert(
			as_user(U_AB, po_picker) == _sides(PO, "B"), as_user(U_AB, po_picker)))
		check("Inward PO picker: Administrator unchanged", lambda: _assert(
			po_picker() == _sides(PO, "A", "B"), po_picker()))
		check("Inward PO lines: B's order refused to a user of A only", lambda: _raises(
			lambda: as_user(U_A, lambda: inward_api.get_purchase_order_items(_name(PO, "B")))))
	if made.get(GRN):
		def grn_picker(filters=None):
			return _ours(invoice_list_api.eligible_grn_query(
				"Purchase Receipt", f"{PREFIX}GRN-", "name", 0, 50, filters or {}))

		set_active(U_AB, A)
		check("Invoice GRN picker: a user of A only gets A's GRNs", lambda: _assert(
			as_user(U_A, grn_picker) == _sides(GRN, "A"), as_user(U_A, grn_picker)))
		set_active(U_AB, ALL)
		check("Invoice GRN picker: All my companies shows both", lambda: _assert(
			as_user(U_AB, grn_picker) == _sides(GRN, "A", "B"), as_user(U_AB, grn_picker)))
		check("Invoice GRN picker: the company passed narrows it", lambda: _assert(
			as_user(U_AB, lambda: grn_picker({"company": B})) == _sides(GRN, "B")))
		check("Invoice GRN picker: a company the user is not in gives nothing", lambda: _assert(
			not as_user(U_A, lambda: grn_picker({"company": B}))))
	set_active(U_AB, A)


def _mutations(made, A, B):
	from alpinos.purchase import grn_edit, purchase_invoice, purchase_order_approval

	if made.get(PO):
		check("Cancel PO: a user of A only cannot cancel B's order", lambda: _raises(
			lambda: as_user(U_A, lambda: purchase_order_approval.cancel_purchase_order(_name(PO, "B")))))
	if made.get(GRN):
		set_active(U_AB, B)
		check("Cancel GRN: the Admin role held in A does not count in B", lambda: _raises(
			lambda: as_user(U_AB, lambda: grn_edit.cancel_grn(_name(GRN, "B"))), "Only"))
		set_active(U_AB, A)
		check("Invoice from GRN: a user of A only cannot raise one on B's GRN", lambda: _raises(
			lambda: as_user(U_A, lambda: purchase_invoice.create_from_grn(_name(GRN, "B")))))
	frappe.db.rollback()


def _reports(made, A, B):
	from alpinos.alpinos_development.report.purchase_grn_register import purchase_grn_register as grn_register
	from alpinos.alpinos_development.report.purchase_pending_receipts import purchase_pending_receipts as pending
	from alpinos.alpinos_development.report.purchase_qc_pending import purchase_qc_pending as qc_pending

	cases = [
		("Pending Receipts", PO, pending),
		("GRN Register", GRN, grn_register),
		("QC Pending", QC, qc_pending),
	]
	set_active(U_AB, A)
	for label, doctype, module in cases:
		if not made.get(doctype):
			continue

		def names(filters=None, module=module):
			return _ours(module.execute(filters or {})[1])

		check(f"{label} report: a user of A only gets A's rows", lambda d=doctype, n=names: _assert(
			as_user(U_A, n) == _sides(d, "A"), as_user(U_A, n)))
		check(f"{label} report: the Company filter picks B", lambda d=doctype, n=names: _assert(
			as_user(U_AB, lambda: n({"company": B})) == _sides(d, "B")))
		check(f"{label} report: Administrator unchanged", lambda d=doctype, n=names: _assert(
			n() == _sides(d, "A", "B"), n()))

	# Stock reports: no company picked -> the companies the user works in.
	from alpinos.alpinos_development.report.stock_balance_report import stock_balance_report as balance
	from alpinos.alpinos_development.report.stock_by_batch_and_mrp import stock_by_batch_and_mrp as by_lot
	from alpinos.alpinos_development.report.stock_transfer_report import stock_transfer_report as transfer

	for label, module, filters in (
		("Stock Balance", balance, {}),
		("Stock by Batch and MRP", by_lot, {}),
		("Stock Transfer", transfer, {"from_date": "2000-01-01"}),
	):
		def companies_seen(module=module, filters=filters):
			return {r.get("company") for r in module.execute(dict(filters))[1]}

		set_active(U_AB, B)
		check(f"{label} report: working in B shows none of A's stock", lambda f=companies_seen: _assert(
			A not in as_user(U_AB, f), as_user(U_AB, f)))
		set_active(U_AB, A)
		check(f"{label} report: working in A shows only A's", lambda f=companies_seen: _assert(
			as_user(U_AB, f) <= {A}, as_user(U_AB, f)))


def _recipients(A, B):
	from alpinos.purchase import notifications

	check("QC alert: a QC Manager of A hears about A's inwards", lambda: _assert(
		U_A in notifications.qc_recipients(A)))
	check("QC alert: ...and not about B's", lambda: _assert(U_A not in notifications.qc_recipients(B)))


def _coverage():
	from alpinos.company_scope import lint

	mine = ("purchase/", "mrp_batch.py", "alpinos_development/doctype/purchase_qc/")
	left = [m for m in lint.report() if m["file"].startswith(mine)]
	check("every purchase endpoint follows the company", lambda: _assert(not left, left))
