"""Attendance Request automation: manage check-in/check-out times."""
import frappe
from frappe import _
from frappe.utils import add_days, add_months, date_diff, formatdate, get_datetime, getdate


def set_reporting_person(doc, method=None):
	if not doc or not getattr(doc, "employee", None):
		return
	if not getattr(doc, "meta", None) or not doc.meta.has_field("reporting_person"):
		return

	reports_to_emp = frappe.db.get_value("Employee", doc.employee, "reports_to")
	if not reports_to_emp:
		doc.reporting_person = None
		return

	manager_user = frappe.db.get_value("Employee", reports_to_emp, "user_id")
	doc.reporting_person = manager_user or None


@frappe.whitelist()
def get_checkin_data_for_dates(employee, from_date, to_date):
	"""Employee Checkin IN/OUT + attendance for every date in the range, keyed by date."""
	if not employee or not from_date or not to_date:
		return {}

	from_date_obj = getdate(from_date)
	to_date_obj = getdate(to_date)

	request_days = date_diff(to_date_obj, from_date_obj) + 1
	dates_in_range = []
	for day in range(request_days):
		attendance_date = add_days(from_date_obj, day)
		dates_in_range.append(attendance_date)

	result = {}
	for date in dates_in_range:
		result[str(date)] = {
			"check_in": None,
			"check_out": None,
			"attendance": None
		}

	start_datetime = get_datetime(f"{from_date} 00:00:00")
	end_datetime = get_datetime(f"{to_date} 23:59:59")

	checkins = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [start_datetime, end_datetime]]
		},
		fields=["name", "log_type", "time", "attendance"],
		order_by="time asc"
	)

	for checkin in checkins:
		checkin_date = getdate(checkin.time)
		date_str = str(checkin_date)
		
		if date_str in result:
			if checkin.log_type == "IN":
				result[date_str]["check_in"] = {
					"name": checkin.name,
					"time": str(checkin.time)
				}
			elif checkin.log_type == "OUT":
				result[date_str]["check_out"] = {
					"name": checkin.name,
					"time": str(checkin.time)
				}
	
	attendance_records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": ["!=", 2]  # Exclude cancelled
		},
		fields=["name", "attendance_date", "status", "docstatus", "in_time", "out_time"]
	)

	for att in attendance_records:
		date_str = str(att.attendance_date)
		if date_str in result:
			result[date_str]["attendance"] = {
				"name": att.name,
				"status": att.status,
				"docstatus": att.docstatus,
				"in_time": str(att.in_time) if att.in_time else None,
				"out_time": str(att.out_time) if att.out_time else None
			}
	
	return result


@frappe.whitelist()
def create_or_update_checkin(employee, date, log_type, time, checkin_name=None, attendance_request=None):
	"""Create a new Employee Checkin or update an existing one."""

	# Reject future-dated check-ins.
	checkin_datetime = get_datetime(time)
	current_datetime = get_datetime()

	if checkin_datetime > current_datetime:
		frappe.throw(
			_("Cannot create check-in records for future dates. Check-in time: {0}, Current time: {1}").format(
				checkin_datetime, current_datetime
			),
			title=_("Future Date Not Allowed")
		)
	
	# Non-admins can't backdate check-ins more than 30 days.
	if frappe.session.user != "Administrator":
		days_diff = date_diff(current_datetime, checkin_datetime)
		if days_diff > 30:
			frappe.throw(
				_("Cannot create check-in records more than 30 days in the past. Please contact HR for assistance."),
				title=_("Date Too Old")
			)
	
	try:
		request_ip = getattr(frappe.request, "remote_addr", "") if getattr(frappe, "request", None) else ""
		request_path = getattr(frappe.request, "path", "") if getattr(frappe, "request", None) else ""
		
		# Use the passed attendance_request, else look it up from the attendance record.
		attendance_request_ref = attendance_request
		if not attendance_request_ref and attendance_name:
			attendance_request_ref = frappe.db.get_value('Attendance', attendance_name, 'attendance_request')
		
		btn_log = f"SOURCE: Attendance Request Dialog\n"
		btn_log += f"CHECKIN TIME: {time}\n"
		btn_log += f"TYPE: {log_type}\n"
		btn_log += f"CREATED BY: {frappe.session.user}\n"
		if attendance_request_ref:
			btn_log += f"ATTENDANCE REQUEST: {attendance_request_ref}\n"
		btn_log += f"REQUEST DATE: {date}\n"
		btn_log += f"ACTION: {'Update Existing' if checkin_name else 'Create New'}\n"
		if checkin_name:
			btn_log += f"CHECKIN ID: {checkin_name}\n"
		btn_log += f"\n--- Technical Details ---\n"
		btn_log += f"IP Address: {request_ip}\n"
		btn_log += f"Request Path: {request_path}"
		
		frappe.get_doc({
			"doctype": "Employee Checkin Log",
			"employee": employee,
			"user": frappe.session.user,
			"action": "Attendance Request",
			"log_type": log_type,
			"details": btn_log,
			"ip_address": request_ip,
			"request_path": request_path
		}).insert(ignore_permissions=True)
	except Exception:
		pass
		
	attendance = get_attendance_for_date(employee, date)
	attendance_name = attendance.get("name") if attendance else None

	if checkin_name:
		new_time = get_datetime(time)
		
		if attendance_name:
			frappe.db.sql(
				"""
				UPDATE `tabEmployee Checkin` 
				SET time = %s, from_attendance_request = 1, attendance = COALESCE(NULLIF(attendance, ''), %s)
				WHERE name = %s
				""", 
				(new_time, attendance_name, checkin_name)
			)
		else:
			frappe.db.sql(
				"""
				UPDATE `tabEmployee Checkin` 
				SET time = %s, from_attendance_request = 1
				WHERE name = %s
				""", 
				(new_time, checkin_name)
			)
			
		frappe.db.commit()

		update_attendance_times(employee, date)

		return {"name": checkin_name, "time": str(new_time)}
	else:
		checkin_doc = frappe.new_doc("Employee Checkin")
		checkin_doc.employee = employee
		checkin_doc.log_type = log_type
		checkin_doc.time = get_datetime(time)
		checkin_doc.from_attendance_request = 1
		if attendance_name:
			checkin_doc.attendance = attendance_name
		checkin_doc.insert(ignore_permissions=True)

		update_attendance_times(employee, date)

		return {"name": checkin_doc.name, "time": str(checkin_doc.time)}


