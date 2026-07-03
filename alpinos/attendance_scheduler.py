import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime
from datetime import datetime, time

def process_auto_attendance_periodic():
    """
    Mark attendance periodically for all Shift Types that have auto-attendance enabled.
    Sets the process window to include recent data and triggers HRMS auto-attendance.
    """
    today_date = getdate()
    # Process from yesterday to capture late night shifts and current day
    yesterday_date = add_days(today_date, -1)
    
    process_attendance_after = get_datetime(datetime.combine(yesterday_date, time(0, 0, 0)))
    # Process up to now to keep attendance fresh
    last_sync_of_checkin = now_datetime()
    
    shifts = frappe.get_all(
        "Shift Type",
        filters={"enable_auto_attendance": 1},
        pluck="name",
    )
    
    if not shifts:
        return
        
    for shift_name in shifts:
        frappe.db.set_value(
            "Shift Type",
            shift_name,
            {
                "process_attendance_after": process_attendance_after,
                "last_sync_of_checkin": last_sync_of_checkin,
            },
            update_modified=False
        )
        
    frappe.db.commit()
    
    # Trigger HRMS standard auto-attendance processing
    try:
        # Ensure the Alpinos attendance patch (first-log -> in-time, last-log -> out-time,
        # regardless of log type) is active in THIS process. Auto-attendance runs in a
        # background worker that may not have imported the override module, so applying it
        # explicitly here guarantees shift_type.calculate_working_hours is our custom version.
        from alpinos.overrides.employee_checkin_override import _apply_checkout_reason_patch
        _apply_checkout_reason_patch()

        from hrms.hr.doctype.shift_type.shift_type import process_auto_attendance_for_all_shifts
        process_auto_attendance_for_all_shifts()
    except Exception as e:
        frappe.log_error("Alpinos Attendance Scheduler Error", frappe.get_traceback())
