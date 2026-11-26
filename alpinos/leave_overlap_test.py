"""HRMS #27: no two leave applications of one employee on the same dates, whatever the leave
types; Rejected and Cancelled ones do not count. TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.leave_overlap_test.run
"""

import frappe

R = []
TAG = "LOVT"


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


_n = [0]


def _existing(emp, leave_type, from_date, to_date, status="Approved", docstatus=1, state=None, half=None, period=None):
	"""An application already on the books, written straight to the table."""
	_n[0] += 1
	doc = frappe.get_doc({
		"doctype": "Leave Application",
		"name": f"{TAG}-{_n[0]}",
		"employee": emp,
		"leave_type": leave_type,
		"from_date": from_date,
		"to_date": to_date,
		"status": status,
		"docstatus": docstatus,
		"workflow_state": state or status,
		"half_day": 1 if half else 0,
		"half_day_date": half,
		"custom_half_day_period": period,
		"total_leave_days": 0.5 if half and from_date == to_date else 1,
		"posting_date": from_date,
	})
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def _new(emp, leave_type, from_date, to_date, half=None, period=None):
	return frappe.get_doc({
		"doctype": "Leave Application",
		"employee": emp,
		"leave_type": leave_type,
		"from_date": from_date,
		"to_date": to_date,
		"half_day": 1 if half else 0,
		"half_day_date": half,
		"custom_half_day_period": period,
		"total_leave_days": 0.5 if half and from_date == to_date else 1,
		"status": "Draft",
	})


def _blocked(doc):
	"""The overlap message, or None when the dates are free."""
	from hrms.hr.doctype.leave_application.leave_application import OverlapError

	try:
		doc.validate_leave_overlap()
	except OverlapError as e:
		frappe.clear_messages()
		return str(e)
	return None


def _run():
	from alpinos.overrides.leave_application_override import OVERLAP_MESSAGE

	emp = frappe.db.get_value("Employee", {"status": "Active"}, "name", order_by="name")
	types = frappe.get_all("Leave Type", pluck="name", order_by="name")
	_assert(len(types) >= 2, "need two leave types")
	a, b = types[0], types[1]
	# far ahead, so no real application of this employee sits on these dates
	D = lambda day: f"2031-11-{day:02d}"  # noqa: E731
	# remove anything real that might sit there (rolled back anyway)
	frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})

	def _pending_other_type():
		_existing(emp, a, D(16), D(23), status="Draft", docstatus=0, state="Pending Reporting Manager Approval")
		msg = _blocked(_new(emp, b, D(20), D(26)))
		_assert(msg and OVERLAP_MESSAGE in msg, msg)
		_assert(a in msg and "Pending Reporting Manager Approval" in msg, msg)

	check("The task's case: 16-23 Nov waiting for approval, a new 20-26 Nov of another type is refused", _pending_other_type)

	def _every_active_state():
		frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})
		for status, ds, state in (
			("Approved", 1, "Approved"),
			("Draft", 0, "Draft"),
			("Draft", 0, "Pending HR Approval"),
			("Open", 0, None),
		):
			name = _existing(emp, a, D(16), D(23), status=status, docstatus=ds, state=state)
			_assert(_blocked(_new(emp, b, D(18), D(18))), f"{status}/{state} did not block")
			frappe.db.delete("Leave Application", {"name": name})

	check("Approved, Draft, Pending HR and Open applications all hold their dates", _every_active_state)

	def _rejected_cancelled_free():
		frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})
		_existing(emp, a, D(16), D(23), status="Rejected", docstatus=1, state="Rejected")
		_existing(emp, a, D(16), D(23), status="Cancelled", docstatus=2, state="Approved")
		_existing(emp, a, D(16), D(23), status="Cancelled", docstatus=1, state="Approved")
		_existing(emp, a, D(16), D(23), status="Draft", docstatus=0, state="Rejected")
		msg = _blocked(_new(emp, b, D(20), D(26)))
		_assert(msg is None, msg)

	check("Rejected and Cancelled applications do not block new ones", _rejected_cancelled_free)

	def _same_type_and_edges():
		frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})
		_existing(emp, a, D(16), D(23))
		_assert(_blocked(_new(emp, a, D(23), D(25))), "same type touching on the last day")
		_assert(_blocked(_new(emp, b, D(10), D(16))), "another type touching on the first day")
		_assert(_blocked(_new(emp, b, D(10), D(30))), "covering the whole existing leave")
		_assert(_blocked(_new(emp, a, D(24), D(26))) is None, "the day after is free")
		other = frappe.db.get_value("Employee", {"status": "Active", "name": ["!=", emp]}, "name")
		_assert(_blocked(_new(other, b, D(20), D(26))) is None, "another employee is not affected")

	check("Any shared day blocks, same or other type; next day and other employees stay free", _same_type_and_edges)

	def _editing_itself():
		frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})
		name = _existing(emp, a, D(16), D(23), status="Draft", docstatus=0, state="Pending HR Approval")
		doc = frappe.get_doc("Leave Application", name)
		doc.to_date = D(24)
		_assert(_blocked(doc) is None, "an application blocked itself")

	check("An application never blocks itself (resave, approval steps)", _editing_itself)

	def _half_days():
		frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})
		_existing(emp, a, D(18), D(18), half=D(18), period="First Half")
		_assert(_blocked(_new(emp, b, D(18), D(18), half=D(18), period="Second Half")) is None, "other half refused")
		_assert(_blocked(_new(emp, b, D(18), D(18), half=D(18), period="First Half")), "same half allowed")
		_assert(_blocked(_new(emp, b, D(18), D(18))), "a full day over a half day allowed")
		_existing(emp, b, D(18), D(18), half=D(18), period="Second Half")
		_assert(_blocked(_new(emp, b, D(18), D(18), half=D(18))), "a third half day on one date allowed")

	check("Half days: First + Second Half on one date allowed; same half, full day or a third one refused", _half_days)

	def _wired_into_save():
		from hrms.hr.doctype.leave_application.leave_application import OverlapError

		frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})
		_existing(emp, a, D(16), D(23), status="Draft", docstatus=0, state="Pending Reporting Manager Approval")
		# an unpaid type needs no allocation, so HRMS's allocation checks do not stop it first
		lwp = frappe.db.get_value("Leave Type", {"is_lwp": 1}, "name") or b
		doc = _new(emp, lwp, D(20), D(26))
		try:
			doc.insert(ignore_permissions=True)
		except OverlapError as e:
			frappe.clear_messages()
			_assert(OVERLAP_MESSAGE in str(e), str(e))
			return
		except frappe.ValidationError as e:
			# another HRMS check fired first; the overlap still has to be what save runs
			frappe.clear_messages()
			_assert(False, f"save stopped on something else first: {e}")
		_assert(False, "saved over a pending leave")

	check("Saving the form runs the check (save, submit and each approval step validate)", _wired_into_save)
