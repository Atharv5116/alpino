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
		"""
		Override to populate custom fields in Attendance when created/updated from Attendance Request
		"""
		# #region agent log
		import json
		explanation_preview = (getattr(self, 'explanation', '') or '')[:30]
		log_data = {
			"id": f"log_override_start_{frappe.utils.now_datetime().timestamp()}",
			"timestamp": int(frappe.utils.now_datetime().timestamp() * 1000),
			"location": "attendance_request_override.py:47",
			"message": "create_or_update_attendance override called",
			"data": {
				"attendance_request": self.name,
				"date": date,
				"explanation": getattr(self, 'explanation', None),
				"explanation_preview": explanation_preview,
				"explanation_length": len(getattr(self, 'explanation', '') or ''),
				"runId": "initial_debug",
				"hypothesisId": "K"
			}
		}
		try:
			with open('/home/hetvi/frappe-bench/.cursor/debug.log', 'a') as f:
				f.write(json.dumps(log_data) + '\n')
		except:
			pass
		# #endregion
		
		# Log that override is being called (short message)
		frappe.log_error(
			f"Override called: {self.name}, date: {date}, exp: {explanation_preview}",
			"AR Override"
		)
		
		doc = self.get_attendance_doc(date)
		status = self.get_attendance_status(date)
		
		if doc:
			# #region agent log
			log_data = {
				"id": f"log_override_existing_{frappe.utils.now_datetime().timestamp()}",
				"timestamp": int(frappe.utils.now_datetime().timestamp() * 1000),
				"location": "attendance_request_override.py:61",
				"message": "create_or_update_attendance: updating existing attendance",
				"data": {
					"attendance_name": doc.name,
					"attendance_request": getattr(doc, 'attendance_request', None),
					"runId": "initial_debug",
					"hypothesisId": "L"
				}
			}
			try:
				with open('/home/hetvi/frappe-bench/.cursor/debug.log', 'a') as f:
					f.write(json.dumps(log_data) + '\n')
			except:
				pass
			# #endregion
			
			# Update existing attendance
			was_submitted = doc.docstatus == 1
			needs_update = False
			
			# Check if status needs to change
			if doc.status != status:
				needs_update = True
				if was_submitted:
					doc.cancel()
				doc.status = status
			
			# Always update attendance_request
			if doc.attendance_request != self.name:
				needs_update = True
				doc.attendance_request = self.name
			
			# If anything changed, save and resubmit if needed
			if needs_update:
				doc.save(ignore_permissions=True)
				if was_submitted and doc.docstatus == 0:
					doc.submit()
				frappe.msgprint(
					_("Attendance updated for {0}").format(
						frappe.bold(frappe.utils.formatdate(date))
					),
					title=_("Attendance Updated"),
				)
			
			# Sync attendance_request_reason using core function (works for both draft and submitted)
			sync_attendance_request_reason(doc)
		else:
			# #region agent log
			log_data = {
				"id": f"log_override_new_{frappe.utils.now_datetime().timestamp()}",
				"timestamp": int(frappe.utils.now_datetime().timestamp() * 1000),
				"location": "attendance_request_override.py:93",
				"message": "create_or_update_attendance: creating new attendance",
				"data": {
					"attendance_request": self.name,
					"explanation": getattr(self, 'explanation', None),
					"runId": "initial_debug",
					"hypothesisId": "M"
				}
			}
			try:
				with open('/home/hetvi/frappe-bench/.cursor/debug.log', 'a') as f:
					f.write(json.dumps(log_data) + '\n')
			except:
				pass
			# #endregion
			
			# Create new attendance
			doc = frappe.new_doc("Attendance")
			doc.employee = self.employee
			doc.attendance_date = date
			doc.shift = self.shift
			doc.company = self.company
			doc.attendance_request = self.name
			doc.status = status
			doc.half_day_status = "Absent" if status == "Half Day" else None
			
			# #region agent log
			log_data = {
				"id": f"log_override_before_insert_{frappe.utils.now_datetime().timestamp()}",
				"timestamp": int(frappe.utils.now_datetime().timestamp() * 1000),
				"location": "attendance_request_override.py:103",
				"message": "create_or_update_attendance: before insert",
				"data": {
					"attendance_request": doc.attendance_request,
					"explanation_in_request": getattr(self, 'explanation', None),
					"runId": "initial_debug",
					"hypothesisId": "N"
				}
			}
			try:
				with open('/home/hetvi/frappe-bench/.cursor/debug.log', 'a') as f:
					f.write(json.dumps(log_data) + '\n')
			except:
				pass
			# #endregion
			
			doc.insert(ignore_permissions=True)
			# after_insert hook will call sync_attendance_request_reason
			
			# #region agent log
			log_data = {
				"id": f"log_override_after_insert_{frappe.utils.now_datetime().timestamp()}",
				"timestamp": int(frappe.utils.now_datetime().timestamp() * 1000),
				"location": "attendance_request_override.py:106",
				"message": "create_or_update_attendance: after insert",
				"data": {
					"attendance_name": doc.name,
					"attendance_request": doc.attendance_request,
					"runId": "initial_debug",
					"hypothesisId": "O"
				}
			}
			try:
				with open('/home/hetvi/frappe-bench/.cursor/debug.log', 'a') as f:
					f.write(json.dumps(log_data) + '\n')
			except:
				pass
			# #endregion
			
			doc.submit()
			# after_submit hook will call sync_attendance_request_reason

