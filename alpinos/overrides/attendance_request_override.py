"""
Override for Attendance Request doctype to handle all attendance status options
based on the reason field and populate custom fields in Attendance
"""

import frappe
from frappe import _
from frappe.utils import getdate, date_diff
from hrms.hr.doctype.attendance_request.attendance_request import AttendanceRequest as HRMSAttendanceRequest
from alpinos.attendance_request_automation import sync_attendance_request_reason


class CustomAttendanceRequest(HRMSAttendanceRequest):
	"""
	Override Attendance Request to handle all attendance status options
	"""
	
	def get_attendance_status(self, attendance_date: str) -> str:
		"""
		Override get_attendance_status to handle all status options based on reason field.
		Original method only handled Half Day and Work From Home.
		"""
		# Check for Half Day first (if half_day flag is set and date matches)
		if self.half_day and date_diff(getdate(self.half_day_date), getdate(attendance_date)) == 0:
			return "Half Day"
		
		# Check reason field for status options
		if self.reason:
			# Map reason to attendance status
			reason_to_status = {
				"Work From Home": "Work From Home",
				"Office": "Present",
				"On Duty": "Present",
				"Other": "Present"
			}
			
			# If reason matches a valid option, return the mapped status
			if self.reason in reason_to_status:
				return reason_to_status[self.reason]
		
		# Fallback to original logic for backward compatibility
		if self.reason == "Work From Home":
			return "Work From Home"
		
		# Default to Present if no match (Office, Other, or empty)
		return "Present"
	
	def create_or_update_attendance(self, date: str):
		doc = self.get_attendance_doc(date)
		status = self.get_attendance_status(date)
		
		from frappe.utils import get_datetime
		date_start = get_datetime(f"{date} 00:00:00")
		date_end = get_datetime(f"{date} 23:59:59")
		
		# Fetch check-in logs for calculation
		logs = frappe.get_all(
			"Employee Checkin",
			filters={
				"employee": self.employee,
				"time": ["between", [date_start, date_end]],
				"skip_auto_attendance": 0
			},
			order_by="time asc",
			fields=["name", "time", "log_type", "shift_start", "shift_end"]
		)
		
		in_time = out_time = working_hours = None
		late_entry = early_exit = False
		
		# Use Shift Type to calculate bounds if applicable
		if self.shift:
			shift_doc = frappe.get_doc("Shift Type", self.shift)
			if logs:
				# ensure logs have shift boundaries for hr calculation
				for log in logs:
					if not log.shift_start:
						log.shift_start = get_datetime(f"{date} {shift_doc.start_time}")
					if not log.shift_end:
						log.shift_end = get_datetime(f"{date} {shift_doc.end_time}")
				
				# Auto-calculate based on HRMS config (Absent, Half Day, Present bounds)
				calc_status, working_hours, late_entry, early_exit, in_time, out_time = shift_doc.get_attendance(logs)
				
				# Only allow the calculated status to override if reason isn't forcing WFH or Half Day
				if self.reason != "Work From Home" and not (self.half_day and frappe.utils.date_diff(frappe.utils.getdate(self.half_day_date), frappe.utils.getdate(date)) == 0):
					status = calc_status
		else:
			# Fallback if no shift
			in_log = next((l for l in logs if l.log_type == "IN"), None)
			out_log = [l for l in logs if l.log_type == "OUT"]
			out_log = out_log[-1] if out_log else None
			in_time = in_log.time if in_log else None
			out_time = out_log.time if out_log else None
			if in_time and out_time:
				working_hours = round((out_time - in_time).total_seconds() / 3600.0, 2)

		# When we have logs but in_time/out_time are still None (e.g. status Absent from shift calc), use first IN / last OUT
		if logs and (in_time is None or out_time is None):
			in_log = next((l for l in logs if l.log_type == "IN"), None)
			out_log_list = [l for l in logs if l.log_type == "OUT"]
			out_log = out_log_list[-1] if out_log_list else None
			if in_time is None and in_log:
				in_time = in_log.time
			if out_time is None and out_log:
				out_time = out_log.time
			if in_time and out_time and working_hours is None:
				working_hours = round((out_time - in_time).total_seconds() / 3600.0, 2)

		# For Absent (or existing doc already Absent e.g. from workflow): set in_time/out_time from shift when missing so they are visible
		attendance_is_absent = status == "Absent" or (doc and getattr(doc, "status", None) == "Absent")
		shift_for_times = self.shift or (doc and getattr(doc, "shift", None))
		if attendance_is_absent and (in_time is None or out_time is None) and shift_for_times:
			shift_doc = frappe.get_doc("Shift Type", shift_for_times)
			if in_time is None:
				in_time = get_datetime(f"{date} {shift_doc.start_time}")
			if out_time is None:
				out_time = get_datetime(f"{date} {shift_doc.end_time}")
			if working_hours is None and in_time and out_time:
				working_hours = round((out_time - in_time).total_seconds() / 3600.0, 2)
		
		if doc:
			was_submitted = doc.docstatus == 1
			needs_update = False
			updates = {}
			
			if doc.status != status:
				doc.status = status
				updates["status"] = status
				needs_update = True
			if doc.attendance_request != self.name:
				doc.attendance_request = self.name
				updates["attendance_request"] = self.name
				needs_update = True
			if doc.in_time != in_time:
				doc.in_time = in_time
				updates["in_time"] = in_time
				needs_update = True
			if doc.out_time != out_time:
				doc.out_time = out_time
				updates["out_time"] = out_time
				needs_update = True
			if doc.working_hours != working_hours:
				doc.working_hours = working_hours
				updates["working_hours"] = working_hours
				needs_update = True
				
			if needs_update:
				if was_submitted:
					# db_set injects directly into db safely
					frappe.db.set_value("Attendance", doc.name, updates)
					frappe.db.commit()
				else:
					doc.save(ignore_permissions=True)
					
				frappe.msgprint(
					_("Attendance updated for {0}").format(frappe.bold(frappe.utils.formatdate(date))),
					title=_("Attendance Updated"),
				)
			
			sync_attendance_request_reason(doc)
		else:
			# Create new attendance document
			doc = frappe.new_doc("Attendance")
			doc.employee = self.employee
			doc.attendance_date = date
			doc.shift = self.shift
			doc.company = self.company
			doc.attendance_request = self.name
			doc.status = status
			doc.in_time = in_time
			doc.out_time = out_time
			doc.working_hours = working_hours
			doc.late_entry = late_entry
			doc.early_exit = early_exit
			doc.half_day_status = "Absent" if status == "Half Day" else None
			
			doc.insert(ignore_permissions=True)
			doc.submit()
			
			# Ensure Employee Checkins are linked securely to the newly created Attendance doc!
			if logs:
				log_names = [l.name for l in logs]
				frappe.db.sql("UPDATE `tabEmployee Checkin` SET attendance = %s WHERE name IN %s", (doc.name, tuple(log_names)))
				frappe.db.commit()