@frappe.whitelist()
def update_attendance_times(employee, date):
	"""Set Attendance in_time/out_time from the day's Employee Checkin records."""
	if not employee or not date:
		return

	attendance = get_attendance_for_date(employee, date)
	if not attendance:
		return

	attendance_doc = frappe.get_doc("Attendance", attendance["name"])

	date_start = get_datetime(f"{date} 00:00:00")
	date_end = get_datetime(f"{date} 23:59:59")

	# First IN checkin
	in_checkins = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [date_start, date_end]],
			"log_type": "IN"
		},
		fields=["name", "time"],
		order_by="time asc",
		limit=1
	)
	
	# Last OUT checkin
	out_checkins = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [date_start, date_end]],
			"log_type": "OUT"
		},
		fields=["name", "time"],
		order_by="time desc",
		limit=1
	)
	
	in_time = in_checkins[0].time if in_checkins else None
	out_time = out_checkins[0].time if out_checkins else None

	needs_update = attendance_doc.in_time != in_time or attendance_doc.out_time != out_time

	if needs_update:
		working_hours = attendance_doc.working_hours
		if in_time and out_time:
			time_diff = out_time - in_time
			working_hours = round(time_diff.total_seconds() / 3600, 2)
			if attendance_doc.working_hours != working_hours:
				needs_update = True

		# Draft can just be saved.
		if attendance_doc.docstatus == 0:
			attendance_doc.in_time = in_time
			attendance_doc.out_time = out_time
			attendance_doc.working_hours = working_hours
			sync_attendance_request_reason(attendance_doc)
			attendance_doc.save(ignore_permissions=True)
		# Submitted: write to the DB directly to avoid a destructive cancel/unlink.
		elif attendance_doc.docstatus == 1:
			update_values = {
				"in_time": in_time,
				"out_time": out_time,
				"working_hours": working_hours,
			}
			# This fast-path bypasses validate, so reconcile the half-day status here too.
			half_day_status = half_day_status_from_threshold(
				attendance_doc.shift,
				attendance_doc.status,
				working_hours,
				bool(attendance_doc.leave_application or attendance_doc.leave_type),
			)
			if half_day_status:
				update_values["half_day_status"] = half_day_status
				update_values["modify_half_day_status"] = 0
			frappe.db.set_value("Attendance", attendance_doc.name, update_values)
			frappe.db.commit()


@frappe.whitelist()
def update_reason_field(attendance_request, reason):
	"""Set the Attendance Request reason field from the dropdown action."""
	if not attendance_request or not reason:
		frappe.throw(_("Attendance Request and reason are required"))
	
	valid_reasons = ["Work From Home", "Office", "On Duty", "Other"]
	if reason not in valid_reasons:
		frappe.throw(_("Reason must be one of: {0}").format(", ".join(valid_reasons)))
	
	try:
		current_reason = frappe.db.get_value("Attendance Request", attendance_request, "reason")
		if current_reason != reason:
			frappe.db.set_value("Attendance Request", attendance_request, "reason", reason, update_modified=False)
			frappe.db.commit()
			return {"success": True, "old_reason": current_reason, "new_reason": reason}
		return {"success": True, "message": "Reason already set", "reason": reason}
	except Exception as e:
		frappe.log_error(
			f"Error updating reason field in Attendance Request {attendance_request} to '{reason}': {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Update Reason Field Error"
		)
		raise


