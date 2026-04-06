"""
Automation for Attendance Request to manage check-in/check-out times
"""
import frappe
from frappe import _
from frappe.utils import add_days, date_diff, get_datetime, getdate


@frappe.whitelist()
def get_checkin_data_for_dates(employee, from_date, to_date):
	"""
	Fetch Employee Checkin records (IN/OUT) for all dates in range, grouped by date.
	
	Returns:
		{
			"2026-01-15": {
				"check_in": {"name": "EMP-CKIN-...", "time": "2026-01-15 09:00:00"},
				"check_out": {"name": "EMP-CKIN-...", "time": "2026-01-15 18:00:00"},
				"attendance": {"name": "HR-ATT-...", "status": "Present", "docstatus": 1}
			},
			...
		}
	"""
	if not employee or not from_date or not to_date:
		return {}
	
	from_date_obj = getdate(from_date)
	to_date_obj = getdate(to_date)
	
	# Calculate all dates in range
	request_days = date_diff(to_date_obj, from_date_obj) + 1
	dates_in_range = []
	for day in range(request_days):
		attendance_date = add_days(from_date_obj, day)
		dates_in_range.append(attendance_date)
	
	# Initialize result structure
	result = {}
	for date in dates_in_range:
		result[str(date)] = {
			"check_in": None,
			"check_out": None,
			"attendance": None
		}
	
	# Fetch all Employee Checkin records for the date range
	# Get start and end datetime for the range
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
	
	# Group checkins by date
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
	
	# Fetch Attendance records for all dates
	attendance_records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": ["!=", 2]  # Exclude cancelled
		},
		fields=["name", "attendance_date", "status", "docstatus", "in_time", "out_time"]
	)
	
	# Map attendance records to dates
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
	"""
	Create new Employee Checkin or update existing one.
	
	Args:
		employee: Employee ID
		date: Date string (YYYY-MM-DD)
		log_type: "IN" or "OUT"
		time: Datetime string (YYYY-MM-DD HH:MM:SS)
		checkin_name: Optional existing checkin name to update
		attendance_request: Optional Attendance Request reference
	"""
	
	# SECURITY: Validate that the checkin date is not in the future
	checkin_datetime = get_datetime(time)
	current_datetime = get_datetime()
	
	if checkin_datetime > current_datetime:
		frappe.throw(
			_("Cannot create check-in records for future dates. Check-in time: {0}, Current time: {1}").format(
				checkin_datetime, current_datetime
			),
			title=_("Future Date Not Allowed")
		)
	
	# SECURITY: Validate that the checkin date is not more than 30 days in the past
	# (unless user is Administrator)
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
		
		# Use the attendance_request parameter, or try to find it from the attendance record
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
		
	# Get Attendance record for this date to link the checkin
	attendance = get_attendance_for_date(employee, date)
	attendance_name = attendance.get("name") if attendance else None

	if checkin_name:
		# Update existing checkin
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
		
		# Update Attendance in_time and out_time after checkin update
		update_attendance_times(employee, date)
		
		return {"name": checkin_name, "time": str(new_time)}
	else:
		# Create new checkin
		checkin_doc = frappe.new_doc("Employee Checkin")
		checkin_doc.employee = employee
		checkin_doc.log_type = log_type
		checkin_doc.time = get_datetime(time)
		checkin_doc.from_attendance_request = 1
		if attendance_name:
			checkin_doc.attendance = attendance_name
		checkin_doc.insert(ignore_permissions=True)
		
		# Update Attendance in_time and out_time after checkin creation
		update_attendance_times(employee, date)
		
		return {"name": checkin_doc.name, "time": str(checkin_doc.time)}


@frappe.whitelist()
def update_attendance_times(employee, date):
	"""
	Update in_time and out_time in Attendance record based on Employee Checkin records.
	
	Args:
		employee: Employee ID
		date: Date string (YYYY-MM-DD)
	"""
	if not employee or not date:
		return
	
	# Get Attendance record for this date
	attendance = get_attendance_for_date(employee, date)
	if not attendance:
		return
	
	attendance_doc = frappe.get_doc("Attendance", attendance["name"])
	
	# Get date range for the day
	date_start = get_datetime(f"{date} 00:00:00")
	date_end = get_datetime(f"{date} 23:59:59")
	
	# Get first IN checkin
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
	
	# Get last OUT checkin
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
	
	# Update in_time and out_time
	in_time = in_checkins[0].time if in_checkins else None
	out_time = out_checkins[0].time if out_checkins else None
	
	# Only update if values have changed
	needs_update = attendance_doc.in_time != in_time or attendance_doc.out_time != out_time

	if needs_update:
		# Calculate working hours if both times are present
		working_hours = attendance_doc.working_hours
		if in_time and out_time:
			time_diff = out_time - in_time
			working_hours = round(time_diff.total_seconds() / 3600, 2)
			if attendance_doc.working_hours != working_hours:
				needs_update = True

		# If it's a drafted document, we can just save it
		if attendance_doc.docstatus == 0:
			attendance_doc.in_time = in_time
			attendance_doc.out_time = out_time
			attendance_doc.working_hours = working_hours
			sync_attendance_request_reason(attendance_doc)
			attendance_doc.save(ignore_permissions=True)
		# If submitted, forcefully update the database to avoid destructive canceling and unlinking
		elif attendance_doc.docstatus == 1:
			frappe.db.set_value("Attendance", attendance_doc.name, {
				"in_time": in_time,
				"out_time": out_time,
				"working_hours": working_hours
			})
			frappe.db.commit()


