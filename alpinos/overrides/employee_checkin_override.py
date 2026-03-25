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
from frappe.utils import flt, get_datetime, getdate

_patch_applied = False


def _apply_checkout_reason_patch():
	# Apply once when this module is loaded so HRMS uses patched mark_attendance_and_link_log
	global _patch_applied
	if _patch_applied:
		return
	import hrms.hr.doctype.employee_checkin.employee_checkin as ec_module
	_original = ec_module.mark_attendance_and_link_log

	def _mark_attendance_and_link_log(*args, **kwargs):
		attendance = _original(*args, **kwargs)
		logs = kwargs.get("logs") or (args[0] if args else None)
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
	def validate_time_change(self):
		# Entirely bypass the core ERPNext warning about modifying time on linked checkins!
		# Our custom Attendance module handles syncing values gracefully.
		pass

	def before_insert(self):
		"""
		Restrict manual creation of check-ins.
		Only allow if:
		1. User is Administrator
		2. It comes from the Attendance Request dashboard (from_attendance_request)
		3. It comes from Biometric Device (device_id)
		4. It comes from the Home Dashboard widget (usually has geolocation or specific API path)
		"""
		request_path = ""
		request_ip = ""
		if getattr(frappe, "request", None):
			request_path = getattr(frappe.request, "path", "")
			request_ip = getattr(frappe.request, "remote_addr", "")

		# Check for flags and attributes
		from_automation = self.get("from_attendance_request") or self.get("device_id")
		
		# Check for geolocation (Widget/Mobile usually provides this)
		has_geo = flt(self.latitude) != 0 or flt(self.longitude) != 0

		# Check if request is coming from the standard HRMS dashboard method
		is_widget_call = False
		if "add_log_based_on_employee_field" in request_path:
			is_widget_call = True

		is_manual_ui = False
		if not from_automation and not has_geo and not is_widget_call:
			if frappe.session.user == "Administrator":
				is_manual_ui = True
				self.is_manual = 1
			else:
				frappe.throw(
					_("Manual creation of Employee Checkin is restricted. Please use the Attendance Request page to manage your check-ins."),
					title=_("Restriction Active")
				)

		# Action Logging
		try:
			log_details = f"Action: CREATED\nUser: {frappe.session.user}\nEmployee: {self.employee}\n"
			log_details += f"Time: {self.time}\nLog Type: {self.log_type}\n"
			log_details += f"Is Manual UI: {is_manual_ui}\n"
			log_details += f"From Request/Dialog: {bool(self.get('from_attendance_request'))}\n"
			log_details += f"Device ID: {self.get('device_id') or 'None'}\n"
			log_details += f"Has Geo: {has_geo} (Lat: {self.get('latitude')}, Lon: {self.get('longitude')})\n"
			log_details += f"Is Widget Call: {is_widget_call}\n"
			log_details += f"IP: {request_ip}\nPath: {request_path}"
			frappe.get_doc({
				"doctype": "Employee Checkin Log",
				"employee": self.employee,
				"user": frappe.session.user,
				"action": "CREATED",
				"log_type": self.log_type,
				"details": log_details,
				"ip_address": request_ip,
				"request_path": request_path
			}).insert(ignore_permissions=True)
		except Exception:
			pass
			
	def on_update(self):
		if self.is_new():
			return
		request_path = ""
		request_ip = ""
		if getattr(frappe, "request", None):
			request_path = getattr(frappe.request, "path", "")
			request_ip = getattr(frappe.request, "remote_addr", "")
			
		try:
			log_details = f"Action: UPDATED\nUser: {frappe.session.user}\nEmployee: {self.employee}\n"
			log_details += f"Time: {self.time}\nLog Type: {self.log_type}\n"
			log_details += f"Is Manual: {self.get('is_manual', 0)}\n"
			log_details += f"From Request/Dialog: {bool(self.get('from_attendance_request'))}\n"
			log_details += f"IP: {request_ip}\nPath: {request_path}"
			frappe.get_doc({
				"doctype": "Employee Checkin Log",
				"employee": self.employee,
				"user": frappe.session.user,
				"action": "UPDATED",
				"log_type": self.log_type,
				"details": log_details,
				"ip_address": request_ip,
				"request_path": request_path
			}).insert(ignore_permissions=True)
		except Exception:
			pass
	def _require_checkout_reason_if_outside(self):
		"""Require checkout_reason for OUT when we cannot confirm employee is at office."""
		reason = (self.get("checkout_reason") or "").strip()
		if not reason:
			frappe.throw(
				_(
					"You are checking out from outside the office location. "
					"Please provide a reason for checking out."
				),
				exc=CheckinRadiusExceededError,
			)

	def validate_distance_from_shift_location(self):
		# Skip all location/geo validations when check-in/check-out is from Attendance Request or Biometric Device
		if self.get("from_attendance_request") or self.get("device_id"):
			return
		if not frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking"):
			return

		# Check-in: require lat/long (HRMS default message)
		if not (self.latitude or self.longitude):
			if self.log_type == "OUT":
				# Cannot verify location; require reason when checking out
				self._require_checkout_reason_if_outside()
				return
			frappe.throw(_("Latitude and longitude values are required for checking in."))

		# No shift assignment for this time: skip location validation (still store lat/long)
		if not self.shift:
			return
		# Shift assignment has no Shift Location: skip location validation (still store lat/long)
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
		checkin_radius = flt(checkin_radius)
		if not checkin_radius or checkin_radius <= 0:
			if self.log_type == "OUT":
				self._require_checkout_reason_if_outside()
			return

		# Coerce all coordinates to float to avoid TypeError in distance calculation
		lat_office = flt(latitude)
		long_office = flt(longitude)
		lat_checkin = flt(self.latitude)
		long_checkin = flt(self.longitude)
		distance = get_distance_between_coordinates(
			lat_office, long_office, lat_checkin, long_checkin
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
					"status": ["in", ["Draft", "Approved", "Live"]],
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
		self._require_checkout_reason_if_outside()


def patch_mark_attendance_and_link_log(bootinfo=None):
	"""Public hook for boot_session: ensure patch is applied. Frappe calls boot hooks with bootinfo."""
	_apply_checkout_reason_patch()


# Apply patch when this module is loaded so HRMS callers get the patched function
_apply_checkout_reason_patch()
