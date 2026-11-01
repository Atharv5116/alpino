"""Company-wise access for the HR / attendance pages and APIs. Run on a TEST site:

	bench --site <test site> execute alpinos.company_scope.hr_scope_test.run

Fixtures (all removed again): employees CS-HR-EMP-* copied from a real employee of the
default company (A) and of another company with employees (B), with a leave, a WFH request,
an outside-location check-in and an Attendance Request each; a reporting manager in A with a
team member in B; an Attendance Batch copy in B; users

	cs.hr.both@example.com  HR Manager in A and in B
	cs.hr.one@example.com   HR Manager in A, member of B without roles
	cs.hr.rm@example.com    member of A, global Reporting Manager, manages CS-HR-EMP-TEAM (B)
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

from alpinos.company_scope.testing import ALL, as_user, cleanup_user, copy_header, delete_copies, ensure_enabled, make_user, set_active

R = []

U_HR, U_ONE, U_RM = "cs.hr.both@example.com", "cs.hr.one@example.com", "cs.hr.rm@example.com"
EMP_A, EMP_B, EMP_RM, EMP_TEAM = "CS-HR-EMP-A", "CS-HR-EMP-B", "CS-HR-EMP-RM", "CS-HR-EMP-TEAM"
LA = ("CS-HR-LA-A", "CS-HR-LA-B")
WFH = ("CS-HR-WFH-A", "CS-HR-WFH-B")
CKIN = ("CS-HR-CKIN-A", "CS-HR-CKIN-B")
AR = ("CS-HR-AR-A", "CS-HR-AR-B", "CS-HR-AR-TEAM")
BATCH_B = "CS-HR-BATCH-B"
FAR_MONTH = "2099-01-01"


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


def _raises(fn, exc=frappe.PermissionError, contains=None):
	try:
		fn()
	except exc as e:
		if contains and contains not in str(e):
			raise AssertionError(f"raised, but '{contains}' not in: {e}")
		return
	raise AssertionError("did not raise")


def _companies():
	"""(default company, the other company with the most active employees)."""
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	rows = frappe.db.sql(
		"""select company, count(*) from `tabEmployee` where status = 'Active' and company != %s
		group by company order by count(*) desc""",
		default,
	)
	return default, rows[0][0]


def _batch_names():
	return frappe.get_all("Monthly Attendance Batch", {"payroll_month": FAR_MONTH}, pluck="name")


def _cleanup():
	frappe.set_user("Administrator")
	delete_copies("Employee", [EMP_A, EMP_B, EMP_RM, EMP_TEAM])
	delete_copies("Leave Application", LA)
	delete_copies("Work From Home Request", WFH)
	delete_copies("Employee Checkin", CKIN)
	delete_copies("Attendance Request", AR)
	delete_copies("Monthly Attendance Batch", [BATCH_B] + _batch_names())
	for user in (U_HR, U_ONE, U_RM):
		cleanup_user(user)
	frappe.db.commit()


def _fixtures(A, B):
	today = getdate(nowdate())
	month_day = today.replace(day=15)
	tpl_a = frappe.db.sql(
		"""select e.name from `tabEmployee` e where e.company = %s and e.status = 'Active'
		and exists (select 1 from `tabAttendance` a where a.employee = e.name) order by e.name limit 1""",
		A,
	)[0][0]
	tpl_b = frappe.db.get_value("Employee", {"company": B, "status": "Active"}, "name", order_by="name asc")

	def employee(name, template, company, label, **extra):
		values = dict(
			employee=name, employee_name=label, first_name=label, middle_name=None, last_name=None,
			user_id=None, attendance_device_id=None, status="Active", relieving_date=None,
			custom_suspension_date=None, reports_to=None,
			date_of_birth=month_day.replace(year=1990), date_of_joining=month_day.replace(year=2020),
			probation_end_date=today,
		)
		values.update(extra)
		copy_header("Employee", template, name, company, **values)

	employee(EMP_A, tpl_a, A, "CS HR Emp A")
	employee(EMP_B, tpl_b, B, "CS HR Emp B")
	employee(EMP_RM, tpl_a, A, "CS HR Emp RM", user_id=U_RM)
	employee(EMP_TEAM, tpl_b, B, "CS HR Emp Team")
	frappe.db.set_value("Employee", EMP_TEAM, "reports_to", EMP_RM, update_modified=False)

	now = now_datetime()
	pairs = ((EMP_A, A, "CS HR Emp A"), (EMP_B, B, "CS HR Emp B"))
	la_tpl = frappe.db.get_value("Leave Application", {}, "name", order_by="creation desc")
	wfh_tpl = frappe.db.get_value("Work From Home Request", {}, "name", order_by="creation desc")
	ck_tpl = frappe.db.get_value("Employee Checkin", {}, "name", order_by="creation desc")
	ar_tpl = frappe.db.get_value("Attendance Request", {}, "name", order_by="creation desc")
	for i, (emp, company, label) in enumerate(pairs):
		common = {"employee": emp, "employee_name": label}
		copy_header("Leave Application", la_tpl, LA[i], company, docstatus=1, status="Approved",
			workflow_state="Approved", from_date=today, to_date=today, half_day=0, **common)
		copy_header("Work From Home Request", wfh_tpl, WFH[i], company, docstatus=0, status="Approved",
			date=today, to_date=today, **common)
		copy_header("Employee Checkin", ck_tpl, CKIN[i], company, time=now, log_type="IN",
			custom_outside_location=1, attendance=None, device_id=None, **common)
		copy_header("Attendance Request", ar_tpl, AR[i], company, docstatus=0,
			workflow_state="Pending HR Approval", from_date=today, to_date=today,
			creation=now, modified=now, reporting_person=None, **common)
	copy_header("Attendance Request", ar_tpl, AR[2], B, docstatus=0, employee=EMP_TEAM,
		employee_name="CS HR Emp Team", workflow_state="Pending RM Approval", from_date=today,
		to_date=today, creation=now, modified=now, reporting_person=U_RM)
	batch_tpl = frappe.db.get_value("Monthly Attendance Batch", {"company": A}, "name")
	if batch_tpl:
		copy_header("Monthly Attendance Batch", batch_tpl, BATCH_B, B, docstatus=0, workflow_state="Draft")
	frappe.db.commit()
	return batch_tpl


def run():
	R.clear()
	frappe.set_user("Administrator")
	ensure_enabled()
	A, B = _companies()
	_cleanup()
	try:
		_run(A, B)
	finally:
		_cleanup()
	return _report()


def _run(A, B):
	batch_a = _fixtures(A, B)
	make_user(U_HR, {A: ["HR Manager"], B: ["HR Manager"]})
	make_user(U_ONE, {A: ["HR Manager"], B: []})
	make_user(U_RM, {A: []}, global_roles=("Reporting Manager",))
	set_active(U_ONE, ALL)

	def in_company(user, company, fn):
		set_active(user, company)
		return as_user(user, fn)

	# 1. Missing check-ins widget: HR by company, reporting manager by team.
	from alpinos import attendance_alerts as alerts

	def emp(name, company, label, reports_to=None):
		return frappe._dict(name=name, employee_name=label, company=company, department="", reports_to=reports_to)

	flagged = [emp(EMP_A, A, "CS HR Emp A"), emp(EMP_B, B, "CS HR Emp B"), emp(EMP_TEAM, B, "CS HR Emp Team", EMP_RM)]
	original_flagged, original_now = alerts.get_flagged_employees, alerts.now_datetime
	alerts.get_flagged_employees = lambda today=None: (getdate(nowdate()), list(flagged))
	alerts.now_datetime = lambda: frappe.utils.get_datetime(f"{nowdate()} 12:00:00")
	try:
		def missing(user, company=None):
			fn = lambda: {r["employee"] for r in alerts.get_missing_checkins_today()["employees"]}
			return in_company(user, company, fn) if company else as_user(user, fn)

		check("missing check-ins: HR in A sees only A", lambda: _assert(missing(U_HR, A) == {EMP_A}, missing(U_HR, A)))
		check("missing check-ins: switching to B shows B", lambda: _assert(
			missing(U_HR, B) == {EMP_B, EMP_TEAM}, missing(U_HR, B)))
		check("missing check-ins: All shows both", lambda: _assert(
			missing(U_HR, ALL) == {EMP_A, EMP_B, EMP_TEAM}, missing(U_HR, ALL)))
		check("missing check-ins: HR of A only, in All, sees no B", lambda: _assert(
			missing(U_ONE) == {EMP_A}, missing(U_ONE)))
		check("missing check-ins: manager sees a team member of another company", lambda: _assert(
			missing(U_RM) == {EMP_TEAM}, missing(U_RM)))
		check("missing check-ins: Administrator unchanged", lambda: _assert(
			missing("Administrator") == {EMP_A, EMP_B, EMP_TEAM}))

		sent = []
		original_send = alerts._send
		alerts._send = lambda recipients, subject, message: sent.append((recipients, message))
		try:
			alerts._send_hr_digest(flagged[:2], getdate(nowdate()))
		finally:
			alerts._send = original_send

		def digest_for(user):
			mails = [m for r, m in sent if user in r]
			_assert(len(mails) == 1, f"{user} got {len(mails)} digests")
			return mails[0]

		check("HR digest: HR of A and B gets one digest with both", lambda: _assert(
			EMP_A in digest_for(U_HR) and EMP_B in digest_for(U_HR)))
		check("HR digest: HR of A only gets A's employees only", lambda: _assert(
			EMP_A in digest_for(U_ONE) and EMP_B not in digest_for(U_ONE)))
	finally:
		alerts.get_flagged_employees, alerts.now_datetime = original_flagged, original_now

	# 2. Outside-geo check-ins.
	from alpinos.outside_geo_checkins import get_outside_geo_checkins

	def geo():
		return {i["employee"] for i in get_outside_geo_checkins()["items"]} & {EMP_A, EMP_B}

	check("outside geo: A only", lambda: _assert(in_company(U_HR, A, geo) == {EMP_A}, in_company(U_HR, A, geo)))
	check("outside geo: switch to B", lambda: _assert(in_company(U_HR, B, geo) == {EMP_B}))
	check("outside geo: All shows both", lambda: _assert(in_company(U_HR, ALL, geo) == {EMP_A, EMP_B}))
	check("outside geo: HR of A only sees no B", lambda: _assert(as_user(U_ONE, geo) == {EMP_A}))
	check("outside geo: Administrator unchanged", lambda: _assert(geo() == {EMP_A, EMP_B}))

	# 3. People events.
	from alpinos import people_events as pe

	def birthdays():
		return {r["employee_name"] for r in pe.get_upcoming_birthdays_and_anniversaries()["birthdays"]} & {
			"CS HR Emp A", "CS HR Emp B"}

	check("birthdays: A only", lambda: _assert(in_company(U_HR, A, birthdays) == {"CS HR Emp A"}))
	check("birthdays: switch to B", lambda: _assert(in_company(U_HR, B, birthdays) == {"CS HR Emp B"}))
	check("birthdays: All shows both", lambda: _assert(in_company(U_HR, ALL, birthdays) == {"CS HR Emp A", "CS HR Emp B"}))
	check("birthdays: Administrator unchanged", lambda: _assert(birthdays() == {"CS HR Emp A", "CS HR Emp B"}))

	def probation():
		return {r["employee_name"] for r in pe.get_upcoming_employee_lifecycle()["probation"]} & {
			"CS HR Emp A", "CS HR Emp B"}

	check("lifecycle: A only", lambda: _assert(in_company(U_HR, A, probation) == {"CS HR Emp A"}))
	check("lifecycle: switch to B", lambda: _assert(in_company(U_HR, B, probation) == {"CS HR Emp B"}))
	check("lifecycle: HR of A only, in All, sees no B", lambda: _assert(as_user(U_ONE, probation) == {"CS HR Emp A"}))

	def away():
		out = pe.get_on_leave_and_wfh_today()
		return ({r["employee"] for r in out["on_leave"]} & {EMP_A, EMP_B},
			{r["employee"] for r in out["on_wfh"]} & {EMP_A, EMP_B})

	check("on leave / WFH today: A only", lambda: _assert(in_company(U_HR, A, away) == ({EMP_A}, {EMP_A}),
		in_company(U_HR, A, away)))
	check("on leave / WFH today: switch to B", lambda: _assert(in_company(U_HR, B, away) == ({EMP_B}, {EMP_B})))
	check("on leave / WFH today: All shows both", lambda: _assert(
		in_company(U_HR, ALL, away) == ({EMP_A, EMP_B}, {EMP_A, EMP_B})))
	check("on leave / WFH today: Administrator unchanged", lambda: _assert(away() == ({EMP_A, EMP_B}, {EMP_A, EMP_B})))

	# 4. Approvals dashboard: HR steps by company, RM step by team.
	from alpinos.approval_dashboard import get_pending_approvals

	def pending():
		return {i["name"] for i in get_pending_approvals()["items"]} & set(AR)

	check("approvals: HR in A sees A's HR step", lambda: _assert(in_company(U_HR, A, pending) == {AR[0]},
		in_company(U_HR, A, pending)))
	check("approvals: switch to B", lambda: _assert(in_company(U_HR, B, pending) == {AR[1]}))
	check("approvals: All shows both", lambda: _assert(in_company(U_HR, ALL, pending) == {AR[0], AR[1]}))
	check("approvals: HR of A only sees no B", lambda: _assert(as_user(U_ONE, pending) == {AR[0]}))
	check("approvals: manager approves a team member of another company", lambda: _assert(
		as_user(U_RM, pending) == {AR[2]}, as_user(U_RM, pending)))
	check("approvals: Administrator unchanged", lambda: _assert(pending() == {AR[0], AR[1]}))

	# 5. Attendance batches.
	from alpinos import attendance_batch_api as batches

	def batch_list():
		out = batches.get_batches(page_length=500)
		return {b.name for b in out["batches"]}, out["counts"]["All"]

	if batch_a:
		check("batches: A only", lambda: _assert(
			batch_a in in_company(U_HR, A, batch_list)[0] and BATCH_B not in in_company(U_HR, A, batch_list)[0]))
		check("batches: switch to B", lambda: _assert(in_company(U_HR, B, batch_list) == ({BATCH_B}, 1),
			in_company(U_HR, B, batch_list)))
		check("batches: All shows both", lambda: _assert({batch_a, BATCH_B} <= in_company(U_HR, ALL, batch_list)[0]))
		check("batches: HR of A only sees no B", lambda: _assert(BATCH_B not in as_user(U_ONE, batch_list)[0]))
		check("batches: Administrator unchanged", lambda: _assert({batch_a, BATCH_B} <= batch_list()[0]))
		check("batch view: B's batch opened while in A asks to switch", lambda: in_company(
			U_HR, A, lambda: _raises(lambda: batches.get_batch(BATCH_B), contains="switch")))
		check("batch view: opens in B", lambda: _assert(
			in_company(U_HR, B, lambda: batches.get_batch(BATCH_B))["doc"]["name"] == BATCH_B))

	b_abbr = frappe.get_cached_value("Company", B, "abbr")
	check("new batch in B carries B's abbreviation", lambda: _assert(
		in_company(U_HR, B, lambda: batches.create_batch("HO/Admin", FAR_MONTH)) == f"ATT-BATCH-{b_abbr}-2099-01-HO"))
	check("second batch for the month in B is refused", lambda: in_company(
		U_HR, B, lambda: _raises(lambda: batches.create_batch("HO/Admin", FAR_MONTH), frappe.ValidationError,
			contains="already exists")))
	check("the default company's batch keeps its name", lambda: _assert(
		in_company(U_HR, A, lambda: batches.create_batch("HO/Admin", FAR_MONTH)) == "ATT-BATCH-2099-01-HO"))
	check("no batch in a company without HR there", lambda: in_company(
		U_ONE, B, lambda: _raises(lambda: batches.create_batch("WH ESSL", FAR_MONTH))))
	set_active(U_ONE, ALL)

	# 6. Reports.
	from alpinos.alpinos_development.report.alpinos_shift_attendance import alpinos_shift_attendance as shift_rpt
	from alpinos.alpinos_development.report.attendance_request_punch_edits import attendance_request_punch_edits as edits_rpt
	from alpinos.alpinos_development.report.attendance_summary import attendance_summary as summary
	from alpinos.alpinos_development.report.attendance_summary import attendance_summary_export as export

	start = getdate(nowdate()).replace(day=1)
	end = add_days(start, 27)

	def summary_companies():
		return {e.company for e in summary.get_employees(frappe._dict(), start, end)}

	check("attendance summary: A only", lambda: _assert(in_company(U_HR, A, summary_companies) == {A}))
	check("attendance summary: switch to B", lambda: _assert(in_company(U_HR, B, summary_companies) == {B}))
	check("attendance summary: All shows both", lambda: _assert(in_company(U_HR, ALL, summary_companies) == {A, B}))
	check("attendance summary: Administrator unchanged", lambda: _assert({A, B} <= summary_companies()))
	check("attendance summary: company filter is a parameter, not SQL", lambda: _assert(
		summary.get_employees(frappe._dict(company="x' OR '1'='1"), start, end) == []))
	check("summary export refuses a company without HR there", lambda: as_user(
		U_ONE, lambda: _raises(lambda: export.download_final_format(str(start)[:7], company=B))))

	last_month = add_days(start, -1).replace(day=1)
	shift_filters = {"from_date": last_month, "to_date": add_days(start, -1), "consider_grace_period": 1}

	def shift_companies():
		return {r.company for r in shift_rpt.execute(dict(shift_filters))[1]}

	check("shift attendance: A only", lambda: _assert(in_company(U_HR, A, shift_companies) == {A}))
	check("shift attendance: B shows none of A", lambda: _assert(A not in in_company(U_HR, B, shift_companies)))

	def edit_companies():
		rows = edits_rpt.execute({"from_date": last_month, "to_date": add_days(start, -1)})[1]
		names = {r["attendance_request"] for r in rows}
		return set(frappe.get_all("Attendance Request", {"name": ["in", list(names) or [""]]}, pluck="company"))

	check("punch edits: B shows none of A", lambda: _assert(A not in in_company(U_HR, B, edit_companies)))
	check("punch edits: A only", lambda: _assert(in_company(U_HR, A, edit_companies) <= {A}))

	# 7. One employee's records.
	from alpinos import attendance_punch_audit, attendance_punch_repair
	from alpinos.attendance_request_automation import get_checkin_data_for_dates
	from alpinos.wfh_leave_exclusion import find_clashes

	today = nowdate()
	check("punches of a B employee opened while in A ask to switch", lambda: in_company(
		U_HR, A, lambda: _raises(lambda: get_checkin_data_for_dates(EMP_B, today, today), contains="switch")))
	check("punches of a B employee open in B", lambda: _assert(
		today in in_company(U_HR, B, lambda: get_checkin_data_for_dates(EMP_B, today, today))))
	check("explain_day of a B employee while in A asks to switch", lambda: in_company(
		U_HR, A, lambda: _raises(lambda: attendance_punch_audit.explain_day(EMP_B, today), contains="switch")))
	check("clashes of a B employee: HR of A only refused", lambda: as_user(
		U_ONE, lambda: _raises(lambda: find_clashes(EMP_B, today))))
	check("clashes of a B employee: HR of B allowed", lambda: _assert(
		"clash" in in_company(U_HR, B, lambda: find_clashes(EMP_B, today))))
	check("retyping a B punch: HR of A only refused", lambda: as_user(
		U_ONE, lambda: _raises(lambda: attendance_punch_repair.set_log_type(CKIN[1], "OUT"))))
	check("retyping a B punch (dry run): HR of B allowed", lambda: _assert(
		in_company(U_HR, B, lambda: attendance_punch_repair.set_log_type(CKIN[1], "OUT"))["mode"] == "DRY-RUN"))

	# 8. Bulk backfills are System Manager tools.
	from alpinos import attendance_healer

	check("healer backfill refused to an HR Manager", lambda: as_user(
		U_HR, lambda: _raises(lambda: attendance_healer.backfill(apply=0, from_date=today, to_date=today))))


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R
