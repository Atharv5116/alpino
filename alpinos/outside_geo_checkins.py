"""Outside-geo-location check-ins for HR review (Alpinos workspace widget).

Lists Employee Checkins flagged as outside the assigned geo-location (custom_outside_location),
with the reason the employee gave. Visible to HR roles only.
"""

import frappe
from frappe.utils import getdate


HR_ROLES = ("HR Manager", "HR User", "System Manager")


@frappe.whitelist()
def get_outside_geo_checkins(from_date=None, to_date=None):
	user = frappe.session.user
	if user != "Administrator" and not (set(HR_ROLES) & set(frappe.get_roles(user))):
		return {"allowed": False, "items": [], "total": 0}

	if not frappe.db.has_column("Employee Checkin", "custom_outside_location"):
		return {"allowed": True, "items": [], "total": 0}

	from_date = getdate(from_date) if from_date else getdate()
	to_date = getdate(to_date) if to_date else getdate()

	rows = frappe.get_all(
		"Employee Checkin",
		filters={
			"custom_outside_location": 1,
			"time": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
		},
		fields=[
			"employee",
			"employee_name",
			"time",
			"log_type",
			"custom_outside_reason",
			"custom_outside_remarks",
			"checkout_reason",
		],
		order_by="time desc",
		limit=500,
	)

	items = []
	for r in rows:
		dt = r.get("time")
		items.append(
			{
				"employee": r.get("employee"),
				"employee_name": r.get("employee_name")
				or frappe.db.get_value("Employee", r.get("employee"), "employee_name"),
				"department": frappe.db.get_value("Employee", r.get("employee"), "department") or "",
				"date": dt.strftime("%d-%m-%Y") if dt else "",
				"checkin_time": dt.strftime("%H:%M") if dt else "",
				"log_type": r.get("log_type"),
				"reason": r.get("custom_outside_reason") or r.get("checkout_reason") or "",
				"remarks": r.get("custom_outside_remarks") or "",
			}
		)
	return {"allowed": True, "items": items, "total": len(items)}
