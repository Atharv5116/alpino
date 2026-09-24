"""Changes(HP) #46: existing Buyer Master IDs reformatted to OBM-<financial year>-<number>.

Run:  bench --site alpinos.test execute alpinos.buyer_id_reformat_test.run

Fixtures are written straight to the tables, the rename is driven with `only` so it never
touches a real buyer, and everything is ROLLED BACK at the end: the tool commits, so commits
are ignored while the suite runs, exactly as the other suites do it.
"""

import random

import frappe

from alpinos import buyer_id_reformat as R

RESULTS = []


def check(label, fn):
	try:
		fn()
		RESULTS.append(("PASS", label, ""))
	except AssertionError as e:
		RESULTS.append(("FAIL", label, str(e)))
	except Exception as e:
		RESULTS.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.db_insert()
	return doc


def _buyer(name, **extra):
	return _insert("Buyer Master", name=name, buyer_name=name, channel="Offline", **extra).name


def run():
	RESULTS.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RESULTS)
	for status, label, detail in RESULTS:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RESULTS if r[0] == 'PASS')}/{len(RESULTS)} passed")
	return RESULTS


def _run():
	# ------------------------------------------------------------- the mapping
	def _the_rule():
		_assert(R.target_name("OBM-2026-00678") == "OBM-2627-00678", R.target_name("OBM-2026-00678"))
		_assert(R.target_name("OBM-2025-00042") == "OBM-2526-00042", R.target_name("OBM-2025-00042"))
		# The number keeps its padding and its length, whatever it is.
		_assert(R.target_name("OBM-2026-1") == "OBM-2627-1", R.target_name("OBM-2026-1"))

	check("#46 OBM-2026-00678 becomes OBM-2627-00678, the number untouched", _the_rule)

	def _left_alone():
		_assert(R.target_name("OBM-2627-01027") is None, "a financial-year id was rewritten")
		_assert(R.target_name("OBM-2526-00001") is None, "a financial-year id was rewritten")
		_assert(R.target_name("CUST-0001") is None, "a name outside the format was rewritten")
		_assert(R.target_name("OBM-2026") is None, "a name with no number was rewritten")
		_assert(R._ambiguous("OBM-2021-00003"), "OBM-2021 is not flagged as ambiguous")
		_assert(not R._ambiguous("OBM-2026-00003"), "a plain calendar year was called ambiguous")

	check("#46 ids already in the format, and the ambiguous 2021, are left alone", _left_alone)

	# ------------------------------------------------------- rename + its links
	# Digits only: a buyer id ends in a number, which is what the tool matches on.
	tag = f"{random.randint(1000, 9999)}"
	old = f"OBM-2026-9{tag}"
	child = f"OBM-2026-8{tag}"
	parent_after = f"OBM-2627-9{tag}"
	_buyer(old, is_parent=1)
	_buyer(child, parent_buyer=old)
	so = _insert(
		"Sales Order",
		name=f"BIR-{tag}-SO",
		docstatus=1,
		customer=f"BIR-{tag}-CUST",
		transaction_date=frappe.utils.today(),
		custom_offline_buyer_master=old,
		company=frappe.defaults.get_global_default("company"),
	).name

	out = R.run(apply=1, only=[old])

	def _renamed():
		_assert(out["renamed"] == 1, f"renamed {out['renamed']}, failed: {out['failed']}")
		_assert(frappe.db.exists("Buyer Master", parent_after), f"{parent_after} does not exist")
		_assert(not frappe.db.exists("Buyer Master", old), f"{old} is still there")

	check("#46 the buyer is renamed to its financial-year id", _renamed)

	def _links_follow():
		_assert(
			frappe.db.get_value("Sales Order", so, "custom_offline_buyer_master") == parent_after,
			f"the Sales Order still points at {frappe.db.get_value('Sales Order', so, 'custom_offline_buyer_master')}",
		)
		_assert(
			frappe.db.get_value("Buyer Master", child, "parent_buyer") == parent_after,
			f"the child still points at {frappe.db.get_value('Buyer Master', child, 'parent_buyer')}",
		)

	check("#46 the Sales Order and the child site follow the rename", _links_follow)

	def _customer_is_not_renamed():
		# The Customer id is the business name plus GSTIN and is quoted outside the system.
		_assert(
			frappe.db.get_value("Sales Order", so, "customer") == f"BIR-{tag}-CUST",
			"the Sales Order's Customer was changed by a buyer rename",
		)

	check("#46 the buyer's Customer id is not touched", _customer_is_not_renamed)

	# --------------------------------------------------------------- collisions
	taken_old = f"OBM-2026-7{tag}"
	taken_new = f"OBM-2627-7{tag}"
	_buyer(taken_old)
	_buyer(taken_new)
	clash = R.run(apply=1, only=[taken_old])

	def _collision_is_refused():
		_assert(clash["renamed"] == 0, "a buyer was renamed onto an id already in use")
		_assert(
			[p["old"] for p in clash["target_taken"]] == [taken_old],
			f"the clash was not reported: {clash['target_taken']}",
		)
		_assert(frappe.db.exists("Buyer Master", taken_old), "the buyer disappeared instead")

	check("#46 an id already in use is reported, never merged into", _collision_is_refused)

	# ------------------------------------------------------------------ dry run
	dry_old = f"OBM-2026-6{tag}"
	_buyer(dry_old)

	dry = R.run(apply=0, only=[dry_old])

	def _dry_run_writes_nothing():
		_assert(dry["mode"] == "DRY-RUN", dry["mode"])
		_assert(dry["to_rename"] == 1 and dry["renamed"] == 0, f"{dry['to_rename']} / {dry['renamed']}")
		_assert(frappe.db.exists("Buyer Master", dry_old), "a dry run renamed a buyer")
		_assert(dry["sample"][0] == {"old": dry_old, "new": f"OBM-2627-6{tag}"}, dry["sample"][0])

	check("#46 a dry run reports the pairs and writes nothing", _dry_run_writes_nothing)