@frappe.whitelist()
def update_attendance_status(employee, date, reason, attendance_request=None):
	"""Update/create the Attendance for the date; status derived from the action value."""
	if not employee or not date or not reason:
		frappe.throw(_("Employee, date, and reason are required"))

	reason_to_status_map = {
		"Work From Home": "Work From Home",
		"Office": "Present",
		"On Duty": "Present",
		"Other": "Present"
	}
	
	if reason not in reason_to_status_map:
		frappe.throw(_("Reason must be one of: Work From Home, Office, On Duty, Other"))
	
	attendance_status = reason_to_status_map[reason]
	
	# The action value is the source of truth for the reason field; write it first.
	if attendance_request:
		try:
			current_reason = frappe.db.get_value("Attendance Request", attendance_request, "reason")
			frappe.log_error(
				f"UPDATE ATTENDANCE STATUS: Requested reason='{reason}', Current reason='{current_reason}', Attendance Request='{attendance_request}'",
				"Update Attendance Status Debug"
			)

			frappe.db.set_value("Attendance Request", attendance_request, "reason", reason, update_modified=False)
			frappe.db.commit()

			# Read it back to confirm.
			updated_reason = frappe.db.get_value("Attendance Request", attendance_request, "reason")
			frappe.log_error(
				f"UPDATE ATTENDANCE STATUS: After update, reason='{updated_reason}' (expected '{reason}')",
				"Update Attendance Status Debug"
			)
			
			if updated_reason != reason:
				frappe.throw(_("Failed to update reason field. Expected '{0}' but got '{1}'. This is a critical error.").format(reason, updated_reason))
		except Exception as e:
			frappe.log_error(
				f"Error updating reason field in Attendance Request {attendance_request} to '{reason}': {str(e)}\nTraceback: {frappe.get_traceback()}",
				"Update Reason Field Error"
			)
			raise
	
	attendance = get_attendance_for_date(employee, date)

	if attendance:
		attendance_doc = frappe.get_doc("Attendance", attendance["name"])

		# Submitted attendance is still editable per requirement.
		if attendance_doc.docstatus == 1:
			updates = {}
			if attendance_request:
				updates["attendance_request"] = attendance_request

			if updates:
				# db_set bypasses cancel/save restrictions.
				frappe.db.set_value("Attendance", attendance_doc.name, updates)
				frappe.db.commit()

			sync_attendance_request_reason(attendance_doc)

			frappe.msgprint(
				_("Attendance Request updated successfully"),
				indicator="green"
			)
		else:
			if attendance_request:
				attendance_doc.attendance_request = attendance_request
			sync_attendance_request_reason(attendance_doc)
			attendance_doc.save(ignore_permissions=True)

		try:
			update_attendance_times(employee, date)
		except Exception:
			# Don't break the flow if time sync fails.
			frappe.log_error(frappe.get_traceback(), "Update Attendance Times (existing)")

		return {
			"name": attendance_doc.name,
			"status": attendance_doc.status,
			"docstatus": attendance_doc.docstatus
		}
	else:
		company = frappe.db.get_value("Employee", employee, "company")
		if not company:
			frappe.throw(_("Employee must have a company assigned"))

		attendance_doc = frappe.new_doc("Attendance")
		attendance_doc.employee = employee
		attendance_doc.attendance_date = date
		attendance_doc.company = company
		attendance_doc.status = attendance_status
		if attendance_request:
			attendance_doc.attendance_request = attendance_request

		if attendance_status == "Half Day":
			attendance_doc.half_day_status = "Absent"

		attendance_doc.insert(ignore_permissions=True)
		attendance_doc.submit()

		try:
			update_attendance_times(employee, date)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Update Attendance Times (new)")
		
		return {
			"name": attendance_doc.name,
			"status": attendance_doc.status,
			"docstatus": attendance_doc.docstatus
		}


@frappe.whitelist()
def get_attendance_for_date(employee, date):
	"""Existing (non-cancelled) Attendance for the date, as a dict, or None."""
	if not employee or not date:
		return None

	attendance = frappe.db.exists(
		"Attendance",
		{
			"employee": employee,
			"attendance_date": date,
			"docstatus": ["!=", 2]  # Exclude cancelled
		}
	)
	
	if attendance:
		attendance_doc = frappe.get_doc("Attendance", attendance)
		return {
			"name": attendance_doc.name,
			"status": attendance_doc.status,
			"docstatus": attendance_doc.docstatus,
			"in_time": str(attendance_doc.in_time) if attendance_doc.in_time else None,
			"out_time": str(attendance_doc.out_time) if attendance_doc.out_time else None
		}
	
	return None


