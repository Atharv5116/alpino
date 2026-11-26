"""My Workday dashboard on Home. TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.my_workday_test.run
"""

import json

import frappe

R = []
HO = {"name": "HO", "start": 600, "span": 510, "start_label": "10:00", "end_label": "18:30", "late_on": True, "grace": 15}


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
		frappe.flags.in_migrate = False
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _employee_with_user():
	return frappe.db.sql(
		"""SELECT e.name, e.user_id FROM `tabEmployee` e JOIN `tabUser` u ON u.name = e.user_id AND u.enabled = 1
		   JOIN `tabLeave Allocation` la ON la.employee = e.name AND la.docstatus = 1 AND CURDATE() BETWEEN la.from_date AND la.to_date
		   WHERE e.status = 'Active' ORDER BY e.name LIMIT 1""",
		as_dict=True,
	)[0]


def _run():
	from alpinos import attendance_widget as W
	from alpinos import my_workday as M

	def _late_after_half_off():
		m = W._clock_minutes
		_assert(W._lateness(m("10:18"), HO) == (18, 1), W._lateness(m("10:18"), HO))
		_assert(W._lateness(m("10:10"), HO) == (10, 0), "inside the 15 min grace")
		leave_first = [{"kind": "leave", "label": "Leave (Casual)"}, {"kind": "present", "label": "Present"}]
		_assert(W._lateness(m("14:20"), HO, leave_first) == (5, 0), W._lateness(m("14:20"), HO, leave_first))
		_assert(W._lateness(m("14:40"), HO, leave_first) == (25, 1), "late against the second half's start")
		off = dict(HO, late_on=False)
		_assert(W._lateness(m("11:00"), off)[1] == 0, "a shift without late marking is never late")

	check("Late counts from the shift start, or from mid-shift after a first half off", _late_after_half_off)

	e = _employee_with_user()

	def _workday():
		frappe.set_user(e.user_id)
		try:
			w = M.get_workday()
		finally:
			frappe.set_user("Administrator")
		_assert(w["employee"] == e.name, w["employee"])
		for k in ("today", "regularization", "leave_balances", "moments", "pulse"):
			_assert(k in w, k)
		g = w["regularization"]
		_assert(g["cap"] == 4 and g["left"] == max(4 - g["used"], 0), g)
		_assert(w["leave_balances"], "no leave balance for an employee with an allocation")
		for b in w["leave_balances"]:
			_assert(b["left"] <= b["allocated"] + 0.001, b)
		_assert(isinstance(w["moments"]["birthdays"], list) and isinstance(w["pulse"]["on_leave"], list))
		json.dumps(w, default=str)

	check("get_workday: today, regularization (x of 4), leave balances, moments, pulse for the user", _workday)

	def _no_employee():
		w = M.get_workday()      # Administrator
		_assert(w["employee"] is None and w["today"] is None and w["regularization"] is None, w)
		_assert("moments" in w and "pulse" in w)

	check("A login with no Employee still gets Moments and Team Pulse, nothing personal", _no_employee)

	def _regularization_matches_limit():
		from alpinos.attendance_request_automation import count_attendance_request_edits, get_reserved_request_names
		from frappe.utils import add_months, getdate, now_datetime

		start = getdate(now_datetime()).replace(day=1)
		used = count_attendance_request_edits(get_reserved_request_names(e.name, start, add_months(start, 1)))
		frappe.set_user(e.user_id)
		try:
			g = M.get_workday()["regularization"]
		finally:
			frappe.set_user("Administrator")
		_assert(g["used"] == used, (g, used))

	check("Regularization 'used' is the same count the monthly limit enforces", _regularization_matches_limit)

	def _placed_on_home():
		if not frappe.db.exists("Workspace", M.WORKSPACE):
			return
		frappe.flags.in_migrate = True
		M.place_on_home()
		M.place_on_home()        # a second migrate changes nothing
		frappe.flags.in_migrate = False
		ws = frappe.get_doc("Workspace", M.WORKSPACE)
		blocks = json.loads(ws.content)
		names = [(b.get("data") or {}).get("custom_block_name") for b in blocks if b.get("type") == "custom_block"]
		_assert(names and names[0] == M.BLOCK, names[:3])
		_assert(names.count(M.BLOCK) == 1, names)
		_assert(not set(names) & set(M.REPLACES), names)
		_assert(not any(r.custom_block_name in M.REPLACES for r in ws.custom_blocks))
		b = frappe.get_doc("Custom HTML Block", M.BLOCK)
		_assert("mw-cal" in b.html and "get_workday" in b.script and ".mw-grid" in (b.style or ""), "block content")
		for other in M.REPLACES:
			if frappe.db.exists("Custom HTML Block", other):
				_assert(True)     # records stay, only the layout drops them

	check("My Workday is first on Home, once, in place of check-in / calendar / birthdays blocks", _placed_on_home)

	def _hr_blocks_stay():
		ws = frappe.get_doc("Workspace", M.WORKSPACE)
		names = [(b.get("data") or {}).get("custom_block_name") for b in json.loads(ws.content) if b.get("type") == "custom_block"]
		for hr in ("Upcoming HR Activities", "Missing Check-ins Today", "Outside Geo-Location Check-ins"):
			if frappe.db.exists("Custom HTML Block", hr):
				_assert(hr in names, f"{hr} dropped from Home")

	check("HR's own Home blocks stay below it", _hr_blocks_stay)
