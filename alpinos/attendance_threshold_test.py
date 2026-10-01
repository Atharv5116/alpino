"""HRMS: the hours shortage follows the Shift Type's own half-day / absent thresholds.

Run:  bench --site alpinos.test execute alpinos.attendance_threshold_test.run

Dharmishtha Paghadar collected 13 half-day shortages in September for working ~7.5 hours
against an 8.5 hour shift span -- while her shift's thresholds read 0. The report never
looked at them: it measured every day against the span (97% / 50% tiers), so a shift
configured to accept a shorter day still charged a shortage for nearly every day.

The thresholds now decide, and the span stays as the fallback for a shift that configures
neither. Fixtures are rolled back at the end.
"""

import frappe
from frappe.utils import flt

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
		calculate_attendance_stats,
	)

	tag = "THR" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")
	start, end = "2026-09-01", "2026-09-30"

	emp = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Person", status="Active",
		company=company, date_of_joining="2026-01-01")

	# Her shift: 10:00-18:30, i.e. an 8.5 hour span, with NO thresholds configured.
	span_only = _insert("Shift Type", name=f"{tag}-SPAN", start_time="10:00:00", end_time="18:30:00",
		working_hours_threshold_for_half_day=0, working_hours_threshold_for_absent=0)
	# The same shift with HR's policy filled in: half below 6, absent below 4.
	configured = _insert("Shift Type", name=f"{tag}-CFG", start_time="10:00:00", end_time="18:30:00",
		working_hours_threshold_for_half_day=6, working_hours_threshold_for_absent=4)

	# The same shift with Alpino's short Saturday configured: Present from 4.5 hours.
	saturday = _insert("Shift Type", name=f"{tag}-SAT", start_time="10:00:00", end_time="18:30:00",
		working_hours_threshold_for_half_day=8.25, working_hours_threshold_for_absent=4,
		saturday_working_hours_threshold=4.5)
	# And one with HR's three-way Saturday policy: half below 6, absent below 3.
	saturday3 = _insert("Shift Type", name=f"{tag}-SAT3", start_time="10:00:00", end_time="18:30:00",
		working_hours_threshold_for_half_day=8.25, working_hours_threshold_for_absent=4,
		saturday_working_hours_threshold_for_half_day=6,
		saturday_working_hours_threshold_for_absent=3)

	def _stats(shift, hours, day="15"):
		att = {f"2026-09-{day}": {
			"attendance_date": f"2026-09-{day}", "status": "Present", "shift": shift,
			"in_time": f"2026-09-{day} 10:05:00", "out_time": f"2026-09-{day} 17:00:00",
			"working_hours": hours,
		}}
		return calculate_attendance_stats(att, {}, {}, {}, start, end, emp)

	def _a_shift_with_no_thresholds_keeps_the_span_tiers():
		# 7.5 of 8.5 = 88% -> between 50% and 97% -> half a day, as before.
		s = _stats(span_only, 7.5)
		_assert(flt(s.working_hours_shortage) == 0.5,
			f"shortage {s.working_hours_shortage}, expected 0.5 from the span tiers")

	check("HRMS: a shift with no thresholds still measures against the span",
		_a_shift_with_no_thresholds_keeps_the_span_tiers)

	def _a_day_at_or_above_the_half_threshold_owes_nothing():
		# 7.5 hours, half-day threshold 6: the shift accepts this day in full.
		s = _stats(configured, 7.5)
		_assert(flt(s.working_hours_shortage) == 0.0,
			f"shortage {s.working_hours_shortage}: the day met the shift's own threshold")

	check("HRMS: a day meeting the shift's half-day threshold is charged nothing",
		_a_day_at_or_above_the_half_threshold_owes_nothing)

	def _below_the_half_threshold_is_half_a_day():
		s = _stats(configured, 5.0)      # under 6, over 4
		_assert(flt(s.working_hours_shortage) == 0.5,
			f"shortage {s.working_hours_shortage}, expected 0.5 below the half-day threshold")

	check("HRMS: below the half-day threshold is half a day's shortage",
		_below_the_half_threshold_is_half_a_day)

	def _below_the_absent_threshold_is_a_full_day():
		s = _stats(configured, 3.0)      # under 4
		_assert(flt(s.working_hours_shortage) == 1.0,
			f"shortage {s.working_hours_shortage}, expected a full day below the absent threshold")

	check("HRMS: below the absent threshold is a full day's shortage",
		_below_the_absent_threshold_is_a_full_day)

	def _dharmishthas_month_under_each_rule():
		"""Her 13 days of ~7.5 hours: 6.5 on the span, nothing once a threshold is set."""
		att = {}
		for d in (1, 3, 7, 9, 10, 11, 15, 17, 18, 21, 22, 24, 28):
			ds = f"2026-09-{d:02d}"
			att[ds] = {"attendance_date": ds, "status": "Present", "shift": span_only,
			           "in_time": f"{ds} 10:05:00", "out_time": f"{ds} 17:35:00", "working_hours": 7.5}
		span_stats = calculate_attendance_stats(att, {}, {}, {}, start, end, emp)
		_assert(flt(span_stats.working_hours_shortage) == 6.5,
			f"span rule gives {span_stats.working_hours_shortage}, expected her 6.5")

		for row in att.values():
			row["shift"] = configured
		cfg_stats = calculate_attendance_stats(att, {}, {}, {}, start, end, emp)
		_assert(flt(cfg_stats.working_hours_shortage) == 0.0,
			f"with a 6 hour half-day threshold the month still charges {cfg_stats.working_hours_shortage}")

	check("HRMS: her 13 days read 6.5 on the span and nothing once the threshold is set",
		_dharmishthas_month_under_each_rule)

	def _a_short_saturday_is_not_a_shortage():
		"""2026-09-05 is a Saturday. 5 hours against a 4.5 hour Saturday threshold owes nothing.

		The weekday thresholds (half below 8.25) would charge half a day for it, which is
		what started appearing against every Saturday of the month.
		"""
		s = _stats(saturday, 5.0, day="05")
		_assert(flt(s.working_hours_shortage) == 0.0,
			f"shortage {s.working_hours_shortage}: Saturday met its own 4.5 hour threshold")

	check("HRMS: a Saturday is measured against the Saturday threshold, not the weekday one",
		_a_short_saturday_is_not_a_shortage)

	def _a_saturday_below_its_threshold_is_a_full_day():
		"""Two-way Saturday: below the Present threshold the marking says Absent, so a full day."""
		s = _stats(saturday, 3.0, day="05")
		_assert(flt(s.working_hours_shortage) == 1.0,
			f"shortage {s.working_hours_shortage}, expected a full day below the Saturday threshold")

	check("HRMS: a Saturday under its own threshold is a full day's shortage",
		_a_saturday_below_its_threshold_is_a_full_day)

	def _a_three_way_saturday_follows_its_own_pair():
		half = _stats(saturday3, 5.0, day="05")      # under 6, over 3 -> half
		_assert(flt(half.working_hours_shortage) == 0.5,
			f"shortage {half.working_hours_shortage}, expected 0.5 below the Saturday half-day threshold")
		full = _stats(saturday3, 2.0, day="05")      # under 3 -> full
		_assert(flt(full.working_hours_shortage) == 1.0,
			f"shortage {full.working_hours_shortage}, expected a full day below the Saturday absent threshold")
		none = _stats(saturday3, 6.5, day="05")      # at or above 6 -> nothing
		_assert(flt(none.working_hours_shortage) == 0.0,
			f"shortage {none.working_hours_shortage}: the Saturday met its half-day threshold")

	check("HRMS: a Saturday with its own half-day and absent thresholds uses that pair",
		_a_three_way_saturday_follows_its_own_pair)

	def _a_weekday_still_uses_the_weekday_pair():
		"""2026-09-15 is a Tuesday: the Saturday fields must not reach it."""
		s = _stats(saturday, 5.0, day="15")
		_assert(flt(s.working_hours_shortage) == 0.5,
			f"shortage {s.working_hours_shortage}: a weekday is still measured at 8.25 / 4")

	check("HRMS: a weekday is untouched by the Saturday thresholds",
		_a_weekday_still_uses_the_weekday_pair)