def sync_attendance_request_reason(attendance_doc):
	"""Sync attendance_request_reason from the linked Attendance Request explanation (idempotent)."""
	if not attendance_doc:
		return

	if not hasattr(attendance_doc, 'attendance_request') or not attendance_doc.attendance_request:
		return

	if not attendance_doc.meta.has_field("attendance_request_reason"):
		return

	try:
		explanation = frappe.db.get_value(
			"Attendance Request",
			attendance_doc.attendance_request,
			"explanation"
		)

		explanation = explanation or ""
		current_value = attendance_doc.get("attendance_request_reason") or ""

		if current_value != explanation:
			# db_set so it works for submitted documents.
			frappe.db.set_value(
				"Attendance",
				attendance_doc.name,
				"attendance_request_reason",
				explanation,
				update_modified=False
			)
			frappe.db.commit()

			attendance_doc.attendance_request_reason = explanation
	except Exception as e:
		frappe.log_error(
			f"Error syncing attendance_request_reason: {str(e)}\n"
			f"Attendance: {attendance_doc.name if hasattr(attendance_doc, 'name') else 'New'}\n"
			f"Attendance Request: {attendance_doc.attendance_request}",
			"Sync Attendance Request Reason Error"
		)

def populate_attendance_reason_after_insert(doc, method=None):
	sync_attendance_request_reason(doc)


def populate_attendance_reason_after_submit(doc, method=None):
	sync_attendance_request_reason(doc)


# States in which a request has "reserved" its monthly edit count (sent for approval or
# approved). Draft and Rejected reserve nothing.
RESERVED_EDIT_STATES = ("Pending RM Approval", "Pending HR Approval", "Approved")


def get_reserved_request_names(employee, month_start, next_month, exclude=None):
	"""Names of the month's requests whose edits are reserved against the monthly limit."""
	candidates = frappe.get_all(
		"Attendance Request",
		filters=[
			["employee", "=", employee],
			["docstatus", "<", 2],
			["from_date", ">=", month_start],
			["from_date", "<", next_month],
			["name", "!=", exclude or "new-attendance-request"],
		],
		fields=["name", "workflow_state", "docstatus"],
	)
	names = []
	for c in candidates:
		state = c.get("workflow_state")
		if state:
			if state in RESERVED_EDIT_STATES:
				names.append(c.name)
		elif c.docstatus == 1:  # legacy pre-workflow submitted request
			names.append(c.name)
	return names


def count_attendance_request_edits(parents):
	"""Total punch edits (ticked Edit Check-in / Check-out boxes) across the requests."""
	if not parents:
		return 0
	# On Duty specifies duty times, not missing-punch edits, so exclude those.
	parents = [
		p for p in parents
		if frappe.db.get_value("Attendance Request", p, "reason") != "On Duty"
	]
	if not parents:
		return 0
	total = 0
	for field in ("edit_check_in", "edit_check_out"):
		total += frappe.db.count(
			"Attendance Request Detail",
			filters=[
				["parenttype", "=", "Attendance Request"],
				["parent", "in", parents],
				[field, "=", 1],
			],
		)
	return total


@frappe.whitelist()
def get_monthly_request_status(employee, on_date=None, current=None):
	"""Monthly check-in/check-out edit allowance for the form banner. HR Managers are exempt."""
	if not employee:
		return {}
	on_date = getdate(on_date) if on_date else getdate()
	month_start = on_date.replace(day=1)
	next_month = add_months(month_start, 1)

	user = frappe.db.get_value("Employee", employee, "user_id")
	exempt = bool(user) and "HR Manager" in frappe.get_roles(user)

	others = get_reserved_request_names(employee, month_start, next_month, current)
	used = count_attendance_request_edits(others)
	limit = 4
	return {
		"exempt": exempt,
		"used": used,
		"limit": limit,
		"remaining": max(0, limit - used),
		"month": formatdate(month_start, "MMMM yyyy"),
	}


