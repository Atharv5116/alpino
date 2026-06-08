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
		# SECURITY: Validate that the checkin time is not in the future
		# This prevents backdoor creation of future-dated checkins
		from frappe.utils import now_datetime
		checkin_time = get_datetime(self.time)
		current_time = now_datetime()
		
		if checkin_time > current_time:
			# Allow Administrator to create future checkins (for testing/debugging)
			if frappe.session.user != "Administrator":
				frappe.throw(
					_("Cannot create check-in records for future dates. Check-in time: {0}, Current time: {1}").format(
						checkin_time, current_time
					),
					title=_("Future Date Not Allowed")
				)
		
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

		# Action Logging - User-friendly format
		try:
			# Determine source in clear language
			if self.get('device_id'):
				source = f"Biometric Device ({self.get('device_id')})"
				source_type = "Biometric Sync"
			elif self.get('from_attendance_request'):
				source = "Attendance Request Dialog"
				source_type = "Attendance Request"
			elif is_widget_call or has_geo:
				source = "Home Dashboard Widget (Employee Self Check-in)"
				source_type = "Dashboard Widget"
			elif is_manual_ui:
				source = "Manual Entry by Administrator"
				source_type = "Manual"
			else:
				source = "Unknown Source"
				source_type = "Unknown"
			
			# Create user-friendly log message
			log_details = f"SOURCE: {source}\n"
			log_details += f"CHECKIN TIME: {self.time}\n"
			log_details += f"TYPE: {self.log_type}\n"
			log_details += f"CREATED BY: {frappe.session.user}\n"
			
			# Add attendance request reference if available
			if self.get('attendance'):
				att_doc = frappe.db.get_value('Attendance', self.get('attendance'), 
					['attendance_request', 'attendance_date'], as_dict=True)
				if att_doc and att_doc.attendance_request:
					log_details += f"ATTENDANCE REQUEST: {att_doc.attendance_request}\n"
					log_details += f"REQUEST DATE: {att_doc.attendance_date}\n"
			
			# Add location info if from widget
			if has_geo:
				log_details += f"LOCATION: Lat {self.get('latitude')}, Lon {self.get('longitude')}\n"
			
			log_details += f"\n--- Technical Details ---\n"
			log_details += f"IP Address: {request_ip}\n"
			log_details += f"Request Path: {request_path}"
			
			frappe.get_doc({
				"doctype": "Employee Checkin Log",
				"employee": self.employee,
				"user": frappe.session.user,
				"action": source_type,
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
			wfh = frappe.db.get_value(
				"Work From Home Request",
				{
					"employee": self.employee,
					"date": checkin_date,
					"status": ["in", ["Draft", "Approved", "Live"]],
				},
				["name", "half_day", "custom_half_day_period"],
				as_dict=True,
			)
			if wfh:
				# Full-day WFH: outside check-in allowed all day. Half-day WFH: the outside
				# check-in must fall within the covered half (the "leverage" is only for that half).
				if not wfh.half_day or self._checkin_within_wfh_half(checkin_date, wfh.custom_half_day_period):
					return
				frappe.throw(
					_(
						"Your Work From Home for {0} is a half-day ({1}). Check-in from outside the "
						"office is only allowed during that half — this check-in at {2} is outside it."
					).format(
						checkin_date,
						wfh.custom_half_day_period or _("half day"),
						get_datetime(self.time).strftime("%H:%M"),
					),
					exc=CheckinRadiusExceededError,
				)
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

	def _checkin_within_wfh_half(self, date, period):
		"""For a half-day WFH, is this check-IN within the covered half?

		The day is split at the shift midpoint: First Half = shift start..midpoint, Second Half =
		midpoint..shift end. Fail-open (allow) when the period is unknown or the shift/midpoint
		can't be resolved, so a legitimate check-in is never blocked for lack of data.
		"""
		if not period:
			return True
		from alpinos.attendance_request_automation import get_assigned_shift_times

		start, end = get_assigned_shift_times(self.employee, date, self.shift)
		if not start or not end or end <= start:
			return True
		midpoint = start + (end - start) / 2
		t = get_datetime(self.time)
		if period == "Second Half":
			return t >= midpoint
		return t <= midpoint  # First Half (default)


def patch_mark_attendance_and_link_log(bootinfo=None):
	"""Public hook for boot_session: ensure patch is applied. Frappe calls boot hooks with bootinfo."""
	_apply_checkout_reason_patch()


# Apply patch when this module is loaded so HRMS callers get the patched function
_apply_checkout_reason_patch()
