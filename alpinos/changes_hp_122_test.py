"""Changes(HP) #122: Accounts Format Report, Buyer ID inside Terms of Delivery. TEST sites only.

Run:  bench --site <test site> execute alpinos.changes_hp_122_test.run

Read only: the report is run on orders already on the site; nothing is written.
"""

import frappe

from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as AFR

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _rows(so):
	return AFR.execute(frappe._dict(sales_order=so))[1]


def _orders(sql):
	return [r[0] for r in frappe.db.sql(sql)]


def run():
	R.clear()
	frappe.set_user("Administrator")

	def _no_column():
		cols = [c["fieldname"] for c in AFR.get_columns()]
		_assert("buyer_id" not in cols, "a separate Buyer ID column is still there")
		_assert("Buyer ID" not in [c["label"] for c in AFR.get_columns()], "a Buyer ID label is still there")
		_assert("terms_of_delivery" in cols, "Terms of Delivery column is gone")

	check("#122 no separate Buyer ID column; Terms of Delivery kept", _no_column)

	def _format():
		got = AFR._with_buyer_id(
			"PL PO No: 1 / Total Box: 24 / Total Weight: 229.20 / Transporter: Delhivery", "OBM-2026-00655"
		)
		want = "PL PO No: 1 / Total Box: 24 / Total Weight: 229.20 / Transporter: Delhivery / Buyer ID: OBM-2026-00655"
		_assert(got == want, got)
		_assert(AFR._with_buyer_id("", "OBM-2026-00655") == "Buyer ID: OBM-2026-00655", "no Pick List row")
		_assert(AFR._with_buyer_id(None, None) == "", "no Pick List, no buyer")

	check("#122 exact format from the sheet", _format)

	picked = _orders(
		"""SELECT so.name FROM `tabSales Order` so
		WHERE so.docstatus = 1 AND IFNULL(so.custom_offline_buyer_master, '') <> ''
			AND IFNULL(so.custom_only_invoice, 0) = 0 AND IFNULL(so.custom_rl_no_invoice, 0) = 0
			AND (SELECT COUNT(*) FROM `tabPick List` p WHERE p.custom_sales_order_id = so.name AND p.docstatus = 1) = 1
		ORDER BY so.creation DESC LIMIT 5"""
	)

	def _real_orders():
		_assert(picked, "no picked order with a buyer on this site")
		for so in picked:
			buyer = frappe.db.get_value("Sales Order", so, "custom_offline_buyer_master")
			pl_text = AFR._pl_header(so).get("terms_of_delivery")
			rows = _rows(so)
			_assert(rows, f"{so}: no rows")
			for r in rows:
				tod = r.get("terms_of_delivery") or ""
				_assert(tod == f"{pl_text} / Buyer ID: {buyer}", f"{so}: {tod!r}")
				_assert("buyer_id" not in r, f"{so}: row still carries buyer_id")

	check(f"#122 report rows end with the order's Buyer ID ({len(picked)} picked orders)", _real_orders)

	parts = _orders(
		"""SELECT so.name FROM `tabSales Order` so
		WHERE so.docstatus = 1 AND IFNULL(so.custom_offline_buyer_master, '') <> ''
			AND IFNULL(so.custom_rl_no_invoice, 0) = 0
			AND (SELECT COUNT(*) FROM `tabPick List` p WHERE p.custom_sales_order_id = so.name AND p.docstatus = 1) > 1
		ORDER BY so.creation DESC LIMIT 3"""
	)

	def _partial():
		if not parts:
			return
		for so in parts:
			buyer = frappe.db.get_value("Sales Order", so, "custom_offline_buyer_master")
			tods = {r.get("terms_of_delivery") for r in _rows(so)}
			_assert(len(tods) > 1, f"{so}: parts no longer keep their own Terms of Delivery: {tods}")
			_assert(all(t.endswith(f" / Buyer ID: {buyer}") for t in tods), f"{so}: {tods}")

	check(f"#122 partial orders: each part keeps its own text, all end with the Buyer ID ({len(parts)} orders)", _partial)

	only = _orders(
		"""SELECT so.name FROM `tabSales Order` so
		WHERE so.docstatus = 1 AND IFNULL(so.custom_only_invoice, 0) = 1 AND IFNULL(so.custom_offline_buyer_master, '') <> ''
			AND NOT EXISTS (SELECT 1 FROM `tabPick List` p WHERE p.custom_sales_order_id = so.name AND p.docstatus = 1)
		ORDER BY so.creation DESC LIMIT 3"""
	)

	def _only_invoice():
		temp = []
		if not only:
			# none on this site: flag an unpicked order as Only Invoice for the check, then roll back
			temp = _orders(
				"""SELECT so.name FROM `tabSales Order` so
				WHERE so.docstatus = 1 AND IFNULL(so.custom_offline_buyer_master, '') <> ''
					AND IFNULL(so.custom_rl_no_invoice, 0) = 0
					AND NOT EXISTS (SELECT 1 FROM `tabPick List` p WHERE p.custom_sales_order_id = so.name AND p.docstatus < 2)
				ORDER BY so.creation DESC LIMIT 1"""
			)
		_assert(only or temp, "no order to check")
		frappe.db.savepoint("hp122")
		try:
			for so in temp:
				frappe.db.set_value("Sales Order", so, "custom_only_invoice", 1, update_modified=False)
			for so in only or temp:
				buyer = frappe.db.get_value("Sales Order", so, "custom_offline_buyer_master")
				rows = _rows(so)
				_assert(rows, f"{so}: no rows")
				for r in rows:
					_assert(r.get("terms_of_delivery") == f"Buyer ID: {buyer}", f"{so}: {r.get('terms_of_delivery')!r}")
		finally:
			frappe.db.rollback(save_point="hp122")

	check(f"#122 Only Invoice orders (no Pick List) still show the Buyer ID (a real one, else one flagged and rolled back)", _only_invoice)

	for status, label, err in R:
		print(f"[{status}] {label} {err}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
