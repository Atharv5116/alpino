"""Outside-geo-location check-ins for HR review (Alpinos workspace widget)."""

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
			# OUT (check-out) fields
			"custom_outside_reason",
			"custom_outside_remarks",
			"checkout_reason",
			# IN (check-in) fields
			"custom_checkin_type",
			"custom_checkin_reason",
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
				# check-IN carries a type; check-OUT carries the outside/checkout reason
				"reason": (
					(r.get("custom_checkin_type") or "")
					if r.get("log_type") == "IN"
					else (r.get("custom_outside_reason") or r.get("checkout_reason") or "")
				),
				"remarks": (
					(r.get("custom_checkin_reason") or "")
					if r.get("log_type") == "IN"
					else (r.get("custom_outside_remarks") or "")
				),
			}
		)
	return {"allowed": True, "items": items, "total": len(items)}


@frappe.whitelist()
def download_outside_geo_checkins(from_date=None, to_date=None):
	"""Excel export of the outside-geo-location check-ins for a date range (HR only)."""
	from frappe.utils.xlsxutils import make_xlsx

	res = get_outside_geo_checkins(from_date, to_date)
	if not res.get("allowed"):
		frappe.throw(frappe._("Not permitted."), frappe.PermissionError)

	def _dir(lt):
		return "Check-In" if lt == "IN" else ("Check-Out" if lt == "OUT" else (lt or ""))

	rows = [["Employee Name", "Department", "Check-In Date", "Check-In Time", "Type", "Reason", "Explanation / Remarks"]]
	for it in res.get("items", []):
		rows.append([
			it.get("employee_name") or it.get("employee") or "",
			it.get("department") or "",
			it.get("date") or "",
			it.get("checkin_time") or "",
			_dir(it.get("log_type")),
			it.get("reason") or "",
			it.get("remarks") or "",
		])

	fd = getdate(from_date) if from_date else getdate()
	td = getdate(to_date) if to_date else getdate()
	xlsx = make_xlsx(rows, "Outside Geo Checkins")
	frappe.response["filename"] = f"Outside_Geo_Checkins_{fd}_{td}.xlsx"
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"