def create_attendance_request_client_script():
	"""Install the Attendance Request form client script (date toggles + old/new punch grid)."""

	script = """
frappe.ui.form.on('Attendance Request', {
	refresh: function(frm) {
		alp_toggle_date_fields(frm);
		alp_show_ar_remaining(frm);
		alp_normalize_punches(frm);
		// Auto-populate only on a brand-new form; re-opening a saved request must never
		// re-dirty it.
		if (frm.is_new()) {
			alp_populate(frm, false);
		}
	},
	onload: function(frm) {
		alp_toggle_date_fields(frm);
	},
	reason: function(frm) {
		alp_toggle_date_fields(frm);
		alp_sync_single_date(frm);
		alp_populate(frm, true);
	},
	custom_request_date: function(frm) {
		alp_sync_single_date(frm);
		alp_populate(frm, true);
		alp_show_ar_remaining(frm);
	},
	from_date: function(frm) {
		if (frm.doc.reason === 'On Duty') alp_populate(frm, true);
		alp_show_ar_remaining(frm);
	},
	to_date: function(frm) {
		if (frm.doc.reason === 'On Duty') alp_populate(frm, true);
	},
	employee: function(frm) {
		alp_populate(frm, true);
		alp_show_ar_remaining(frm);
	},
	show_attendance_warnings: function() {
		// Suppress the standard HRMS attendance warnings section
	}
});

function alp_toggle_date_fields(frm) {
	var on_duty = frm.doc.reason === 'On Duty';
	frm.toggle_display('from_date', on_duty);
	frm.toggle_display('to_date', on_duty);
	frm.toggle_display('custom_request_date', !on_duty);
	// On Duty always uses the employee's assigned shift start/end per date — there is no manual
	// check-in/check-out, so hide all four punch columns for On Duty.
	var grid = frm.fields_dict.custom_attendance_details && frm.fields_dict.custom_attendance_details.grid;
	if (grid) {
		['edit_check_in', 'check_in', 'edit_check_out', 'check_out'].forEach(function (f) {
			grid.update_docfield_property(f, 'hidden', on_duty ? 1 : 0);
		});
		grid.refresh();
	}
}

function alp_normalize_punches(frm) {
	// The Edit checkbox is the gate: a Check-in/Check-out time only counts when its box is ticked.
	// Frappe's grid shares one column definition across rows, so per-row inline read-only can't be
	// trusted — instead we hard-clear any punch whose Edit box is unticked, so an untouched row (or
	// a Time field's auto-"now" default) is always blank. On Duty enters times directly with no
	// boxes (blank = assigned shift), so skip it.
	if (frm.doc.reason === 'On Duty') return;
	var changed = false;
	(frm.doc.custom_attendance_details || []).forEach(function (row) {
		if (!row.edit_check_in && row.check_in) { row.check_in = null; changed = true; }
		if (!row.edit_check_out && row.check_out) { row.check_out = null; changed = true; }
	});
	if (changed) frm.refresh_field('custom_attendance_details');
}

function alp_sync_single_date(frm) {
	// For non On-Duty requests the single Date drives From/To.
	if (frm.doc.reason !== 'On Duty' && frm.doc.custom_request_date) {
		if (frm.doc.from_date !== frm.doc.custom_request_date) {
			frm.set_value('from_date', frm.doc.custom_request_date);
		}
		if (frm.doc.to_date !== frm.doc.custom_request_date) {
			frm.set_value('to_date', frm.doc.custom_request_date);
		}
	}
}

function alp_populate(frm, force) {
	// Build the two tables for the date range (draft only). 'force' (an explicit
	// reason/date/employee change) rebuilds the editable Details table; otherwise we keep
	// the rows the user is editing and only refresh the read-only Existing Logs + status.
	if (frm.doc.docstatus !== 0) return;
	alp_sync_single_date(frm);
	if (!frm.doc.employee || !frm.doc.from_date || !frm.doc.to_date) return;

	frappe.call({
		method: 'alpinos.attendance_request_automation.build_attendance_request_details',
		args: {
			employee: frm.doc.employee,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
			reason: frm.doc.reason
		},
		callback: function(r) {
			var data = r.message || {};
			var details = data.details || [];
			var logs = data.logs || [];

			// Existing Check-in Logs (read-only) — always rebuilt.
			frm.clear_table('custom_existing_logs');
			logs.forEach(function(row) {
				var c = frm.add_child('custom_existing_logs');
				c.attendance_date = row.attendance_date;
				c.check_in = row.check_in;
				c.check_out = row.check_out;
			});
			frm.refresh_field('custom_existing_logs');

			// Check-in / Check-out Details (editable). On Duty uses the assigned shift and hides
			// these columns, so every row just starts blank and gated.
			var emptyDetails = (frm.doc.custom_attendance_details || []).length === 0;
			if (force || emptyDetails) {
				frm.clear_table('custom_attendance_details');
				details.forEach(function(row) {
					var c = frm.add_child('custom_attendance_details');
					c.attendance_date = row.attendance_date;
					c.attendance_status = row.attendance_status;
					// Clear the Time auto-now defaults so an unedited punch starts blank.
					c.edit_check_in = 0;
					c.edit_check_out = 0;
					c.check_in = null;
					c.check_out = null;
				});
			} else {
				// Keep the user's entered times; only refresh the status per date.
				var statusByDate = {};
				details.forEach(function(row) { statusByDate[row.attendance_date] = row.attendance_status; });
				(frm.doc.custom_attendance_details || []).forEach(function(c) {
					if (statusByDate[c.attendance_date] !== undefined) {
						c.attendance_status = statusByDate[c.attendance_date];
					}
				});
			}
			frm.refresh_field('custom_attendance_details');
			alp_normalize_punches(frm);
		}
	});
}

function alp_show_ar_remaining(frm) {
	// Banner at the top of the form: how many Attendance Requests the employee has left this
	// month (max 4). HR Managers are exempt. Mirrors the server-side monthly-limit check.
	if (!frm.doc.employee) { frm.set_intro(''); return; }
	frappe.call({
		method: 'alpinos.attendance_request_automation.get_monthly_request_status',
		args: {
			employee: frm.doc.employee,
			on_date: frm.doc.custom_request_date || frm.doc.from_date || frappe.datetime.now_date(),
			current: (frm.doc.name && !frm.is_new()) ? frm.doc.name : null
		},
		callback: function(r) {
			// set_intro() appends a new banner each time (it only clears on empty text), so
			// always clear first — this guarantees exactly one banner, never a stack.
			frm.set_intro('');
			var d = r.message;
			if (!d || !d.limit) { return; }
			if (d.exempt) {
				frm.set_intro(__('HR Manager — exempt from the monthly Attendance Request limit.'), 'blue');
				return;
			}
			var color = d.remaining > 1 ? 'green' : (d.remaining === 1 ? 'orange' : 'red');
			frm.set_intro(
				__('Check-in/Check-out edits for {0}: {1} of {2} used, {3} remaining this month.',
				   [d.month, d.used, d.limit, d.remaining]),
				color
			);
		}
	});
}

frappe.ui.form.on('Attendance Request Detail', {
	edit_check_in: function (frm, cdt, cdn) {
		// Unticking clears the CHECK-IN only (never the check-out) so it stays blank.
		if (!locals[cdt][cdn].edit_check_in) frappe.model.set_value(cdt, cdn, 'check_in', null);
	},
	edit_check_out: function (frm, cdt, cdn) {
		// Unticking clears the CHECK-OUT only (the check-in is left untouched).
		if (!locals[cdt][cdn].edit_check_out) frappe.model.set_value(cdt, cdn, 'check_out', null);
	},
	check_in: function (frm, cdt, cdn) {
		// A time only counts when its Edit box is ticked. Drop any value (including the Time
		// field's auto-"now") that lands on an UNticked check-in, so it never shows or applies.
		var row = locals[cdt][cdn];
		if (!row.edit_check_in && row.check_in) frappe.model.set_value(cdt, cdn, 'check_in', null);
	},
	check_out: function (frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (!row.edit_check_out && row.check_out) frappe.model.set_value(cdt, cdn, 'check_out', null);
	}
});

frappe.ui.form.on('Attendance Request', {
	custom_attendance_details_add: function (frm, cdt, cdn) {
		// New row from "Add Row": clear the Time auto-now defaults so it starts blank.
		frappe.model.set_value(cdt, cdn, 'check_in', null);
		frappe.model.set_value(cdt, cdn, 'check_out', null);
	}
});
"""

	try:
		if frappe.db.exists("Client Script", "Attendance Request - Check-in/Check-out Management"):
			client_script = frappe.get_doc("Client Script", "Attendance Request - Check-in/Check-out Management")
			client_script.script = script
			client_script.enabled = 1
			client_script.save(ignore_permissions=True)
			frappe.db.commit()
		else:
			client_script = frappe.get_doc({
				"doctype": "Client Script",
				"name": "Attendance Request - Check-in/Check-out Management",
				"dt": "Attendance Request",
				"view": "Form",
				"enabled": 1,
				"script": script
			})
			client_script.insert(ignore_permissions=True)
			frappe.db.commit()
	except Exception as e:
		frappe.log_error(f"Error creating Attendance Request client script: {str(e)}", "Client Script Creation Error")
		print(f"⚠️  Could not create Attendance Request client script: {str(e)}")