@frappe.whitelist()
def update_reason_field(attendance_request, reason):
	"""
	Update the reason field in Attendance Request.
	This is called first to set the reason field from the dropdown action.
	"""
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
	"""
	Update or create Attendance record with the specified status.
	Update the Attendance Request's reason field based on the action (reason parameter).
	The attendance status is derived from the action value, NOT from reading the reason field.
	
	Args:
		employee: Employee ID
		date: Date string (YYYY-MM-DD)
		reason: Action value from dropdown (Work From Home, On Duty) - this becomes the reason field value
		attendance_request: Optional Attendance Request name to link
	"""
	if not employee or not date or not reason:
		frappe.throw(_("Employee, date, and reason are required"))
	
	# Map action (reason) to attendance status
	reason_to_status_map = {
		"Work From Home": "Work From Home",
		"Office": "Present",
		"On Duty": "Present",
		"Other": "Present"
	}
	
	if reason not in reason_to_status_map:
		frappe.throw(_("Reason must be one of: Work From Home, Office, On Duty, Other"))
	
	attendance_status = reason_to_status_map[reason]
	
	# ALWAYS update the reason field FIRST based on the action value
	# The action value (reason parameter) is the source of truth
	if attendance_request:
		try:
			current_reason = frappe.db.get_value("Attendance Request", attendance_request, "reason")
			frappe.log_error(
				f"UPDATE ATTENDANCE STATUS: Requested reason='{reason}', Current reason='{current_reason}', Attendance Request='{attendance_request}'",
				"Update Attendance Status Debug"
			)
			
			# ALWAYS update the reason field to match the action value, even if it's the same
			# This ensures the reason field reflects the action
			frappe.db.set_value("Attendance Request", attendance_request, "reason", reason, update_modified=False)
			frappe.db.commit()
			
			# Verify it was updated - read it back immediately
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
	
	# Get existing attendance
	attendance = get_attendance_for_date(employee, date)
	
	if attendance:
		# Update existing attendance
		attendance_doc = frappe.get_doc("Attendance", attendance["name"])
		
		# Allow updating even if submitted (as per user requirement)
		if attendance_doc.docstatus == 1:
			updates = {}
			if attendance_request:
				updates["attendance_request"] = attendance_request
			
			if updates:
				# Use db_set to bypass cancel and save restrictions
				frappe.db.set_value("Attendance", attendance_doc.name, updates)
				frappe.db.commit()
			
			# Sync attendance_request_reason directly
			sync_attendance_request_reason(attendance_doc)
			
			frappe.msgprint(
				_("Attendance Request updated successfully"),
				indicator="green"
			)
		else:
			# Draft attendance - just update link if needed
			if attendance_request:
				attendance_doc.attendance_request = attendance_request
			# Sync attendance_request_reason using core function
			sync_attendance_request_reason(attendance_doc)
			attendance_doc.save(ignore_permissions=True)
		
		# Ensure in_time / out_time are in sync with check-ins after status/link changes
		try:
			update_attendance_times(employee, date)
		except Exception:
			# Avoid breaking the user flow if time sync fails; errors are logged separately
			frappe.log_error(frappe.get_traceback(), "Update Attendance Times (existing)")
		
		return {
			"name": attendance_doc.name,
			"status": attendance_doc.status,
			"docstatus": attendance_doc.docstatus
		}
	else:
		# Create new attendance
		# Get company from employee
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
		
		# Set half_day_status if Half Day (not applicable for reason-based statuses, but keeping for safety)
		if attendance_status == "Half Day":
			attendance_doc.half_day_status = "Absent"
		
		attendance_doc.insert(ignore_permissions=True)
		# after_insert hook will call sync_attendance_request_reason
		
		attendance_doc.submit()
		# after_submit hook will call sync_attendance_request_reason
		
		# Sync in_time / out_time from check-ins (if any) for newly created attendance
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
	"""
	Get existing Attendance record for a specific date.
	
	Returns:
		{"name": "...", "status": "...", "docstatus": 1} or None
	"""
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
	"""
	Core function to sync attendance_request_reason from Attendance Request explanation.
	
	This is the single source of truth for populating the attendance_request_reason field.
	It reads the explanation from the linked Attendance Request and updates the Attendance
	field only if the value is different (idempotent).
	
	Args:
		attendance_doc: Attendance document (can be submitted or draft)
	
	Returns:
		None (modifies attendance_doc in place and saves to database)
	"""
	if not attendance_doc:
		return
	
	# Validate prerequisites
	if not hasattr(attendance_doc, 'attendance_request') or not attendance_doc.attendance_request:
		return
	
	if not attendance_doc.meta.has_field("attendance_request_reason"):
		return
	
	try:
		# Always read from the linked Attendance Request (not from document name)
		explanation = frappe.db.get_value(
			"Attendance Request",
			attendance_doc.attendance_request,
			"explanation"
		)
		
		# Normalize None to empty string for comparison
		explanation = explanation or ""
		current_value = attendance_doc.get("attendance_request_reason") or ""
		
		# Only update if different (idempotent)
		if current_value != explanation:
			# Use db_set to ensure it works for submitted documents
			frappe.db.set_value(
				"Attendance",
				attendance_doc.name,
				"attendance_request_reason",
				explanation,
				update_modified=False
			)
			frappe.db.commit()
			
			# Update the document object as well
			attendance_doc.attendance_request_reason = explanation
	except Exception as e:
		frappe.log_error(
			f"Error syncing attendance_request_reason: {str(e)}\n"
			f"Attendance: {attendance_doc.name if hasattr(attendance_doc, 'name') else 'New'}\n"
			f"Attendance Request: {attendance_doc.attendance_request}",
			"Sync Attendance Request Reason Error"
		)

