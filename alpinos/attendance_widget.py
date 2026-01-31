import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime


def _get_employee_for_user(user):
    return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _get_today_range():
    today = getdate(now_datetime())
    start = get_datetime(today)
    end = add_days(start, 1)
    return start, end


def _get_today_last_checkin(employee):
    start, end = _get_today_range()
    return frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "time": ["between", [start, end]]},
        fields=["name", "log_type", "time"],
        order_by="time desc",
        limit=1,
    )


def _get_today_first_checkin(employee):
    start, end = _get_today_range()
    return frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "log_type": "IN", "time": ["between", [start, end]]},
        fields=["name", "log_type", "time"],
        order_by="time asc",
        limit=1,
    )


def _get_today_last_checkout(employee):
    start, end = _get_today_range()
    return frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "log_type": "OUT", "time": ["between", [start, end]]},
        fields=["name", "log_type", "time"],
        order_by="time desc",
        limit=1,
    )


@frappe.whitelist()
def get_status():
    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        return {"status": "NONE", "last_time": None, "elapsed_seconds": 0}
    today_in = _get_today_first_checkin(employee)
    if not today_in:
        return {"status": "NONE", "last_time": None, "elapsed_seconds": 0}

    in_time = today_in[0]["time"]
    last = _get_today_last_checkin(employee)
    last_out = _get_today_last_checkout(employee)

    if last and last[0]["log_type"] == "IN":
        return {"status": "IN", "last_time": in_time, "elapsed_seconds": None}

    if last_out:
        elapsed_seconds = int((last_out[0]["time"] - in_time).total_seconds())
        return {
            "status": "OUT",
            "last_time": last_out[0]["time"],
            "elapsed_seconds": max(elapsed_seconds, 0),
        }

    return {"status": "NONE", "last_time": None, "elapsed_seconds": 0}


@frappe.whitelist()
def check_in():
    if not frappe.has_permission("Employee Checkin", "create"):
        frappe.throw("You do not have permission to Check In.")

    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        frappe.throw("No Employee linked to this user.")
    today_last = _get_today_last_checkin(employee)
    if today_last:
        frappe.throw("You can only Check In once per day.")

    doc = frappe.get_doc(
        {"doctype": "Employee Checkin", "employee": employee, "log_type": "IN"}
    )
    doc.insert()
    return {"status": "IN", "time": doc.time}


@frappe.whitelist()
def check_out():
    if not frappe.has_permission("Employee Checkin", "create"):
        frappe.throw("You do not have permission to Check Out.")

    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        frappe.throw("No Employee linked to this user.")
    today_last = _get_today_last_checkin(employee)
    if not today_last or today_last[0]["log_type"] != "IN":
        frappe.throw("You must Check In today before Check Out.")

    last_out = _get_today_last_checkout(employee)
    if last_out:
        frappe.throw("You have already Checked Out today.")

    doc = frappe.get_doc(
        {"doctype": "Employee Checkin", "employee": employee, "log_type": "OUT"}
    )
    doc.insert()
    in_time = _get_today_first_checkin(employee)[0]["time"]
    elapsed_seconds = int((doc.time - in_time).total_seconds())
    return {"status": "OUT", "time": doc.time, "elapsed_seconds": max(elapsed_seconds, 0)}

