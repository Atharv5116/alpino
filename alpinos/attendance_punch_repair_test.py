"""Changes(HP) HRMS #13 repair: retyping a punch, and the day that follows from it.

Run:  bench --site alpinos.test execute alpinos.attendance_punch_repair_test.run

The fixture is Harsh Patel's 10-09-2026 as the audit found it: an edited check-in, a 13:58
OUT, and an 18:33 exit the device typed IN, with the Attendance reading 3.75 hours.
Everything is rolled back at the end.
"""

import frappe
from frappe.utils import cint, flt

from alpinos import attendance_punch_repair as R

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
	tag = "APR" + frappe.generate_hash(length=5).upper()
	day = "2026-09-10"
	emp = _insert(
		"Employee", name=f"{tag}-EMP", employee_name=f"{tag} Punch Person", status="Active",
		company=frappe.defaults.get_global_default("company"), date_of_joining="2026-01-01",
	)

	# The day exactly as the audit found it on prod.
	edited_in = _insert("Employee Checkin", name=f"{tag}-CK1", employee=emp, log_type="IN",
		time=f"{day} 10:14:08", from_attendance_request=1)
	_insert("Employee Checkin", name=f"{tag}-CK2", employee=emp, log_type="OUT",
		time=f"{day} 13:58:50", device_id="TDBD260200038")
	mistyped = _insert("Employee Checkin", name=f"{tag}-CK3", employee=emp, log_type="IN",
		time=f"{day} 18:33:39", device_id="TDBD260200038")
	att = _insert("Attendance", name=f"{tag}-ATT", employee=emp, attendance_date=day, docstatus=1,
		status="Present", in_time=f"{day} 10:14:08", out_time=f"{day} 13:58:50", working_hours=3.75)

	def _the_dry_run_shows_the_day_and_writes_nothing():
		out = R.set_log_type(checkin=mistyped, log_type="OUT", apply=0)
		_assert(out["mode"] == "DRY-RUN", out["mode"])
		_assert(out["day_before"]["hours"] == 3.75, f"before: {out['day_before']}")
		_assert(out["day_after"]["out"].startswith(f"{day} 18:33"), f"after: {out['day_after']}")
		_assert(out["day_after"]["hours"] == 8.33, f"hours after: {out['day_after']['hours']}")
		# nothing written
		_assert(frappe.db.get_value("Employee Checkin", mistyped, "log_type") == "IN",
			"the dry run retyped the punch")
		_assert(flt(frappe.db.get_value("Attendance", att, "working_hours"), 2) == 3.75,
			"the dry run touched the attendance")

	check("#13 the dry run shows 3.75 hours becoming 8.33, and writes nothing",
		_the_dry_run_shows_the_day_and_writes_nothing)

	def _applying_retypes_the_punch_and_re_derives_the_day():
		out = R.set_log_type(checkin=mistyped, log_type="OUT", apply=1)
		_assert(frappe.db.get_value("Employee Checkin", mistyped, "log_type") == "OUT",
			"the punch was not retyped")
		row = frappe.db.get_value("Attendance", att, ["in_time", "out_time", "working_hours"], as_dict=True)
		_assert(str(row.out_time).startswith(f"{day} 18:33"), f"out_time is {row.out_time}")
		_assert(str(row.in_time).startswith(f"{day} 10:14"), f"in_time moved: {row.in_time}")
		_assert(flt(row.working_hours, 2) == 8.33, f"hours are {row.working_hours}")
		_assert(out["attendance_after"] != "unchanged", "the attendance was reported unchanged")

	check("#13 applying retypes the punch and re-derives in / out / hours",
		_applying_retypes_the_punch_and_re_derives_the_day)

	def _the_correction_is_left_on_the_record():
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Employee Checkin", "reference_name": mistyped},
			fields=["content"],
		)
		_assert(any("IN -" in (c.content or "") and "OUT" in (c.content or "") for c in comments),
			f"no audit comment on the punch: {comments}")
		att_comments = frappe.get_all(
			"Comment", filters={"reference_doctype": "Attendance", "reference_name": att}, fields=["content"]
		)
		_assert(att_comments, "no audit comment on the attendance")

	check("#13 both records carry a comment saying what was corrected",
		_the_correction_is_left_on_the_record)

	def _an_edited_check_in_is_left_alone():
		_assert(frappe.db.get_value("Employee Checkin", edited_in, "log_type") == "IN",
			"the approved check-in edit was disturbed")
		_assert(str(frappe.db.get_value("Employee Checkin", edited_in, "time")).startswith(f"{day} 10:14"),
			"the approved check-in time was disturbed")

	check("#13 the approved check-in edit is left exactly as it was",
		_an_edited_check_in_is_left_alone)

	def _a_punch_already_that_type_is_refused():
		out = R.set_log_type(checkin=mistyped, log_type="OUT", apply=0)
		_assert("error" in out, f"retyping to the same value was accepted: {out}")

	check("#13 retyping a punch to what it already is is refused",
		_a_punch_already_that_type_is_refused)

	def _a_request_owned_day_can_be_re_marked():
		"""Dharmishtha's 2 Sep: an approved request left it Absent with 7.68 hours."""
		emp2 = _insert("Employee", name=f"{tag}-EMP2", employee_name=f"{tag} Request Day",
			status="Active", company=frappe.defaults.get_global_default("company"),
			date_of_joining="2026-01-01")
		# HO_G as it stands: a short span, absent below four hours.
		shift = _insert("Shift Type", name=f"{tag}-HOG", start_time="11:00:00", end_time="15:00:00",
			working_hours_threshold_for_absent=4, working_hours_threshold_for_half_day=0)
		d = "2026-09-02"
		_insert("Employee Checkin", name=f"{tag}-R-IN", employee=emp2, log_type="IN",
			time=f"{d} 10:27:44", shift=shift)
		_insert("Employee Checkin", name=f"{tag}-R-OUT", employee=emp2, log_type="OUT",
			time=f"{d} 18:08:41", shift=shift, skip_auto_attendance=1, from_attendance_request=1)
		req = _insert("Attendance Request", name=f"{tag}-R-ARQ", employee=emp2, from_date=d,
			to_date=d, docstatus=1, workflow_state="Approved", reason="Office", shift=shift)
		att2 = _insert("Attendance", name=f"{tag}-R-ATT", employee=emp2, attendance_date=d,
			docstatus=1, status="Absent", shift=shift, attendance_request=req,
			in_time=f"{d} 10:27:44", out_time=f"{d} 18:08:41", working_hours=7.68)

		dry = R.remark_day(employee=emp2, date=d, apply=0)
		_assert(dry["before"]["status"] == "Absent", f"before: {dry['before']}")
		_assert(dry["after"]["status"] != "Absent",
			f"the re-mark would leave it {dry['after']['status']}")
		_assert(dry["owned_by_request"] == req, "the report does not say the request owns the day")
		_assert(frappe.db.get_value("Attendance", att2, "status") == "Absent",
			"the dry run wrote the status")

		R.remark_day(employee=emp2, date=d, apply=1)
		_assert(frappe.db.get_value("Attendance", att2, "status") != "Absent",
			"the day is still Absent after applying")
		_assert(not cint(frappe.db.get_value("Employee Checkin", f"{tag}-R-OUT", "skip_auto_attendance")),
			"the stray skip flag was left on the punch")
		_assert(str(frappe.db.get_value("Attendance", att2, "in_time")).endswith("10:27:44"),
			"the in-time was disturbed")

	check("#13 a day an Attendance Request owns can still be re-marked from its punches",
		_a_request_owned_day_can_be_re_marked)