def populate_attendance_reason_after_insert(doc, method=None):
	"""
	Hook: Called after Attendance is inserted.
	Calls the core sync function to populate attendance_request_reason.
	"""
	sync_attendance_request_reason(doc)


def populate_attendance_reason_after_submit(doc, method=None):
	"""
	Hook: Called after Attendance is submitted.
	Calls the core sync function to populate attendance_request_reason.
	Works for submitted documents as well.
	"""
	sync_attendance_request_reason(doc)


def create_attendance_request_client_script():
	"""Create client script to show check-in/check-out data after save"""
	
	script = """
frappe.ui.form.on('Attendance Request', {
	refresh: function(frm) {
		// Clean up stale checkin sections (persisted from previously viewed docs)
		if (frm.dashboard && frm.dashboard.parent) {
			frm.dashboard.parent.find('.checkin-dashboard-section').remove();
		}

		if (!frm.is_new() && frm.doc.employee && frm.doc.from_date && frm.doc.to_date) {
			show_checkin_data(frm);
		}
	},
	show_attendance_warnings: function() {
		// Suppress the standard HRMS attendance warnings section
	}
});

function show_checkin_data(frm) {
	frappe.call({
		method: 'alpinos.attendance_request_automation.get_checkin_data_for_dates',
		args: {
			employee: frm.doc.employee,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date
		},
		callback: function(r) {
			if (r.message) {
				render_checkin_table(frm, r.message);
			}
		}
	});
}

function render_checkin_table(frm, data) {
	const dates = Object.keys(data).sort();
	if (dates.length === 0) return;
	
	let html = `
		<div class="checkin-data-section" style="margin-top: 20px;">
			<div class="table-responsive">
				<table class="table table-bordered table-hover" style="font-size: 12px;">
					<thead>
						<tr>
							<th style="width: 20%;">Date</th>
							<th style="width: 25%;">Check-in</th>
							<th style="width: 25%;">Check-out</th>
							<th style="width: 30%;">Attendance Status</th>
						</tr>
					</thead>
					<tbody>
	`;
	
	dates.forEach(function(date) {
		const dateData = data[date];
		const checkIn = dateData.check_in;
		const checkOut = dateData.check_out;
		const attendance = dateData.attendance;
		
		const checkInTime = checkIn ? format_datetime(checkIn.time) : '-';
		const checkOutTime = checkOut ? format_datetime(checkOut.time) : '-';
		const attendanceStatus = attendance ? attendance.status : '-';
		
		let statusBadgeClass = 'badge-secondary';
		if (attendance) {
			if (attendance.status === 'Present') statusBadgeClass = 'badge-success';
			else if (attendance.status === 'Absent') statusBadgeClass = 'badge-danger';
			else if (attendance.status === 'Half Day') statusBadgeClass = 'badge-warning';
			else if (attendance.status === 'Work From Home') statusBadgeClass = 'badge-info';
		}
		
		html += `
			<tr data-date="${date}">
				<td>${format_date(date)}</td>
				<td class="text-center">
					${checkIn ? 
						`<span class="checkin-time">${checkInTime}</span>
						<button class="btn btn-xs btn-link edit-checkin" data-type="IN" data-checkin-name="${checkIn.name}" data-date="${date}"><i class="fa fa-edit"></i></button>` :
						`<button class="btn btn-xs btn-primary add-checkin" data-type="IN" data-date="${date}"><i class="fa fa-plus"></i> Add</button>`
					}
				</td>
				<td class="text-center">
					${checkOut ? 
						`<span class="checkout-time">${checkOutTime}</span>
						<button class="btn btn-xs btn-link edit-checkin" data-type="OUT" data-checkin-name="${checkOut.name}" data-date="${date}"><i class="fa fa-edit"></i></button>` :
						`<button class="btn btn-xs btn-primary add-checkin" data-type="OUT" data-date="${date}"><i class="fa fa-plus"></i> Add</button>`
					}
				</td>
				<td>${attendance ? `<span class="badge ${statusBadgeClass}">${attendanceStatus}</span>` : `<span class="badge badge-secondary">-</span>`}</td>
			</tr>
		`;
	});
	
	html += `</tbody></table></div></div>`;
	
	// Remove any existing checkin section before adding new one
	if (frm.dashboard && frm.dashboard.parent) {
		frm.dashboard.parent.find('.checkin-dashboard-section').remove();
	}
	
	frm.dashboard.add_section(html, __('Check-in/Check-out Details'), 'checkin-dashboard-section');
	frm.dashboard.show();
	
	setTimeout(() => attach_checkin_handlers(frm), 100);
}

function attach_checkin_handlers(frm) {
	$('.add-checkin').off('click').on('click', function() {
		add_checkin(frm, $(this).data('date'), $(this).data('type'));
	});
	$('.edit-checkin').off('click').on('click', function() {
		edit_checkin(frm, $(this).data('date'), $(this).data('type'), $(this).data('checkin-name'));
	});
}

function add_checkin(frm, date, logType) {
	const dialog = new frappe.ui.Dialog({
		title: __('Add Check-' + (logType === 'IN' ? 'in' : 'out')),
		fields: [
			{label: __('Date'), fieldname: 'date', fieldtype: 'Date', default: date, read_only: 1},
			{label: __('Time'), fieldname: 'time', fieldtype: 'Datetime', default: date + ' ' + (logType === 'IN' ? '09:00:00' : '18:00:00'), reqd: 1}
		],
		primary_action_label: __('Save'),
		primary_action: function() {
			const v = dialog.get_values();
			if (!v.time) return;
			
			// CLIENT-SIDE VALIDATION: Prevent future dates
			const selectedTime = new Date(v.time);
			const currentTime = new Date();
			if (selectedTime > currentTime) {
				frappe.msgprint({
					title: __('Future Date Not Allowed'),
					message: __('Cannot create check-in records for future dates. Selected time: {0}, Current time: {1}', [v.time, currentTime.toISOString()]),
					indicator: 'red'
				});
				return;
			}
			
			// CLIENT-SIDE VALIDATION: Ensure date matches the attendance request date
			const selectedDate = v.time.split(' ')[0];
			if (selectedDate !== date) {
				frappe.msgprint({
					title: __('Invalid Date'),
					message: __('Check-in date must match the attendance request date: {0}', [date]),
					indicator: 'red'
				});
				return;
			}
			
			frappe.call({
				method: 'alpinos.attendance_request_automation.create_or_update_checkin',
				args: { 
					employee: frm.doc.employee, 
					date: v.date, 
					log_type: logType, 
					time: v.time,
					attendance_request: frm.doc.name
				},
				callback: function(r) {
					if (r.message) {
						frappe.show_alert({message: __('Saved'), indicator: 'green'});
						dialog.hide();
						show_checkin_data(frm);
					}
				}
			});
		}
	});
	dialog.show();
}

function edit_checkin(frm, date, logType, checkinName) {
	frappe.db.get_value('Employee Checkin', checkinName, 'time').then(r => {
		if (!r.message) return;
		const dialog = new frappe.ui.Dialog({
			title: __('Edit Check-' + (logType === 'IN' ? 'in' : 'out')),
			fields: [
				{label: __('Date'), fieldname: 'date', fieldtype: 'Date', default: date, read_only: 1},
				{label: __('Time'), fieldname: 'time', fieldtype: 'Datetime', default: r.message.time, reqd: 1}
			],
			primary_action_label: __('Update'),
			primary_action: function() {
				const v = dialog.get_values();
				
				// CLIENT-SIDE VALIDATION: Prevent future dates
				const selectedTime = new Date(v.time);
				const currentTime = new Date();
				if (selectedTime > currentTime) {
					frappe.msgprint({
						title: __('Future Date Not Allowed'),
						message: __('Cannot create check-in records for future dates. Selected time: {0}, Current time: {1}', [v.time, currentTime.toISOString()]),
						indicator: 'red'
					});
					return;
				}
				
				// CLIENT-SIDE VALIDATION: Ensure date matches the attendance request date
				const selectedDate = v.time.split(' ')[0];
				if (selectedDate !== date) {
					frappe.msgprint({
						title: __('Invalid Date'),
						message: __('Check-in date must match the attendance request date: {0}', [date]),
						indicator: 'red'
					});
					return;
				}
				
				frappe.call({
					method: 'alpinos.attendance_request_automation.create_or_update_checkin',
					args: { 
						employee: frm.doc.employee, 
						date: v.date, 
						log_type: logType, 
						time: v.time, 
						checkin_name: checkinName,
						attendance_request: frm.doc.name
					},
					callback: function(r) {
						if (r.message) {
							frappe.show_alert({message: __('Updated'), indicator: 'green'});
							dialog.hide();
							show_checkin_data(frm);
						}
					}
				});
			}
		});
		dialog.show();
	});
}

function update_attendance_status(frm, date) {
	const reason = $(`.attendance-reason-select[data-date="${date}"]`).val();
	if (!reason) return;
	frappe.call({
		method: 'alpinos.attendance_request_automation.update_attendance_status',
		args: { employee: frm.doc.employee, date: date, reason: reason, attendance_request: frm.doc.name },
		callback: function(r) {
			if (r.message) {
				frm.set_value('reason', reason);
				frappe.show_alert({message: __('Updated'), indicator: 'green'});
				show_checkin_data(frm);
			}
		}
	});
}

function format_datetime(s) {
	if (!s) return '-';
	return new Date(s).toLocaleString('en-US', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: true });
}

function format_date(s) {
	if (!s) return '-';
	return new Date(s).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}
"""
	
	# Create or update client script
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
def sync_logs_now():
    from alpinos.essl_sync import sync_essl_logs
    return sync_essl_logs()

