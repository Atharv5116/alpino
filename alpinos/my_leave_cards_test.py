"""Home leave cards show the signed-in person's own balance. TEST sites only; rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.my_leave_cards_test.run
"""

import frappe
from frappe.utils import flt, nowdate

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
		frappe.set_user("Administrator")
		frappe.clear_cache()
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _people(leave_type, n=3):
	"""Active employees with a login and a current allocation of `leave_type`."""
	return frappe.db.sql(
		"""SELECT DISTINCT e.name, e.user_id FROM `tabEmployee` e
		   JOIN `tabLeave Allocation` la ON la.employee = e.name AND la.docstatus = 1
		        AND la.leave_type = %s AND %s BETWEEN la.from_date AND la.to_date
		   JOIN `tabUser` u ON u.name = e.user_id AND u.enabled = 1
		   WHERE e.status = 'Active' ORDER BY e.name LIMIT %s""",
		(leave_type, nowdate(), n),
		as_dict=True,
	)


def _run():
	from hrms.hr.doctype.leave_application.leave_application import get_leave_details

	from alpinos import my_leave_cards as M

	cards = frappe.get_all(
		"Number Card", filters={"type": "Report", "report_name": M.REPORT}, fields=["name", "report_field"]
	)
	M.convert_cards()
	# every personal leave card on the site, whether converted now or by an earlier migrate
	changed = [
		(c.name, frappe.parse_json(c.filters_json).get("leave_type"))
		for c in frappe.get_all("Number Card", filters={"type": "Custom", "method": M.METHOD}, fields=["name", "filters_json"])
	]

	def _converted():
		_assert(changed, "no leave balance cards on this site")
		_assert(all(frappe.db.get_value("Number Card", c.name, "type") == "Custom" for c in cards), "a card was left as a company total")
		for name, leave_type in changed:
			c = frappe.get_doc("Number Card", name)
			_assert(c.type == "Custom" and c.method == M.METHOD, (name, c.type, c.method))
			_assert(frappe.parse_json(c.filters_json) == {"leave_type": leave_type}, c.filters_json)
			_assert(not c.report_name and not c.show_percentage_stats, name)
		_assert(M.convert_cards() == [], "a second run changed cards again")

	check("Company-wide leave cards become personal cards (and a second run changes nothing)", _converted)

	def _own_figure():
		seen = 0
		for _name, leave_type in changed:
			for p in _people(leave_type):
				frappe.set_user(p.user_id)
				try:
					got = M.my_leave_balance(frappe.as_json({"leave_type": leave_type}))
					want = get_leave_details(p.name, nowdate())["leave_allocation"][leave_type]["remaining_leaves"]
				finally:
					frappe.set_user("Administrator")
				_assert(flt(got["value"]) == flt(want), f"{p.name} {leave_type}: card {got['value']} vs form {want}")
				_assert(got["route_options"] == {"employee": p.name}, got)
				seen += 1
		_assert(seen, "no employee with a current allocation to compare")

	check("Each person's card = the remaining balance their Leave Application form shows", _own_figure)

	def _no_employee():
		got = M.my_leave_balance(frappe.as_json({"leave_type": changed[0][1] if changed else "Casual"}))
		_assert(got["value"] is None, got)

	check("A login with no Employee (Administrator) gets N/A, not a company total", _no_employee)

	def _not_company_total():
		for _name, leave_type in changed:
			people = _people(leave_type, 50)
			if len(people) < 2:
				continue
			total = sum(M.balance_for(p.name, leave_type) for p in people)
			frappe.set_user(people[0].user_id)
			try:
				got = M.my_leave_balance(frappe.as_json({"leave_type": leave_type}))
			finally:
				frappe.set_user("Administrator")
			_assert(total == 0 or flt(got["value"]) < total, (got, total))
			return
		raise AssertionError("no leave type held by two or more people")

	check("The card no longer adds up other employees' leave", _not_company_total)

	def _employee_can_see():
		from frappe.desk.doctype.number_card.number_card import has_permission

		for _name, leave_type in changed:
			people = _people(leave_type, 1)
			if not people:
				continue
			card = frappe.get_doc("Number Card", _name)
			_assert(has_permission(card, "read", people[0].user_id), f"{people[0].user_id} cannot see {_name}")
			return

	check("An ordinary employee is allowed to see the card", _employee_can_see)
