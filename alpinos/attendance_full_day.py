"""HRMS #8 - "Mark as Full Day" from the Attendance Summary report.

HR ticks employees on the report, picks a date and types a reason, and each of them is
marked Present for the whole of that day. Unlike Default Present this is a deliberate HR
override, so it does NOT check custom_default_present and it does NOT skip a holiday --
if HR says the day is a full day, it is. The reason is stored on the Attendance so the
override can be explained later.
"""

import json

import frappe
from frappe import _
from frappe.utils import getdate

#: Only these may override an attendance day.
ALLOWED_ROLES = ("HR Manager", "HR User")


def _assert_may_mark():
	roles = set(frappe.get_roles())
	if roles.isdisjoint(ALLOWED_ROLES) and "System Manager" not in roles:
		frappe.throw(
			_("Only HR can mark a day as a full day."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def mark_full_day(employees, date, reason):
	"""Mark every given employee Present for the whole of `date`, carrying `reason`.

	Returns {marked, skipped, reason, date} -- skipped rows carry a why, so the caller can
	tell the operator which employees were left alone rather than silently dropping them.
	"""
	_assert_may_mark()

	if isinstance(employees, str):
		employees = json.loads(employees)
	employees = [e for e in (employees or []) if e]
	if not employees:
		frappe.throw(_("Select at least one employee."))

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required to mark a day as a full day."))
	if not date:
		frappe.throw(_("Select the date to mark."))
	date = getdate(date)

	# Reuse the Default Present shift resolution so a marked day carries the same in/out
	# times a normal present day would.
	from alpinos.default_present import _shift_for, _shift_times

	has_flag = frappe.get_meta("Attendance").has_field("custom_marked_full_day")
	marked, skipped = [], []

	for employee in employees:
		emp = frappe.db.get_value(
			"Employee",
			employee,
			["name", "employee_name", "date_of_joining", "relieving_date", "default_shift", "company"],
			as_dict=True,
		)
		if not emp:
			skipped.append({"employee": employee, "why": _("No such Employee")})
			continue
		# Before joining or after leaving there is no day to mark; everything else is HR's call.
		if emp.date_of_joining and date < getdate(emp.date_of_joining):
			skipped.append({"employee": employee, "why": _("Before joining date")})
			continue
		if emp.relieving_date and date > getdate(emp.relieving_date):
			skipped.append({"employee": employee, "why": _("After relieving date")})
			continue

		values = {
			"status": "Present",
			"leave_type": None,
			"leave_application": None,
			"half_day_status": None,
			"late_entry": 0,
			"early_exit": 0,
		}
		# Shift timings are best effort: no resolvable shift still marks the day Present
		# rather than skipping the employee the operator explicitly picked.
		shift = _shift_for(employee, date, emp.default_shift)
		if shift:
			in_time, out_time, working_hours = _shift_times(shift, date)
			if in_time is not None:
				values.update({
					"shift": shift,
					"in_time": in_time,
					"out_time": out_time,
					"working_hours": working_hours,
				})
		if has_flag:
			values["custom_marked_full_day"] = 1
			values["custom_full_day_reason"] = reason

		try:
			existing = frappe.db.get_value(
				"Attendance",
				{"employee": employee, "attendance_date": date, "docstatus": ["<", 2]},
				"name",
			)
			if existing:
				# Overridden in place so a SUBMITTED day can be corrected without the
				# cancel/amend dance -- same approach Default Present takes.
				frappe.db.set_value("Attendance", existing, values, update_modified=True)
				marked.append({"employee": employee, "employee_name": emp.employee_name,
				               "attendance": existing, "action": "updated"})
				continue

			doc = frappe.new_doc("Attendance")
			doc.employee = employee
			doc.attendance_date = date
			doc.company = emp.company
			for k, v in values.items():
				setattr(doc, k, v)
			# bypass leave-overlap / duplicate guards: an HR override outranks them
			doc.flags.ignore_validate = True
			doc.insert(ignore_permissions=True)
			doc.submit()
			marked.append({"employee": employee, "employee_name": emp.employee_name,
			               "attendance": doc.name, "action": "created"})
		except Exception:
			frappe.log_error(
				title="Mark as Full Day failed for {0} on {1}".format(employee, date),
				message=frappe.get_traceback(),
			)
			skipped.append({"employee": employee, "why": _("Failed - see Error Log")})

	if marked:
		frappe.db.commit()

	return {
		"date": str(date),
		"reason": reason,
		"marked": marked,
		"skipped": skipped,
	}
