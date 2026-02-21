"""
Override Employee Checkin to require a reason when clocking OUT from outside the office geo-fence.
Check-IN from outside remains blocked; check-OUT from outside is allowed only with checkout_reason.
Also syncs checkout_reason from the last OUT checkin to Attendance when marking attendance.
"""

import frappe
from frappe import _

from hrms.hr.doctype.employee_checkin.employee_checkin import (
	EmployeeCheckin,
	CheckinRadiusExceededError,
)
from hrms.hr.utils import get_distance_between_coordinates
from frappe.utils import get_datetime, getdate

_patch_applied = False


def _apply_checkout_reason_patch():
	# Apply once when this module is loaded so HRMS uses patched mark_attendance_and_link_log
	global _patch_applied
	if _patch_applied:
		return
	import hrms.hr.doctype.employee_checkin.employee_checkin as ec_module
	_original = ec_module.mark_attendance_and_link_log

	def _mark_attendance_and_link_log(
		logs,
		attendance_status,
		attendance_date,
		working_hours=None,
		late_entry=False,
		early_exit=False,
		in_time=None,
		out_time=None,
		shift=None,
		overtime_type=None,
	):
		attendance = _original(
			logs=logs,
			attendance_status=attendance_status,
			attendance_date=attendance_date,
			working_hours=working_hours,
			late_entry=late_entry,
			early_exit=early_exit,
			in_time=in_time,
			out_time=out_time,
			shift=shift,
			overtime_type=overtime_type,
		)
		if attendance and logs:
			last_out = None
			for log in logs:
				if getattr(log, "log_type", None) == "OUT":
					last_out = log
			if last_out and getattr(last_out, "checkout_reason", None):
				frappe.db.set_value(
					"Attendance",
					attendance.name,
					"checkout_reason",
					last_out.checkout_reason,
					update_modified=False,
				)
		return attendance

	ec_module.mark_attendance_and_link_log = _mark_attendance_and_link_log
	_patch_applied = True


class CustomEmployeeCheckin(EmployeeCheckin):
	def validate_distance_from_shift_location(self):
		if not frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking"):
			return

		# Check-in: require lat/long (HRMS default message)
		if not (self.latitude or self.longitude):
			if self.log_type == "OUT":
				# Allow checkout without location; no reason required
				return
			frappe.throw(_("Latitude and longitude values are required for checking in."))

		# Resolve shift for this time (fetch_shift already ran in validate)
		if not self.shift:
			return
		assignment_locations = frappe.get_all(
			"Shift Assignment",
			filters={
				"employee": self.employee,
				"shift_type": self.shift,
				"start_date": ["<=", self.time],
				"shift_location": ["is", "set"],
				"docstatus": 1,
				"status": "Active",
			},
			or_filters=[["end_date", ">=", self.time], ["end_date", "is", "not set"]],
			pluck="shift_location",
		)
		if not assignment_locations:
			return

		checkin_radius, latitude, longitude = frappe.db.get_value(
			"Shift Location", assignment_locations[0], ["checkin_radius", "latitude", "longitude"]
		)
		if not checkin_radius or checkin_radius <= 0:
			return

		distance = get_distance_between_coordinates(
			latitude, longitude, self.latitude, self.longitude
		)
		if distance <= checkin_radius:
			return

		# Outside radius
		if self.log_type == "IN":
			# Allow check-in from outside only if employee has applied for Work From Home for this day
			checkin_date = getdate(self.time)
			wfh_exists = frappe.db.exists(
				"Work From Home Request",
				{
					"employee": self.employee,
					"date": checkin_date,
					"status": ["in", ["Draft", "Approved"]],
				},
			)
			if wfh_exists:
				return
			frappe.throw(
				_(
					"You are checking in from outside the office location. "
					"Check-in is only allowed if you have applied for Work From Home for this date. "
					"Please submit a Work From Home request for {0} first."
				).format(checkin_date),
				exc=CheckinRadiusExceededError,
			)

		# OUT: require reason when checking out from outside office
		reason = (self.get("checkout_reason") or "").strip()
		if not reason:
			frappe.throw(
				_(
					"You are checking out from outside the office location. "
					"Please provide a reason for checking out."
				),
				exc=CheckinRadiusExceededError,
			)


def patch_mark_attendance_and_link_log():
	"""Public hook for boot_session: ensure patch is applied."""
	_apply_checkout_reason_patch()


# Apply patch when this module is loaded so HRMS callers get the patched function
_apply_checkout_reason_patch()