@frappe.whitelist()
def sync_logs_now(serial_numbers=None, category=None):
    from alpinos.essl_sync import sync_essl_logs
    return sync_essl_logs(serial_numbers=serial_numbers, category=category)

def create_employee_checkin_client_script():
    """Create client script to add Sync eSSL Logs button and hide manual Add buttons"""
    script = """
frappe.listview_settings['Employee Checkin'] = {
    refresh: function(listview) {
        // Add Sync Button for System Managers only
        if (frappe.user_roles.includes('System Manager') || frappe.session.user === 'Administrator') {
            listview.page.add_inner_button(__('Sync eSSL Logs'), function() {
                // Load configured devices, then ask which to sync (by category / serial).
                frappe.call({
                    method: 'alpinos.essl_sync.get_essl_devices',
                    callback: function(res) {
                        const devices = (res.message || []);
                        if (!devices.length) {
                            frappe.msgprint(__('No eSSL devices configured. Add them in eSSL Settings first.'));
                            return;
                        }

                        const serial_options = devices.map(function(d) {
                            return { label: d.serial_number + ' (' + (d.category || '-') + ')', value: d.serial_number };
                        });

                        const d = new frappe.ui.Dialog({
                            title: __('Sync eSSL Logs'),
                            fields: [
                                {
                                    fieldname: 'category',
                                    label: __('Category'),
                                    fieldtype: 'Select',
                                    options: ['All', 'HO', 'Warehouse'],
                                    default: 'All',
                                    description: __('Sync devices of this location. Leave on "All" or tick specific serial numbers below.')
                                },
                                { fieldname: 'serial_sb', fieldtype: 'Section Break', label: __('Serial Numbers (optional)') },
                                {
                                    fieldname: 'serial_numbers',
                                    label: __('Serial Numbers'),
                                    fieldtype: 'MultiCheck',
                                    options: serial_options,
                                    description: __('If none are ticked, all serial numbers matching the category above are synced.')
                                }
                            ],
                            primary_action_label: __('Sync'),
                            primary_action: function(values) {
                                d.hide();
                                frappe.dom.freeze(__('Syncing eSSL logs...'));
                                frappe.call({
                                    method: 'alpinos.attendance_request_automation.sync_logs_now',
                                    args: {
                                        category: values.category,
                                        serial_numbers: (values.serial_numbers && values.serial_numbers.length)
                                            ? JSON.stringify(values.serial_numbers) : null
                                    },
                                    callback: function(r) {
                                        frappe.dom.unfreeze();
                                        if (r.message && r.message.status === 'success') {
                                            frappe.msgprint({
                                                title: __('Sync Complete'),
                                                indicator: 'green',
                                                message: __('Total {0} logs synced.', [r.message.total_synced]) +
                                                    '<br><br>' + (r.message.details || []).join('<br>')
                                            });
                                            listview.refresh();
                                        }
                                    },
                                    error: function() {
                                        frappe.dom.unfreeze();
                                    }
                                });
                            }
                        });
                        d.show();
                    }
                });
            });
        }

        // Hide 'Add Employee Checkin' button for non-admins
        if (frappe.session.user !== 'Administrator') {
            listview.page.clear_primary_action();
        }
    }
};

frappe.ui.form.on('Employee Checkin', {
    refresh: function(frm) {
        // Hide 'New' button and disable manual entry for non-admins
        if (frappe.session.user !== 'Administrator') {
            frm.disable_save();
            if (frm.is_new()) {
                frappe.msgprint(__('Manual creation is restricted. Please use the Attendance Request page.'));
            }
        }
    }
});
"""
    script_name = "Employee Checkin - Restrictions and Sync"

    # Rename the old script if it's still around, else create/update by name.
    old_script_name = "Employee Checkin Sync Button"
    if frappe.db.exists("Client Script", old_script_name):
        frappe.db.set_value("Client Script", old_script_name, {
            "name": script_name,
            "script": script
        })
    elif not frappe.db.exists("Client Script", script_name):
        cs = frappe.get_doc({
            "doctype": "Client Script",
            "name": script_name,
            "dt": "Employee Checkin",
            "script": script,
            "enabled": 1,
            "view": "List"
        })
        cs.insert(ignore_permissions=True)
    else:
        frappe.db.set_value("Client Script", script_name, "script", script)
    
    frappe.db.commit()


