"""Company-wise access, the real HR chain in a second company (Hire Hunt). TEST sites only:

	bench --site <test site> execute alpinos.company_scope.hr_flow_test.run

Everything runs in ONE transaction that is rolled back at the end (frappe.db.commit is
switched off for the run, frappe.sendmail / frappe.enqueue / Raven DMs are captured), so the
site keeps none of it (the pre-onboarding mail's trace Error Logs, which outlive a rollback,
are deleted after it): users cs.flow.hr.*@example.com, employees CS-FLOW-HR-*, their punches,
requests, leave, attendance, batches, and the Hire Hunt HR mailbox set for step 5.

	emp   an employee of HH (Employee + User), reporting to rm
	rm    an employee of the default company, global Reporting Manager / Leave Approver
	hh    HR Manager in HH only            a     HR Manager in the default company only
	both  HR Manager in both companies
"""

import re

import frappe
from frappe.utils import add_days, getdate, nowdate

from alpinos.company_scope import access
from alpinos.company_scope.testing import ALL, as_user, fresh, make_user, set_active

R = []

U_EMP, U_RM = "cs.flow.hr.emp@example.com", "cs.flow.hr.rm@example.com"
U_HH, U_A, U_BOTH = "cs.flow.hr.hh@example.com", "cs.flow.hr.a@example.com", "cs.flow.hr.both@example.com"
USERS = (U_EMP, U_RM, U_HH, U_A, U_BOTH)
EMP, EMP_RM = "CS-FLOW-HR-EMP", "CS-FLOW-HR-RM"
HH_MAILBOX = "cs.flow.hr.mailbox@example.com"
JOINEE = "cs.flow.hr.joinee@example.com"
AR_WF, LA_WF = "Attendance Request", "Leave Application"


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:300]}"))


