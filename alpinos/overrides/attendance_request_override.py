"""
Override for Attendance Request doctype to handle all attendance status options
based on the reason field and populate custom fields in Attendance
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, date_diff, formatdate, get_datetime, get_time, getdate, now_datetime
from hrms.hr.doctype.attendance_request.attendance_request import AttendanceRequest as HRMSAttendanceRequest
from alpinos.attendance_request_automation import (
	RESERVED_EDIT_STATES,
	count_attendance_request_edits,
	gather_day_info,
	get_reserved_request_names,
	sync_attendance_request_reason,
)


class CustomAttendanceRequest(HRMSAttendanceRequest):
	"""
	Override Attendance Request to handle all attendance status options
	"""

	def validate(self):
		self._apply_single_day_or_range()   # Rules 3 & 7: single day, On Duty = range
		if self.is_new():
			# Rule 2: only last 7 days — enforced at request creation only, NOT on approval/submit
			# (an approver acting a few days later must not be blocked by the window).
			self._enforce_request_window()
		self._enforce_monthly_limit()        # Rule 1: max 4 per month
		super().validate()
		self._sync_tables()                  # build the Details + Existing Logs tables
		self._clear_unticked_punches()       # blank punches stay blank (no Time auto-now)
		self._validate_detail_times()        # reject mistyped Check-in/Check-out times
		self._set_punch_edit_flag()          # edit (overwrites a recorded punch) vs missing

	def validate_request_overlap(self):
		# Allow multiple requests for the same date — e.g. add the check-in in one request and the
		# check-out in another (each is a separate edit). _upsert_checkin keeps a single IN/OUT per
		# date and the monthly edit limit caps the volume, so the hard hrms overlap block is dropped.
		pass

	def _clear_unticked_punches(self):
		"""A Time field auto-fills a new row with the current time; clear any punch whose Edit
		box is unticked so an unedited check-in/check-out is stored blank, not the auto-now value.
		On Duty rows carry no manual times (the assigned shift is used on approval), so their
		unticked punches are blanked here too."""
		for row in (self.custom_attendance_details or []):
			if not row.get("edit_check_in"):
				row.check_in = None
			if not row.get("edit_check_out"):
				row.check_out = None

	def _set_punch_edit_flag(self):
		"""Decide EDIT vs MISSING for the approval workflow's Reporting-Manager branch.

		An EDIT *overwrites a punch that is already on record*: a ticked Edit Check-in /
		Edit Check-out whose side the Existing Logs snapshot already holds a value for. A
		request that only fills a genuinely-missing side stays MISSING — even on a day that
		already has the OTHER side punched (e.g. adding a missing check-out to a day whose
		check-in came from the device). MISSING is approved by the Reporting Manager alone;
		EDIT additionally needs HR Manager approval.

		On Duty carries no ticked punch edits (its times come from the assigned shift on
		approval), so it is never an edit here — it stays a Reporting-Manager-only approval.
		"""
		existing = {
			getdate(r.attendance_date): r
			for r in (self.custom_existing_logs or [])
			if r.attendance_date
		}
		is_edit = False
		for row in (self.custom_attendance_details or []):
			if not row.attendance_date:
				continue
			snap = existing.get(getdate(row.attendance_date))
			if not snap:
				continue
			if (row.get("edit_check_in") and snap.check_in) or (
				row.get("edit_check_out") and snap.check_out
			):
				is_edit = True
				break
		self.custom_is_punch_edit = 1 if is_edit else 0

	def on_submit(self):
		# Rule 4: check-in / attendance are changed ONLY on approval (= submit).
		self._apply_requested_checkins()
		super().on_submit()
		# Sync in/out/working-hours onto the Attendance from the (now applied) check-ins.
		# This runs last and reads ALL check-ins (no skip_auto_attendance filter), so the
		# requested punches always land as In Time / Out Time on the Attendance.
		self._refresh_attendance_times()

	def _refresh_attendance_times(self):
		from alpinos.attendance_request_automation import update_attendance_times

		start = getdate(self.from_date)
		end = getdate(self.to_date)
		if end < start:
			end = start
		d = start
		guard = 0
		while d <= end and guard < 366:
			try:
				update_attendance_times(self.employee, d)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "AR refresh attendance times")
			d = add_days(d, 1)
			guard += 1

	def validate_no_attendance_to_create(self):
		# Rule 6: allow the request even when attendance already exists with the same
		# status (e.g. already Present). We still re-apply the requested check-ins and
		# update in/out/working hours on approval (see create_or_update_attendance), so
		# we never block submission here the way standard HRMS does.
		pass

	def _is_hr_manager(self):
		"""Rules 1 & 2 don't apply to HR Managers. Check the request's EMPLOYEE's roles
		(via their user), NOT the session user — otherwise an admin or an impersonated
		session (which carries the HR Manager role) would bypass the limits for everyone.
		"""
		user = frappe.db.get_value("Employee", self.employee, "user_id") if self.employee else None
		return bool(user) and "HR Manager" in frappe.get_roles(user)

	# ----- Rules 3 & 7: single-day unless the reason is On Duty -----
	def _apply_single_day_or_range(self):
		if self.reason == "On Duty":
			# Range mode — use the standard From/To as entered.
			if self.from_date and not self.to_date:
				self.to_date = self.from_date
			return
		# Single-day mode — driven by the custom single Date field.
		single = self.get("custom_request_date") or self.from_date
		if not single:
			frappe.throw(_("Please set the Date for this request."), title=_("Date Required"))
		self.custom_request_date = single
		self.from_date = single
		self.to_date = single

	# ----- Rule 2: only the last 7 days (On Duty and HR Manager exempt) -----
	def _enforce_request_window(self):
		# On Duty is a duty assignment, not a missing-punch edit — no date window at all.
		if self.reason == "On Duty":
			return
		if self._is_hr_manager():
			return
		today = getdate(now_datetime())
		earliest = add_days(today, -7)
		start = getdate(self.from_date)
		end = getdate(self.to_date)
		if start > today or end > today:
			frappe.throw(_("Attendance Request cannot be for a future date."), title=_("Invalid Date"))
		if start < earliest:
			frappe.throw(
				_("Attendance Request can only be raised for the last 7 days (on or after {0}).").format(
					formatdate(earliest)
				),
				title=_("Date Too Old"),
			)

	# ----- Rule 1: at most 4 punch EDITS per calendar month (HR Manager exempt) -----
	# Each check-in or check-out the employee fills counts as one edit, so a single request
	# that sets both a check-in and a check-out uses 2 of the 4 monthly edits.
	def _punch_edits_in_details(self):
		"""Edits in THIS request: number of ticked Edit Check-in / Edit Check-out boxes.
		On Duty specifies duty times (a whole range, blank = assigned shift), not missing-punch
		edits, so it never counts toward the monthly limit."""
		if self.reason == "On Duty":
			return 0
		n = 0
		for row in (self.custom_attendance_details or []):
			if row.get("edit_check_in"):
				n += 1
			if row.get("edit_check_out"):
				n += 1
		return n

	def _enforce_monthly_limit(self):
		# On Duty never consumes the monthly edit balance.
		if self.reason == "On Duty":
			return
		if self._is_hr_manager():
			return
		# The count is reserved only when the request is sent for approval (or approved); while
		# it is still a Draft (being prepared) or has been Rejected it consumes nothing. So only
		# enforce once it enters a reserved state. (No workflow_state -> legacy/no workflow -> enforce.)
		state = self.get("workflow_state")
		if state and state not in RESERVED_EDIT_STATES:
			return
		month_start = getdate(self.from_date).replace(day=1)
		next_month = add_months(month_start, 1)

		# Edits already reserved this month by the employee's other requests.
		others = get_reserved_request_names(self.employee, month_start, next_month, self.name)
		used = count_attendance_request_edits(others)
		current = self._punch_edits_in_details()
		if used + current > 4:
			frappe.throw(
				_(
					"Limit reached: at most 4 check-in/check-out edits per month. "
					"{0} already used in {1} and this request adds {2}."
				).format(used, formatdate(month_start, "MMMM yyyy"), current),
				title=_("Monthly Edit Limit Reached"),
			)

	# ----- Build/refresh the two tables (Details + Existing Logs) for the date range -----
	def _sync_tables(self):
		start = getdate(self.from_date)
		end = getdate(self.to_date)
		if end < start:
			end = start

		dates = []
		d = start
		guard = 0
		while d <= end and guard < 366:
			dates.append(d)
			d = add_days(d, 1)
			guard += 1
		date_set = set(dates)

		# Editable Check-in/Check-out Details — keep the times the user entered.
		kept = [
			r
			for r in (self.custom_attendance_details or [])
			if r.attendance_date and getdate(r.attendance_date) in date_set
		]
		self.custom_attendance_details = kept
		by_date = {getdate(r.attendance_date): r for r in kept}

		# Read-only Existing Check-in Logs — snapshot the OLD punches ONCE per date and then
		# preserve them, so the old -> new transition stays on record (the request applies
		# new check-ins on approval; the old values must NOT be overwritten here).
		kept_logs = [
			r
			for r in (self.custom_existing_logs or [])
			if r.attendance_date and getdate(r.attendance_date) in date_set
		]
		self.custom_existing_logs = kept_logs
		logged_dates = {getdate(r.attendance_date) for r in kept_logs}

		for dt_ in dates:
			info = gather_day_info(self.employee, dt_)

			row = by_date.get(dt_)
			if not row:
				row = self.append("custom_attendance_details", {"attendance_date": dt_})
				# A new child row's Time fields auto-fill with the current time; blank them so an
				# unedited punch starts empty (not a stray "now" value).
				row.check_in = None
				row.check_out = None
			row.attendance_status = info["status"]

			# Only capture a date's existing log the first time; never overwrite it.
			if dt_ not in logged_dates:
				self.append(
					"custom_existing_logs",
					{
						"attendance_date": dt_,
						"check_in": info["old_in_time"],
						"check_out": info["old_out_time"],
					},
				)

	@staticmethod
	def _time_on_date(date, t):
		"""Combine a date with a time-of-day so the punch lands on that date.

		`check_in`/`check_out` are Time fields, which come through as a timedelta (or time/
		datetime); older records may hold typed text. Handle all. Blank/unparseable -> None.
		"""
		if t in (None, ""):
			return None
		import datetime as _dt
		d = getdate(date)
		if isinstance(t, _dt.datetime):
			return get_datetime(_dt.datetime.combine(d, t.time()))
		if isinstance(t, _dt.timedelta):
			return get_datetime(_dt.datetime.combine(d, _dt.time()) + t)
		if isinstance(t, _dt.time):
			return get_datetime(_dt.datetime.combine(d, t))
		try:
			return get_datetime(f"{d} {get_time(t)}")
		except Exception:
			return None

	def _validate_detail_times(self):
		"""Reject a ticked Check-in/Check-out whose time can't be parsed (unticked rows ignored)."""
		for row in (self.custom_attendance_details or []):
			for fieldname, label, box in (
				("check_in", "Check-in", "edit_check_in"),
				("check_out", "Check-out", "edit_check_out"),
			):
				if not row.get(box):
					continue
				val = row.get(fieldname)
				if val and self._time_on_date(row.attendance_date or getdate(), val) is None:
					frappe.throw(
						_("{0} time '{1}' for {2} is not valid. Use 24-hour HH:MM (e.g. 09:00).").format(
							label, val, frappe.utils.formatdate(row.attendance_date)
						),
						title=_("Invalid Time"),
					)

	# ----- Rule 4: apply the requested punches on approval (submit) -----
	def _apply_requested_checkins(self):
		from alpinos.attendance_request_automation import get_assigned_shift_times

		on_duty = self.reason == "On Duty"
		for row in (self.custom_attendance_details or []):
			if not row.attendance_date:
				continue
			if on_duty:
				# On Duty always uses the employee's assigned shift start/end for each date —
				# there is no manual check-in/check-out entry.
				in_dt, out_dt = get_assigned_shift_times(self.employee, row.attendance_date, self.shift)
			else:
				# Only a ticked 'Edit' box is a real punch. An unticked Time field may carry the
				# auto-now default, so it must be ignored.
				in_dt = self._time_on_date(row.attendance_date, row.check_in) if row.get("edit_check_in") else None
				out_dt = self._time_on_date(row.attendance_date, row.check_out) if row.get("edit_check_out") else None
			if in_dt:
				self._upsert_checkin(row.attendance_date, "IN", in_dt, None)
			if out_dt:
				self._upsert_checkin(row.attendance_date, "OUT", out_dt, None)

	def _upsert_checkin(self, date, log_type, time, checkin_name=None):
		time = get_datetime(time)
		name = checkin_name
		if not name:
			day = getdate(date)
			existing = frappe.get_all(
				"Employee Checkin",
				filters={
					"employee": self.employee,
					"log_type": log_type,
					"time": ["between", [get_datetime(f"{day} 00:00:00"), get_datetime(f"{day} 23:59:59")]],
				},
				pluck="name",
				limit=1,
			)
			name = existing[0] if existing else None

		if name:
			frappe.db.set_value(
				"Employee Checkin",
				name,
				{"time": time, "from_attendance_request": 1, "is_manual": 1},
			)
		else:
			checkin = frappe.new_doc("Employee Checkin")
			checkin.employee = self.employee
			checkin.log_type = log_type
			checkin.time = time
			checkin.from_attendance_request = 1
			checkin.is_manual = 1
			if self.shift:
				checkin.shift = self.shift
			checkin.insert(ignore_permissions=True)

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
				
				# Use the shift's hours-based status (Absent/Half Day/Present) unless the reason is
				# forcing WFH or Half Day. Only a check-in (no check-out) => 0 hours => Absent; the
				# status changes once a check-out is added and the hours are recomputed.
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

		# For a truly-missing Absent day (no check-ins at all): set in_time/out_time from shift so
		# they are visible. When there ARE check-ins (e.g. only a check-in was added), keep the
		# real times — don't backfill the missing check-out from the shift.
		attendance_is_absent = status == "Absent" or (doc and getattr(doc, "status", None) == "Absent")
		shift_for_times = self.shift or (doc and getattr(doc, "shift", None))
		if attendance_is_absent and not logs and (in_time is None or out_time is None) and shift_for_times:
			shift_doc = frappe.get_doc("Shift Type", shift_for_times)
			if in_time is None:
				in_time = get_datetime(f"{date} {shift_doc.start_time}")
			if out_time is None:
				out_time = get_datetime(f"{date} {shift_doc.end_time}")
			if working_hours is None and in_time and out_time:
				working_hours = round((out_time - in_time).total_seconds() / 3600.0, 2)
		
		# An incomplete punch (check-in but no check-out) has zero working hours -> Absent, even
		# when there's no shift / threshold configured (the calc branch never ran). WFH and Half
		# Day keep their own status. Adding the check-out later recomputes the real status.
		is_half_day = bool(self.half_day) and self.half_day_date and date_diff(getdate(self.half_day_date), getdate(date)) == 0
		if in_time and not out_time and self.reason != "Work From Home" and not is_half_day:
			status = "Absent"
		# working_hours is a NOT NULL column; only a check-in (no check-out) leaves it None.
		working_hours = working_hours or 0

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