def validate_saturday_attendance_threshold(doc, method):
	"""Override Saturday attendance status from the Shift Type's Saturday hour thresholds."""
	if doc.docstatus == 2:
		return

	# Don't override leaves or holidays.
	if doc.status in ["On Leave", "Holiday"] or doc.get("leave_application") or doc.get("leave_type"):
		return

	# weekday 5 == Saturday.
	from frappe.utils import getdate, flt
	if getdate(doc.attendance_date).weekday() != 5:
		return

	if not doc.shift:
		return

	# Half-day falls back to the legacy Present threshold.
	half_day_threshold = flt(
		frappe.db.get_value("Shift Type", doc.shift, "saturday_working_hours_threshold_for_half_day")
	)
	absent_threshold = flt(
		frappe.db.get_value("Shift Type", doc.shift, "saturday_working_hours_threshold_for_absent")
	)
	if not half_day_threshold:
		half_day_threshold = flt(
			frappe.db.get_value("Shift Type", doc.shift, "saturday_working_hours_threshold")
		)

	if not (half_day_threshold or absent_threshold):
		return

	# Only override once check-ins have produced working hours; else leave the no-checkin
	# case to HRMS auto-attendance (Absent).
	working_hours = flt(doc.working_hours)
	if working_hours <= 0:
		return

	if absent_threshold:
		# Three-way: below absent -> Absent, below half day -> Half Day, else Present.
		if working_hours < absent_threshold:
			doc.status = "Absent"
		elif half_day_threshold and working_hours < half_day_threshold:
			doc.status = "Half Day"
			doc.half_day_status = "Absent"
		else:
			doc.status = "Present"
	else:
		# Legacy two-way: below the Present threshold -> Absent, else Present.
		if half_day_threshold and working_hours < half_day_threshold:
			doc.status = "Absent"
		else:
			doc.status = "Present"


def half_day_status_from_threshold(shift, status, working_hours, has_leave):
	"""Working half status for a half-day leave: Absent below the shift half-day threshold, else Present."""
	from frappe.utils import flt

	if status != "Half Day" or not has_leave or not shift:
		return None
	if flt(working_hours) <= 0:
		return None
	threshold = flt(
		frappe.db.get_value("Shift Type", shift, "working_hours_threshold_for_half_day")
	)
	if threshold <= 0:
		return None
	return "Absent" if flt(working_hours) < threshold else "Present"


