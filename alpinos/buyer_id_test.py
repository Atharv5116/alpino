"""Changes(HP) #40: Buyer Master IDs read OBM-<financial year>-<number>.

Run:  bench --site alpinos.test execute alpinos.buyer_id_test.run

Rolled back at the end, including the series counter.
"""

import frappe

from alpinos.alpinos_development.doctype.buyer_master import buyer_master as B

R = []


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


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _highest():
	return frappe.db.sql(
		"SELECT MAX(CAST(SUBSTRING_INDEX(name, '-', -1) AS UNSIGNED)) FROM `tabBuyer Master` WHERE name LIKE 'OBM-%%'"
	)[0][0] or 0


def _run():
	check("financial year code: 1 April starts the year, 31 March ends it", lambda: _assert(
		(B.financial_year_code("2026-04-01"), B.financial_year_code("2027-03-31"), B.financial_year_code("2026-03-31"),
		 B.financial_year_code("2099-12-01")) == ("2627", "2627", "2526", "9900"),
		"wrong FY codes"))

	# Start from a site that has never used the new counter.
	frappe.db.sql("DELETE FROM `tabSeries` WHERE name = %s", B.BUYER_SERIES_KEY)
	highest = _highest()

	def _new_id_format_and_continuity():
		doc = frappe.new_doc("Buyer Master")
		doc.autoname()
		fy = B.financial_year_code()
		_assert(doc.name == f"OBM-{fy}-{highest + 1:05d}", f"got {doc.name}, expected OBM-{fy}-{highest + 1:05d}")

	check("a new buyer gets OBM-<FY>-<next number>, continuing after the existing IDs", _new_id_format_and_continuity)

	def _counter_runs_on():
		a = B.next_buyer_id()
		b = B.next_buyer_id()
		_assert(int(b.rsplit("-", 1)[1]) == int(a.rsplit("-", 1)[1]) + 1, f"{a} then {b}")

	check("the counter runs on from one buyer to the next", _counter_runs_on)

	def _one_counter_across_years():
		this_year = B.next_buyer_id("2026-09-14")
		next_year = B.next_buyer_id("2027-04-01")
		_assert(next_year.startswith("OBM-2728-"), next_year)
		_assert(int(next_year.rsplit("-", 1)[1]) == int(this_year.rsplit("-", 1)[1]) + 1,
			"the number restarted in the new financial year")

	check("a new financial year changes the year part but not the running number", _one_counter_across_years)

	def _taken_number_is_skipped():
		fy = B.financial_year_code()
		current = frappe.db.sql("SELECT current FROM `tabSeries` WHERE name = %s", B.BUYER_SERIES_KEY)[0][0]
		taken = f"OBM-{fy}-{current + 1:05d}"
		frappe.db.sql("INSERT INTO `tabBuyer Master` (name, creation, modified) VALUES (%s, NOW(), NOW())", taken)
		got = B.next_buyer_id()
		_assert(got != taken and got == f"OBM-{fy}-{current + 2:05d}", f"got {got} with {taken} already taken")

	check("a number already in use is skipped, not duplicated", _taken_number_is_skipped)

	check("existing buyer IDs are untouched", lambda: _assert(
		frappe.db.count("Buyer Master", {"name": ["like", "OBM-2026-%"]}) > 0 or not frappe.db.count("Buyer Master"),
		"old OBM-2026 IDs are gone"))
