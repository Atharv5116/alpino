"""Attendance Request override: status from reason, custom fields, and the punch-edit rules."""

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
	"""Attendance Request with the Alpinos punch-edit rules."""

	def validate(self):
		self._apply_single_day_or_range()   # Rules 3 & 7: single day, On Duty = range
		if self.is_new():
			# Rule 2: only last 7 days, enforced at creation only (not on approval).
			self._enforce_request_window()
		self._enforce_monthly_limit()        # Rule 1: max 4 per month
		super().validate()
		self._sync_tables()                  # build the Details + Existing Logs tables
		self._clear_unticked_punches()       # blank punches stay blank (no Time auto-now)
		self._validate_detail_times()        # reject mistyped Check-in/Check-out times
		self._enforce_mandatory_punches()    # both punches required unless reason is On Duty
		self._validate_punches_vs_shift()    # Out >= shift start, In <= shift end
		self._set_punch_edit_flag()          # edit (overwrites a recorded punch) vs missing

	def validate_request_overlap(self):
		# Allow multiple requests for the same date (e.g. check-in and check-out separately).
		pass

	def _clear_unticked_punches(self):
		"""Blank any punch whose Edit box is unticked (a Time field auto-fills with the current time)."""
		for row in (self.custom_attendance_details or []):
			if not row.get("edit_check_in"):
				row.check_in = None
			if not row.get("edit_check_out"):
				row.check_out = None

	def _set_punch_edit_flag(self):
		"""Set custom_is_punch_edit: an EDIT overwrites a punch already on record; a missing-side fill stays MISSING."""
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
		# Rule 4: check-ins/attendance change only on approval (submit).
		self._apply_requested_checkins()
		super().on_submit()
		# Sync in/out/working-hours onto the Attendance from the applied check-ins.
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
		# Rule 6: allow the request even when attendance already exists (we re-apply on approval).
		pass

	def _is_hr_manager(self):
		"""True when the request's EMPLOYEE (not the session user) is an HR Manager; Rules 1 & 2 skip them."""
		user = frappe.db.get_value("Employee", self.employee, "user_id") if self.employee else None
		return bool(user) and "HR Manager" in frappe.get_roles(user)

	def _session_is_hr_manager(self):
		"""True when the session user (the person raising the request) is an HR Manager."""
		return "HR Manager" in frappe.get_roles(frappe.session.user)

	# ----- Rules 3 & 7: single-day unless the reason is On Duty -----
	def _apply_single_day_or_range(self):
		if self.reason == "On Duty":
			# Range mode: use the standard From/To.
			if self.from_date and not self.to_date:
				self.to_date = self.from_date
			return
		# Single-day mode from the custom Date field.
		single = self.get("custom_request_date") or self.from_date
		if not single:
			frappe.throw(_("Please set the Date for this request."), title=_("Date Required"))
		self.custom_request_date = single
		self.from_date = single
		self.to_date = single

	# ----- Rule 2: only the last 7 days (On Duty and HR Manager exempt) -----
	def _enforce_request_window(self):
		# On Duty is a duty assignment, not a punch edit; no date window.
		if self.reason == "On Duty":
			return
		# HR Manager exempt (own request or raising for an employee).
		if self._is_hr_manager() or self._session_is_hr_manager():
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
	# Each check-in or check-out filled counts as one edit (both = 2 of the 4).
	def _punch_edits_in_details(self):
		"""Number of ticked Edit Check-in / Edit Check-out boxes in this request (On Duty counts none)."""
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
		# HR Manager is exempt from the monthly cap.
		if self._is_hr_manager() or self._session_is_hr_manager():
			return
		# Only reserved states (sent for approval / approved) consume the balance; Draft/Rejected don't.
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

		# Editable Details: keep the times the user entered.
		kept = [
			r
			for r in (self.custom_attendance_details or [])
			if r.attendance_date and getdate(r.attendance_date) in date_set
		]
		self.custom_attendance_details = kept
		by_date = {getdate(r.attendance_date): r for r in kept}

		# Read-only Existing Logs: snapshot the OLD punches once per date; never overwrite them.
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
				# A new child row's Time fields auto-fill with now; blank them.
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
		"""Combine a date with a time-of-day (Time field arrives as timedelta/time/datetime/text)."""
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

	# ----- Rule: Check-in/out mandatory unless On Duty; punches sane vs the assigned shift -----
	def _enforce_mandatory_punches(self):
		"""At least one of Check-in / Check-out is required per date unless the reason is On Duty.

		Only the missing side usually needs correcting — the other punch is already on record —
		so a request is valid with either time. A row with neither would change nothing.
		"""
		if self.reason == "On Duty":
			return
		for row in (self.custom_attendance_details or []):
			if not row.attendance_date:
				continue
			if not row.get("check_in") and not row.get("check_out"):
				frappe.throw(
					_("Enter a Check-in or a Check-out for {0} — at least one is required when the reason is not On Duty (tick Edit and enter the time).").format(
						formatdate(row.attendance_date)
					),
					title=_("Check-in / Check-out Required"),
				)

	def _validate_punches_vs_shift(self):
		"""Check-out not before shift start, Check-in not after shift end; On Duty and overnight shifts skip."""
		if self.reason == "On Duty":
			return
		from alpinos.attendance_request_automation import get_assigned_shift_times

		for row in (self.custom_attendance_details or []):
			if not row.attendance_date:
				continue
			in_dt = self._time_on_date(row.attendance_date, row.check_in) if row.get("check_in") else None
			out_dt = self._time_on_date(row.attendance_date, row.check_out) if row.get("check_out") else None
			if not in_dt and not out_dt:
				continue
			shift_start, shift_end = get_assigned_shift_times(self.employee, row.attendance_date, self.shift)
			if not shift_start or not shift_end or shift_end < shift_start:
				continue  # no shift resolved, or overnight
			if out_dt and out_dt < shift_start:
				frappe.throw(
					_("Check-out {0} on {1} cannot be before the shift start ({2}).").format(
						get_time(row.check_out), formatdate(row.attendance_date), shift_start.strftime("%H:%M")
					),
					title=_("Invalid Check-out"),
				)
			if in_dt and in_dt > shift_end:
				frappe.throw(
					_("Check-in {0} on {1} cannot be after the shift end ({2}).").format(
						get_time(row.check_in), formatdate(row.attendance_date), shift_end.strftime("%H:%M")
					),
					title=_("Invalid Check-in"),
				)

	# ----- Rule 4: apply the requested punches on approval (submit) -----
	def _apply_requested_checkins(self):
		from alpinos.attendance_request_automation import get_assigned_shift_times

		on_duty = self.reason == "On Duty"
		for row in (self.custom_attendance_details or []):
			if not row.attendance_date:
				continue
			if on_duty:
				# On Duty uses the assigned shift start/end; no manual entry.
				in_dt, out_dt = get_assigned_shift_times(self.employee, row.attendance_date, self.shift)
			else:
				# Only a ticked Edit box is a real punch; an unticked Time field may be the auto-now default.
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
		"""Map the reason field to an attendance status (core handled only Half Day / WFH)."""
		# Half Day first
		if self.half_day and date_diff(getdate(self.half_day_date), getdate(attendance_date)) == 0:
			return "Half Day"

		if self.reason:
			reason_to_status = {
				"Work From Home": "Work From Home",
				"Office": "Present",
				"On Duty": "Present",
				"Other": "Present"
			}

			if self.reason in reason_to_status:
				return reason_to_status[self.reason]

		# Fallback to original logic for backward compatibility
		if self.reason == "Work From Home":
			return "Work From Home"
		
		# Default to Present if no match (Office, Other, or empty)
		return "Present"
	
	def _should_defer_same_day_marking(self, date):
		"""Defer marking a same-day, still-open day (checked in, not out) to avoid a false Absent."""
		if getdate(date) != getdate(now_datetime()):
			return False
		if self.reason in ("Work From Home", "On Duty"):
			return False
		if self.half_day and self.half_day_date and getdate(self.half_day_date) == getdate(date):
			return False
		day = getdate(date)
		has_out = frappe.db.exists(
			"Employee Checkin",
			{
				"employee": self.employee,
				"log_type": "OUT",
				"time": ["between", [get_datetime(f"{day} 00:00:00"), get_datetime(f"{day} 23:59:59")]],
			},
		)
		return not has_out

	def create_or_update_attendance(self, date: str):
		doc = self.get_attendance_doc(date)

		# Defer a same-day, still-open day (checked in, not out) to avoid a false Absent.
		if not doc and self._should_defer_same_day_marking(date):
			frappe.msgprint(
				_(
					"Check-in updated for {0}. Attendance will be marked automatically once the "
					"day completes — it is not marked now because check-out is still pending."
				).format(frappe.bold(frappe.utils.formatdate(date))),
				title=_("Check-in Updated"),
				indicator="blue",
			)
			return

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

				# Use the shift's hours-based status unless the reason forces WFH/Half Day.
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

		# Truly-missing Absent day (no check-ins): set in/out from shift for visibility; keep real times otherwise.
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
		
		# Incomplete punch (check-in, no check-out) = 0 hours = Absent, even with no shift configured.
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
			
			# Link the check-ins to the new Attendance.
			if logs:
				log_names = [l.name for l in logs]
				frappe.db.sql("UPDATE `tabEmployee Checkin` SET attendance = %s WHERE name IN %s", (doc.name, tuple(log_names)))
				frappe.db.commit()