def create_employee_checkin_client_script():
    """Create client script to add Sync eSSL Logs button and hide manual Add buttons"""
    script = """
frappe.listview_settings['Employee Checkin'] = {
    refresh: function(listview) {
        // Add Sync Button for System Managers only
        if (frappe.user_roles.includes('System Manager') || frappe.session.user === 'Administrator') {
            listview.page.add_inner_button(__('Sync eSSL Logs'), function() {
                frappe.call({
                    method: 'alpinos.attendance_request_automation.sync_logs_now',
                    callback: function(r) {
                        if (r.message && r.message.status === 'success') {
                            frappe.show_alert({
                                message: __('Sync complete: ') + r.message.total_synced + __(' logs synced.'),
                                indicator: 'green'
                            });
                            listview.refresh();
                        }
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
    # Use a descriptive name for the script
    script_name = "Employee Checkin - Restrictions and Sync"
    
    # Check if old name exists and rename it or just use it
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
	"""
	Check if Attendance is on a Saturday, and override status based on `saturday_working_hours_threshold`.
	If finished required hours, mark Present, else Absent.
	"""
	if doc.docstatus == 2:
		return
		
	# Do not override approved Leaves or Holidays
	if doc.status in ["On Leave", "Holiday"]:
		return
		
	# 0 is Monday, 5 is Saturday
	from frappe.utils import getdate, flt
	if getdate(doc.attendance_date).weekday() != 5:
		return
		
	if not doc.shift:
		return
		
	threshold = frappe.db.get_value("Shift Type", doc.shift, "saturday_working_hours_threshold")
	
	threshold = flt(threshold)
	if threshold > 0:
		# Only apply Saturday override if working_hours is actually set (has checkins)
		# If working_hours is 0/None, let HRMS auto-attendance handle it (will be Absent)
		if flt(doc.working_hours) > 0:
			if flt(doc.working_hours) >= threshold:
				doc.status = "Present"
			else:
				doc.status = "Absent"