def mark_half_day_absent_below_threshold(doc, method):
	"""Attendance validate hook: set half_day_status for half-day leave attendances."""
	if doc.docstatus == 2:
		return

	has_leave = bool(doc.get("leave_application") or doc.get("leave_type"))
	new_status = half_day_status_from_threshold(
		doc.shift, doc.status, doc.working_hours, has_leave
	)
	if new_status:
		doc.half_day_status = new_status
		# Lock our decision so HRMS's mark_absent_for_half_day_dates won't flip it.
		doc.modify_half_day_status = 0


# Attendance Request per-day detail helpers (old vs new in/out times)

def get_assigned_shift_times(employee, date, ar_shift=None):
	"""Return (in_datetime, out_datetime) for the employee's shift on `date`."""
	if not employee or not date:
		return None, None
	date = getdate(date)

	candidates = []
	if ar_shift:
		candidates.append(ar_shift)

	# The shift already on the attendance keeps created check-ins aligned with it.
	att_shift = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": date, "docstatus": ["<", 2]},
		"shift",
	)
	if att_shift:
		candidates.append(att_shift)

	default_shift = frappe.db.get_value("Employee", employee, "default_shift")
	if default_shift:
		candidates.append(default_shift)

	try:
		from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift

		details = get_employee_shift(
			employee, get_datetime(f"{date} 00:00:00"), consider_default_shift=True
		)
		if details:
			st = details.get("shift_type")
			name = getattr(st, "name", st)  # may be a Shift Type doc or its name
			if name:
				candidates.append(name)
	except Exception:
		pass

	# Direct Shift Assignment lookup covering the date, catching open-ended or expired
	# assignments the helpers above skip (lets a backdated On Duty resolve its shift).
	sa = frappe.get_all(
		"Shift Assignment",
		filters=[
			["employee", "=", employee],
			["docstatus", "=", 1],
			["start_date", "<=", date],
		],
		or_filters=[["end_date", ">=", date], ["end_date", "is", "not set"]],
		fields=["shift_type"],
		order_by="start_date desc",
		limit=1,
	)
	if sa:
		candidates.append(sa[0].shift_type)

	seen = set()
	for shift_type in candidates:
		if not shift_type or shift_type in seen:
			continue
		seen.add(shift_type)
		st = frappe.db.get_value("Shift Type", shift_type, ["start_time", "end_time"], as_dict=True)
		if not st or (st.start_time is None and st.end_time is None):
			continue
		in_dt = get_datetime(f"{date} {st.start_time}") if st.start_time is not None else None
		out_dt = get_datetime(f"{date} {st.end_time}") if st.end_time is not None else None
		return in_dt, out_dt

	return None, None


def gather_day_info(employee, date):
	"""Existing in/out check-ins + names, current attendance status, and default new in/out for one day."""
	date = getdate(date)
	date_start = get_datetime(f"{date} 00:00:00")
	date_end = get_datetime(f"{date} 23:59:59")

	ins = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "log_type": "IN", "time": ["between", [date_start, date_end]]},
		fields=["name", "time"], order_by="time asc", limit=1,
	)
	outs = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "log_type": "OUT", "time": ["between", [date_start, date_end]]},
		fields=["name", "time"], order_by="time desc", limit=1,
	)
	old_in = ins[0].time if ins else None
	old_out = outs[0].time if outs else None

	status = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": date, "docstatus": ["<", 2]},
		"status",
	)

	return {
		"old_in_time": old_in,
		"old_out_time": old_out,
		"old_in_checkin": ins[0].name if ins else None,
		"old_out_checkin": outs[0].name if outs else None,
		"status": status or "",
		# New time starts from the existing punch; a missing punch stays blank (the On Duty
		# shift fallback is applied on submit, not pre-filled here).
		"default_in_time": old_in,
		"default_out_time": old_out,
	}


@frappe.whitelist()
def build_attendance_request_details(employee, from_date, to_date, reason=None):
	"""Read-only rows for the two Attendance Request tables (editable details + existing logs)."""
	if "HR Manager" not in frappe.get_roles():
		employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	if not (employee and from_date and to_date):
		return {"details": [], "logs": []}

	start = getdate(from_date)
	end = getdate(to_date)
	if end < start:
		end = start

	details, logs = [], []
	d = start
	guard = 0  # cap to avoid pathological ranges
	while d <= end and guard < 366:
		info = gather_day_info(employee, d)
		details.append({
			"attendance_date": str(d),
			"attendance_status": info["status"],
		})
		logs.append({
			"attendance_date": str(d),
			"check_in": str(info["old_in_time"]) if info["old_in_time"] else None,
			"check_out": str(info["old_out_time"]) if info["old_out_time"] else None,
		})
		d = add_days(d, 1)
		guard += 1
	return {"details": details, "logs": logs}