def gap(label, fn):
	"""A known gap outside this domain: GAP while it still fails, PASS once it is fixed."""
	try:
		fn()
		R.append(("PASS", label, ""))
	except Exception as e:
		R.append(("GAP", label, f"{type(e).__name__}: {str(e)[:200]}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _raises(fn, exc=(frappe.PermissionError,), contains=None):
	try:
		fn()
	except exc as e:
		if contains and contains not in str(e):
			raise AssertionError(f"raised, but '{contains}' not in: {e}")
		return str(e) or type(e).__name__
	raise AssertionError("did not raise")


class _Capture:
	"""frappe.sendmail, frappe.enqueue and the Raven DM sender, recorded instead of run."""

	def __init__(self):
		self.mails, self.jobs, self.dms = [], [], []

	def __enter__(self):
		from alpinos import raven_notifications as rn

		self._saved = (frappe.sendmail, frappe.enqueue, rn._send_dm, rn._get_bot)
		frappe.sendmail = lambda *a, **k: self.mails.append(k)
		frappe.enqueue = lambda *a, **k: self.jobs.append((a, k))
		rn._send_dm = lambda bot, user, text, doc=None: self.dms.append((user, text, doc.name if doc else None))
		rn._get_bot = lambda: object()
		return self

	def __exit__(self, *exc):
		from alpinos import raven_notifications as rn

		frappe.sendmail, frappe.enqueue, rn._send_dm, rn._get_bot = self._saved

	def recipients(self, mail):
		out = []
		for key in ("recipients", "cc"):
			value = mail.get(key) or []
			out += [value] if isinstance(value, str) else list(value)
		return set(out)


def _companies():
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	hh = frappe.db.get_value("Company", {"abbr": "HH"}) or frappe.db.sql(
		"""select company from `tabEmployee` where status = 'Active' and company != %s
		group by company order by count(*) desc limit 1""", default)[0][0]
	return default, hh


def _working_day(start, step):
	"""The nearest day from `start` (stepping by `step`) that is no holiday in the list used."""
	d = getdate(start)
	while d.weekday() >= 5 or frappe.db.exists("Holiday", {"parent": HOLIDAY_LIST, "holiday_date": d}):
		d = add_days(d, step)
	return d


HOLIDAY_LIST = None


def run():
	global HOLIDAY_LIST
	R.clear()
	frappe.set_user("Administrator")
	A, HH = _companies()
	HOLIDAY_LIST = frappe.db.get_value("Company", A, "default_holiday_list")
	db = frappe.db
	real_commit = db.commit
	db.commit = lambda *a, **k: None
	try:
		from alpinos.company_scope.testing import ensure_enabled

		ensure_enabled()
		with _Capture() as cap:
			_run(A, HH, cap)
	finally:
		db.commit = real_commit
		frappe.set_user("Administrator")
		db.rollback()
		# Error Logs outlive a rollback; the pre-onboarding mail writes three trace rows a call.
		frappe.db.sql(
			"""delete from `tabError Log` where method = 'Onboarding Email Trace' and error like %s""",
			(f"%{JOINEE}%",),
		)
		db.commit()
		for user in USERS:
			access.clear_cache(user)
			frappe.clear_cache(user=user)
		frappe.clear_document_cache("Company", HH)
		fresh()
	return _report()


def _fixtures(A, HH):
	make_user(U_HH, {HH: ["HR Manager"]})
	make_user(U_A, {A: ["HR Manager"]})
	make_user(U_BOTH, {A: ["HR Manager"], HH: ["HR Manager"]})
	make_user(U_RM, {A: []}, global_roles=("Employee", "Reporting Manager", "Leave Approver"))
	make_user(U_EMP, {HH: []}, global_roles=("Employee",))

	def employee(name, template, company, label, **extra):
		doc = frappe.copy_doc(frappe.get_doc("Employee", template))
		doc.update({
			"name": name, "employee": name, "first_name": label, "middle_name": None, "last_name": None,
			"employee_name": label, "company": company, "status": "Active", "attendance_device_id": None,
			"relieving_date": None, "custom_suspension_date": None, "holiday_list": HOLIDAY_LIST,
			"family_relation": doc.get("family_relation") or "Father", "date_of_joining": "2025-01-01",
			"department": None, "reports_to": None, "leave_approver": None, "expense_approver": None,
			"default_shift": None, "custom_no_biometric": 0, "create_user_permission": 0,
		})
		doc.update(extra)
		doc.insert(ignore_permissions=True)
		return doc

	tpl_a = frappe.db.get_value("Employee", {"company": A, "status": "Active"}, "name", order_by="name asc")
	tpl_hh = frappe.db.get_value("Employee", {"company": HH, "status": "Active"}, "name", order_by="name asc")
	employee(EMP_RM, tpl_a, A, "CS Flow HR Manager Of Team", user_id=U_RM)
	employee(EMP, tpl_hh, HH, "CS Flow HR Employee", user_id=U_EMP, reports_to=EMP_RM, leave_approver=U_RM)
	for user in USERS:
		set_active(user, HH if user in (U_HH, U_EMP, U_BOTH) else A)


def _save_as(user, doc):
	"""Save a new document the way the form does (savedocs), as `user`; returns its name."""
	from frappe.desk.form.save import savedocs

	doc = dict(doc, __islocal=1, name="new-" + doc["doctype"].lower().replace(" ", "-") + "-1")

	def go():
		frappe.response.docs = []
		savedocs(frappe.as_json(doc), "Save")
		return frappe.response.docs[0]["name"]

	return as_user(user, go)


def _action(user, doctype, name, action):
	from frappe.model.workflow import apply_workflow

	return as_user(user, lambda: apply_workflow(frappe.as_json({"doctype": doctype, "name": name}), action))


def _open(user, doctype, name):
	from frappe.desk.form.load import getdoc

	return as_user(user, lambda: getdoc(doctype, name))


def _run(A, HH, cap):
	_fixtures(A, HH)
	hh_code = frappe.get_cached_value("Company", HH, "custom_series_code") or "HH"

	# 1a. Attendance Request: the employee edits a punch on record; HR of HH approves.
	day = _working_day(add_days(nowdate(), -1), -1)
	for log_type, at in (("IN", "09:40:00"), ("OUT", "18:30:00")):
		ci = frappe.new_doc("Employee Checkin")
		ci.flags.skip_attendance_heal = True
		ci.flags.skip_geo_validation = True
		ci.update({"employee": EMP, "log_type": log_type, "time": f"{day} {at}"})
		ci.insert(ignore_permissions=True)
	ar = _save_as(U_EMP, {
		"doctype": "Attendance Request", "__islocal": 1, "employee": EMP, "company": HH, "reason": "Office",
		"explanation": "CS flow: forgot the badge", "custom_request_date": str(day), "from_date": str(day),
		"to_date": str(day),
		"custom_attendance_details": [{"attendance_date": str(day), "edit_check_in": 1, "check_in": "09:05:00"}],
	})
	ar_doc = lambda: frappe.get_doc("Attendance Request", ar)  # noqa: E731
	# Attendance Request is named by autoname, not a naming series: no company code.
	check(f"AR {ar}: raised by the HH employee, in HH", lambda: _assert(ar_doc().company == HH, ar_doc().company))
	check("AR: a punch edit, sent to the reporting manager", lambda: (
		_action(U_EMP, AR_WF, ar, "Submit for Approval"),
		_assert(ar_doc().workflow_state == "Pending RM Approval" and ar_doc().custom_is_punch_edit
			and ar_doc().reporting_person == U_RM, (ar_doc().workflow_state, ar_doc().reporting_person))))
	check("AR: HR of the default company only cannot open it", lambda: _raises(lambda: _open(U_A, AR_WF, ar)))

	cap.dms.clear()

	def rm_approves():
		_action(U_RM, AR_WF, ar, "Approve")
		_assert(ar_doc().workflow_state == "Pending HR Approval", ar_doc().workflow_state)

	# The manager is a member of the default company only, so his Company User Permission
	# (company_scope.sync) hides the HH team member's request from him.
	gap("AR: a manager in the default company only can open his HH team member's request",
		lambda: _open(U_RM, AR_WF, ar))
	from alpinos.company_scope import sync

	sync.ensure_membership(U_RM, HH, [], source="Manual", is_default=False)
	sync.sync_user(U_RM)
	fresh()
	check("AR: with a no-role membership in HH the manager approves his team member", rm_approves)
	from alpinos.raven_notifications import _approvers_for_state

	check("AR: Raven HR-stage DMs go to HH HR Managers only", lambda: _assert(
		{u for u, _t, d in cap.dms if d == ar and "needs your approval" in _t} == set(_approvers_for_state(ar_doc(), "Pending HR Approval"))
		and U_HH in {u for u, _t, d in cap.dms if d == ar} and U_A not in {u for u, _t, d in cap.dms if d == ar},
		cap.dms))
	check("AR: HR-stage recipients are the HR Managers holding the role in HH", lambda: _assert(
		U_HH in _approvers_for_state(ar_doc(), "Pending HR Approval")
		and U_BOTH in _approvers_for_state(ar_doc(), "Pending HR Approval")
		and U_A not in _approvers_for_state(ar_doc(), "Pending HR Approval")))

	from alpinos.approval_dashboard import get_pending_approvals

	def pending(user):
		return as_user(user, lambda: {i["name"] for i in get_pending_approvals()["items"]})

	check("AR: on the HH HR's approvals dashboard, not the default-company HR's", lambda: _assert(
		ar in pending(U_HH) and ar not in pending(U_A)))
	check("AR: HR of the default company only cannot approve (API)", lambda: _raises(
		lambda: _action(U_A, AR_WF, ar, "Approve"), (frappe.PermissionError, frappe.ValidationError)))
	check("AR: HR of the default company only cannot open it (form)", lambda: _raises(lambda: _open(U_A, AR_WF, ar)))
	check("AR: still pending after the refusal", lambda: _assert(ar_doc().workflow_state == "Pending HR Approval"))

	def hh_approves():
		_action(U_HH, AR_WF, ar, "Approve")
		doc = ar_doc()
		_assert(doc.workflow_state == "Approved" and doc.docstatus == 1, (doc.workflow_state, doc.docstatus))

	check("AR: HR of HH approves", hh_approves)
	att = frappe.db.get_value("Attendance", {"employee": EMP, "attendance_date": day, "docstatus": 1},
		["name", "company", "in_time"], as_dict=True)
	check(f"AR approval marks attendance {att and att.name} in HH", lambda: _assert(
		att and att.company == HH and f"-{hh_code}-" in att.name, att))
	check("AR approval moved the punch to the requested time, in HH", lambda: _assert(
		frappe.db.exists("Employee Checkin", {"employee": EMP, "time": f"{day} 09:05:00", "company": HH})))

	# 1b. Leave Application: the employee applies, HR of HH approves at the manager's stage.
	leave_day = _working_day(add_days(nowdate(), 1), 1)
	la = _save_as(U_EMP, {
		"doctype": "Leave Application", "__islocal": 1, "employee": EMP, "company": HH, "leave_type": "Unpaid",
		"from_date": str(leave_day), "to_date": str(leave_day), "posting_date": nowdate(),
		"leave_approver": U_RM, "description": "CS flow leave", "status": "Open",
	})
	la_doc = lambda: frappe.get_doc("Leave Application", la)  # noqa: E731
	check(f"Leave {la}: raised by the HH employee in HH, numbered with {hh_code}", lambda: _assert(
		la_doc().company == HH and f"-{hh_code}-" in la, (la_doc().company, la)))
	check("Leave: sent for approval", lambda: (
		_action(U_EMP, LA_WF, la, "Send for Approval"),
		_assert(la_doc().workflow_state == "Pending Reporting Manager Approval", la_doc().workflow_state)))
	check("Leave: HR of the default company only cannot open it (form)", lambda: _raises(lambda: _open(U_A, LA_WF, la)))
	check("Leave: HR of the default company only cannot approve (API)", lambda: _raises(
		lambda: _action(U_A, LA_WF, la, "Approve"), (frappe.PermissionError, frappe.ValidationError)))
	check("Leave: on the HH HR's approvals dashboard, not the default-company HR's", lambda: _assert(
		la in pending(U_HH) and la not in pending(U_A)))

	def hh_approves_leave():
		_action(U_HH, LA_WF, la, "Approve")
		doc = la_doc()
		_assert(doc.workflow_state == "Approved" and doc.status == "Approved" and doc.docstatus == 1,
			(doc.workflow_state, doc.status, doc.docstatus))

	check("Leave: HR of HH approves", hh_approves_leave)
	check("Leave: the ledger entry is in HH", lambda: _assert(
		frappe.db.get_value("Leave Ledger Entry", {"transaction_name": la}, "company") == HH))

	# 2. Monthly Attendance Batch per company.
	from alpinos import attendance_batch_api as batches

	month = add_days(getdate(nowdate()).replace(day=1), -40).replace(day=1)
	stamp = f"{month.year}-{month.month:02d}"
	hh_abbr = frappe.get_cached_value("Company", HH, "abbr")
	names = {}

	def create(user, key):
		names[key] = as_user(user, lambda: batches.create_batch("HO/Admin", str(month)))
		return names[key]

	check(f"batch: HH HR creates ATT-BATCH-{hh_abbr}-{stamp}-HO", lambda: _assert(
		create(U_HH, "hh") == f"ATT-BATCH-{hh_abbr}-{stamp}-HO"
		and frappe.db.get_value("Monthly Attendance Batch", names["hh"], "company") == HH, names))
	check(f"batch: the default company's batch for the month keeps ATT-BATCH-{stamp}-HO", lambda: _assert(
		create(U_A, "a") == f"ATT-BATCH-{stamp}-HO"
		and frappe.db.get_value("Monthly Attendance Batch", names["a"], "company") == A, names))
	check("batch: a second HH batch for the month is refused", lambda: _raises(
		lambda: as_user(U_HH, lambda: batches.create_batch("HO/Admin", str(month))), frappe.ValidationError,
		contains="already exists"))
	check("batch: HR of the default company cannot open, fill or move the HH batch", lambda: (
		_raises(lambda: as_user(U_A, lambda: batches.get_batch(names["hh"]))),
		_raises(lambda: as_user(U_A, lambda: batches.populate_batch_rows(names["hh"]))),
		_raises(lambda: as_user(U_A, lambda: batches.apply_batch_action(names["hh"], "Submit for Approval")),
			(frappe.PermissionError, frappe.ValidationError))))

	def hh_rows():
		try:
			as_user(U_HH, lambda: batches.populate_batch_rows(names["hh"]))
		except frappe.ValidationError as e:
			# Uncategorized employees block the generation; the list must be HH's alone.
			ids = set(re.findall(r"\(([^()]+)\)", str(e)))
			companies = set(frappe.get_all("Employee", {"name": ["in", list(ids) or [""]]}, pluck="company"))
			_assert(companies <= {HH}, companies)
			return
		rows = frappe.get_all("Monthly Attendance Batch Row", {"parent": names["hh"]}, pluck="employee")
		_assert(set(frappe.get_all("Employee", {"name": ["in", rows or [""]]}, pluck="company")) <= {HH})

	check("batch: HH HR generates rows only from HH employees", hh_rows)
	check("batch: HH HR sends the HH batch for approval", lambda: _assert(as_user(U_HH, lambda: batches.apply_batch_action(
		names["hh"], "Submit for Approval"))["workflow_state"] == "Pending Approval"))

	def batch_list(user):
		return as_user(user, lambda: {b.name for b in batches.get_batches(page_length=500)["batches"]})

	check("batch list: HH HR sees the HH batch only, default HR the default one only", lambda: _assert(
		names["hh"] in batch_list(U_HH) and names["a"] not in batch_list(U_HH)
		and names["a"] in batch_list(U_A) and names["hh"] not in batch_list(U_A)))

	# 3. Missing check-in digest: each HR Manager hears about their companies' employees.
	from alpinos import attendance_alerts

	_today, flagged = attendance_alerts.get_flagged_employees()
	company_of = {e.name: e.company for e in flagged}
	cap.mails.clear()
	attendance_alerts.notify_missing_checkins()
	digests = [m for m in cap.mails if "no check-in by 11:30" in (m.get("subject") or "") and "your team" not in m.get("subject")]

	def listed(mail):
		return {company_of.get(i) for i in re.findall(r"<td style='[^']*'>([^<]+?) — ", mail.get("message") or "")}

	def mails_to(user):
		return [m for m in digests if frappe.db.get_value("User", user, "email") in cap.recipients(m)]

	check("digest: the run flags employees of HH", lambda: _assert(HH in set(company_of.values()), set(company_of.values())))
	check("digest: HR of HH gets one digest, HH employees only", lambda: _assert(
		len(mails_to(U_HH)) == 1 and listed(mails_to(U_HH)[0]) == {HH}, [listed(m) for m in mails_to(U_HH)]))
	check("digest: HR of the default company gets no HH employee", lambda: _assert(
		all(HH not in listed(m) for m in mails_to(U_A)) and (A not in company_of.values() or len(mails_to(U_A)) == 1)))
	check("digest: HR of both gets one digest with every flagged company", lambda: _assert(
		len(mails_to(U_BOTH)) == 1 and listed(mails_to(U_BOTH)[0]) == set(company_of.values()) & {A, HH}))

	# 4. HR email layout per company.
	def render(company):
		tmpl = frappe.get_doc("Email Template", "Onboarding - Job Confirmation")
		return tmpl.get_formatted_email({"doc": {"company": company, "company_name": company,
			"candidate_name": "CS Flow Candidate", "job_title": "Tester"}})["message"]

	hh_mail, a_mail = render(HH), render(A)
	alpino_bits = ("alpino.store", "Napoleon Estate", "linkedin.com/company/alpinohealthfoods",
		"instagram.com/alpinohealthfoods", "facebook.com/alpinohealthfoods", "gstatic.com", 'alt="Alpino"', 'src="None"')
	check("HR email for HH shows HH and nothing of Alpino", lambda: _assert(
		HH in hh_mail and not [b for b in alpino_bits if b in hh_mail], [b for b in alpino_bits if b in hh_mail]))
	check("HR email for the default company keeps the Alpino logo and footer", lambda: _assert(
		all(re.sub(r"\s+", " ", p) in re.sub(r"\s+", " ", a_mail) for p in _ALPINO_FOOTER), a_mail[-1500:]))

	# 5. Onboarding mails: HR of the joinee's company + that company's mailbox.
	from alpinos.employee_onboarding_automation import send_pre_onboarding_email
	from alpinos.employee_onboarding_webform import _notify_hr_webform_submitted

	frappe.db.set_value("Company", HH, "custom_hr_email", HH_MAILBOX, update_modified=False)
	frappe.clear_document_cache("Company", HH)
	template = frappe.db.get_value("Employee Onboarding", {}, "name", order_by="creation desc")

	def onboarding(company):
		doc = frappe.get_doc("Employee Onboarding", template)
		doc.company = company
		return doc

	def hr_emails(company):
		return {frappe.db.get_value("User", u, "email") for u in access.users_with_roles(["HR Manager"], company)
			if u not in ("Administrator", "Guest")}

	def webform_mail(company):
		cap.mails.clear()
		_notify_hr_webform_submitted(onboarding(company))
		_assert(len(cap.mails) == 1, cap.mails)
		return cap.recipients(cap.mails[0])

	a_email = lambda u: frappe.db.get_value("User", u, "email")  # noqa: E731
	def hh_webform():
		got = webform_mail(HH)
		_assert(got == hr_emails(HH) | {HH_MAILBOX} and a_email(U_A) not in got and a_email(U_HH) in got
			and "admin@example.com" not in got, got ^ (hr_emails(HH) | {HH_MAILBOX}))

	def a_webform():
		got = webform_mail(A)
		_assert(got == hr_emails(A) | {"hr@alpinohealthfoods.com"} and a_email(U_HH) not in got
			and a_email(U_A) in got, got ^ (hr_emails(A) | {"hr@alpinohealthfoods.com"}))

	check("onboarding submitted (HH): HH HR Managers + HH mailbox, no default-only HR, no Administrator", hh_webform)
	check("onboarding submitted (default company): its HR Managers + hr@alpinohealthfoods.com", a_webform)

	def pre_mail(company):
		cap.mails.clear()
		send_pre_onboarding_email(onboarding(company), JOINEE)
		_assert(len(cap.mails) == 1, cap.mails)
		return cap.mails[0]

	def hh_pre_mail():
		mail = pre_mail(HH)
		leaks = [b for b in ("alpino.store", "6359474000", "Khushi Doshi", 'src="None"') if b in mail["message"]]
		_assert(mail.get("cc") == [HH_MAILBOX] and HH in mail["message"] and not leaks, (mail.get("cc"), leaks))

	def a_pre_mail():
		mail = pre_mail(A)
		_assert(mail.get("cc") == ["hr@alpinohealthfoods.com"] and "alpino.store" in mail["message"]
			and "6359474000" in mail["message"], mail.get("cc"))

	check("pre-onboarding mail (HH): CC the HH mailbox, HH layout, no Alpino HR contact", hh_pre_mail)
	check("pre-onboarding mail (default company): CC hr@alpinohealthfoods.com, Alpino footer and contact", a_pre_mail)

	# 6. Lists as HH HR, default-company HR and in All mode.
	from alpinos.company_scope.helpers import listing

	def list_view(fn):
		with listing():
			return fn()

	def companies_in(user, doctype, company=None):
		if company:
			set_active(user, company)
		return as_user(user, lambda: list_view(lambda: set(
			frappe.get_list(doctype, fields=["company"], group_by="company", pluck="company"))))

	def names_in(user, doctype, filters):
		return as_user(user, lambda: list_view(lambda: set(frappe.get_list(doctype, filters=filters, pluck="name"))))

	for doctype, mine in (("Attendance", att and att.name), ("Attendance Request", ar), ("Leave Application", la),
			("Employee Checkin", None), ("Employee", EMP)):
		check(f"list {doctype}: HH HR sees HH only", lambda doctype=doctype: _assert(
			companies_in(U_HH, doctype) <= {HH}, companies_in(U_HH, doctype)))
		check(f"list {doctype}: default-company HR sees the default company only", lambda doctype=doctype: _assert(
			companies_in(U_A, doctype) <= {A}, companies_in(U_A, doctype)))
		check(f"list {doctype}: HR of both in All sees both, switched to the default no HH", lambda doctype=doctype: _assert(
			{A, HH} <= companies_in(U_BOTH, doctype, ALL) and HH not in companies_in(U_BOTH, doctype, A),
			(companies_in(U_BOTH, doctype, ALL), companies_in(U_BOTH, doctype, A))))
		if mine:
			check(f"list {doctype}: the flow's {mine} is in HH HR's list, not the default HR's", lambda doctype=doctype, mine=mine: _assert(
				mine in names_in(U_HH, doctype, {"name": mine}) and mine not in names_in(U_A, doctype, {"name": mine})))
	check("list Employee Checkin: the flow's punches are in HH HR's list, not the default HR's", lambda: _assert(
		names_in(U_HH, "Employee Checkin", {"employee": EMP}) and not names_in(U_A, "Employee Checkin", {"employee": EMP})))


# The default company's footer, exactly as the layout had it before company-wise access.
_ALPINO_FOOTER = (
	"""<img src="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR0cfjJi3U8tgoX4Jk3zp07AXjRNveFA-jxLA&s" alt="Alpino" style="max-height:72px;max-width:260px;height:auto;" />""",
	"""<p style="margin:0 0 8px 0;"><strong>Website:</strong> <a href="https://alpino.store/" target="_blank">https://alpino.store/</a></p>""",
	"""<p style="margin:0 0 8px 0;"><strong>Address:</strong> Alpino Health Foods, Bungalow No.7, Napoleon Estate, Near VR Mall, Udhana-Magdalla Road, New Magdalla, Dumas, Surat, Gujarat - 395007, India</p>""",
	"""<p style="margin:0;"><strong>Social:</strong>
<a href="https://www.linkedin.com/company/alpinohealthfoods/" target="_blank">LinkedIn</a> |
<a href="https://www.instagram.com/alpinohealthfoods" target="_blank">Instagram</a> |
<a href="https://www.facebook.com/alpinohealthfoods" target="_blank">Facebook</a>
</p>""",
)


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R
