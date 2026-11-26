"""My Attendance Calendar: half days split by half, late from each day's shift, outside geo
punches. TEST sites only; reads real records, writes nothing (rolled back anyway).

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.calendar_halves_test.run
"""

import frappe
from frappe.utils import getdate

R = []

# HO on this site: 10:00 to 18:30, late-entry marking on, 15 min grace
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
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _kinds(halves):
	return [(h["kind"], h["label"]) for h in halves] if halves else None


def _day(W, employee, day):
	"""The calendar row for `employee` on `day`, as that employee would get it."""
	real = W._get_employee_for_user
	W._get_employee_for_user = lambda user: employee
	try:
		d = getdate(day)
		return (W.get_monthly_attendance(d.year, d.month).get("days") or {}).get(str(d)) or {}
	finally:
		W._get_employee_for_user = real


def _run():
	from alpinos import attendance_widget as W

	H = W._day_halves
	m = W._clock_minutes

	# ---- logic, made-up days ----
	def _named_halves():
		lv1 = {"leave_type": "Casual", "half": True, "period": "First Half"}
		lv2 = {"leave_type": "Casual", "half": True, "period": "Second Half"}
		att = {"status": "Half Day", "leave_type": "Casual", "half_day_status": "Present"}
		_assert(_kinds(H(att, lv1, None, m("14:20"), m("18:40"), HO)) == [("leave", "Leave (Casual)"), ("present", "Present")])
		_assert(_kinds(H(att, lv2, None, m("10:00"), m("14:20"), HO)) == [("present", "Present"), ("leave", "Leave (Casual)")])
		wf = {"half": True, "period": "First Half"}
		_assert(_kinds(H({"status": "Present"}, None, wf, m("14:00"), m("18:30"), HO)) == [("wfh", "WFH"), ("present", "Present")])

	check("Leave / WFH half sits on the half its application names; the other half shows its own status", _named_halves)

	def _unnamed_halves():
		att = {"status": "Half Day", "leave_type": "Casual", "half_day_status": "Present"}
		lv = {"leave_type": "Casual", "half": True, "period": None}
		_assert(_kinds(H(att, lv, None, m("13:59"), m("18:35"), HO))[0][0] == "leave", "came in 13:59: leave is the first half")
		_assert(_kinds(H(att, lv, None, m("10:02"), m("14:20"), HO))[1][0] == "leave", "left 14:20: leave is the second half")
		_assert(_kinds(H(att, lv, None, None, None, HO))[0][0] == "leave", "no punches: first half by default")

	check("An application that names no half is placed by the half of the shift the punches cover", _unnamed_halves)

	def _short_hours():
		att = {"status": "Half Day", "leave_type": None, "half_day_status": "Absent"}
		_assert(_kinds(H(att, None, None, m("14:11"), m("18:36"), HO)) == [("absent", "Absent"), ("present", "Present")])
		_assert(_kinds(H(att, None, None, m("09:18"), m("16:12"), HO)) == [("present", "Present"), ("absent", "Absent")])
		_assert(_kinds(H(att, None, None, m("10:15"), m("14:20"), HO)) == [("present", "Present"), ("absent", "Absent")])

	check("Half Day for short hours: the half not worked is Absent, the worked half Present", _short_hours)

	def _mixed_and_absent_other():
		lv = {"leave_type": "Casual", "half": True, "period": None}
		wf = {"half": True, "period": "Second Half"}
		_assert(_kinds(H({"status": "Present"}, lv, wf, None, None, HO)) == [("leave", "Leave (Casual)"), ("wfh", "WFH")])
		att = {"status": "Half Day", "leave_type": "Casual", "half_day_status": "Absent"}
		lv2 = {"leave_type": "Casual", "half": True, "period": "First Half"}
		_assert(_kinds(H(att, lv2, None, None, None, HO)) == [("leave", "Leave (Casual)"), ("absent", "Absent")])
		_assert(_kinds(H(None, lv2, None, None, None, HO)) == [("leave", "Leave (Casual)"), ("open", "Working")], "a day ahead")
		_assert(H({"status": "Present"}, None, None, m("10:00"), m("18:30"), HO) is None, "a full day is not split")

	check("Leave + WFH halves, leave + Absent, a planned half leave, and a full day left whole", _mixed_and_absent_other)

	def _late_by_shift():
		_assert(W._from_shift_start(m("10:18"), HO) == 18)
		night = {"name": "N", "start": 20 * 60, "span": 600, "late_on": True, "grace": 15}
		_assert(W._from_shift_start(m("00:30"), night) == 270, W._from_shift_start(m("00:30"), night))
		_assert(W._from_shift_start(m("19:50"), night) == -10)
		row = W._shift_row("HO", {})
		_assert(row and row["start_label"] == "10:00" and row["late_on"] and row["grace"] == 15, row)

	check("Minutes after shift start are read on the shift's own clock (night shifts too)", _late_by_shift)

	# ---- real records on this site ----
	def _real_named():
		r = frappe.db.sql(
			"""SELECT a.employee, a.attendance_date, la.custom_half_day_period p FROM `tabAttendance` a
			   JOIN `tabLeave Application` la ON la.name = a.leave_application
			   WHERE a.status = 'Half Day' AND a.docstatus = 1 AND la.custom_half_day_period IN ('First Half', 'Second Half')
			   ORDER BY a.attendance_date DESC LIMIT 3""",
			as_dict=True,
		)
		_assert(r, "no half-day leave with a named half on this site")
		for x in r:
			day = _day(W, x.employee, x.attendance_date)
			hv = day.get("halves")
			_assert(hv, f"{x.employee} {x.attendance_date}: not split")
			i = 0 if x.p == "First Half" else 1
			_assert(hv[i]["kind"] == "leave" and hv[1 - i]["kind"] in ("present", "absent", "wfh"), (x, hv))

	check("Real half-day leaves show on the named half with the other half's status", _real_named)

	def _real_short():
		r = frappe.db.sql(
			"""SELECT employee, attendance_date, in_time, out_time FROM `tabAttendance`
			   WHERE status = 'Half Day' AND docstatus = 1 AND leave_type IS NULL AND half_day_status = 'Absent'
			     AND shift = 'HO' AND in_time IS NOT NULL AND out_time IS NOT NULL
			   ORDER BY attendance_date DESC LIMIT 3""",
			as_dict=True,
		)
		_assert(r, "no short-hours half day on this site")
		for x in r:
			hv = _day(W, x.employee, x.attendance_date).get("halves")
			_assert(hv and sorted(h["kind"] for h in hv) == ["absent", "present"], (x, hv))

	check("Real short-hours half days show one Present and one Absent half", _real_short)

	def _real_late():
		r = frappe.db.sql(
			"""SELECT a.employee, a.attendance_date, TIME_TO_SEC(TIMEDIFF(TIME(a.in_time), s.start_time)) DIV 60 mins,
			          s.late_entry_grace_period grace, s.enable_late_entry_marking late_on
			   FROM `tabAttendance` a JOIN `tabShift Type` s ON s.name = a.shift
			   WHERE a.docstatus = 1 AND a.status = 'Present' AND a.in_time IS NOT NULL AND a.attendance_date > '2026-09-30'
			     AND TIMEDIFF(TIME(a.in_time), s.start_time) BETWEEN '00:01:00' AND '02:00:00'
			   ORDER BY a.attendance_date DESC LIMIT 40""",
			as_dict=True,
		)
		_assert(r, "no Present day with a check-in after its shift start")
		late = ok = 0
		for x in r:
			day = _day(W, x.employee, x.attendance_date)
			if day.get("shift") is None or day.get("late_minutes") is None:
				continue
			want = 1 if x.late_on and day["late_minutes"] > (x.grace or 0) else 0
			_assert(day["late_coming"] == want, (x, day["late_minutes"], day["late_coming"]))
			late += want
			ok += 1
		_assert(ok, "no day resolved a shift")
		_assert(late, "none of the sample was late, cannot tell late from on time")

	check("Real check-ins: Late only past that shift's grace, and only where the shift marks late", _real_late)

	def _real_geo():
		r = frappe.db.sql(
			"""SELECT employee, DATE(time) d FROM `tabEmployee Checkin` WHERE custom_outside_location = 1
			   ORDER BY time DESC LIMIT 3""",
			as_dict=True,
		)
		_assert(r, "no outside geo-fence punch on this site")
		for x in r:
			day = _day(W, x.employee, x.d)
			wfh = day.get("wfh")
			_assert(day.get("out_of_geo") == (0 if wfh else 1), (x, day.get("out_of_geo"), wfh))

	check("Real punches outside the geo-fence mark the day (not on an approved WFH day)", _real_geo)

	def _real_wfh_range():
		r = frappe.db.sql(
			"""SELECT employee, date, to_date FROM `tabWork From Home Request`
			   WHERE status = 'Approved' AND to_date > date AND MONTH(to_date) = MONTH(date) LIMIT 1""",
			as_dict=True,
		)
		if not r:
			return
		x = r[0]
		day = _day(W, x.employee, x.to_date)
		_assert(day.get("wfh") == 1, f"last day of {x.date} to {x.to_date} not WFH")

	check("A WFH request over several days marks every day, not just the first", _real_wfh_range)
