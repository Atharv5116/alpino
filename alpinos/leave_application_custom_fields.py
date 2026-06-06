"""Custom fields on Leave Application.

  - custom_supporting_document : Attach proof, mandatory when the leave is longer
    than 3 days (total_leave_days > 3). The mandatory rule is enforced both at the
    field level (mandatory_depends_on) and in CustomLeaveApplication.validate().

  - custom_half_day_period : which half (First/Second) a half-day leave is for.
    Shown and mandatory only when the Half Day box is ticked. The "other" (working)
    half is reconciled against the shift threshold during attendance auto-marking
    (see alpinos.attendance_request_automation.mark_half_day_absent_below_threshold).

Created on every migrate via the after_migrate hook.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_leave_application_custom_fields():
	custom_fields = {
		"Leave Application": [
			dict(
				fieldname="custom_half_day_period",
				label="Half Day Period",
				fieldtype="Select",
				options="\nFirst Half\nSecond Half",
				insert_after="half_day_date",
				depends_on="eval:doc.half_day",
				mandatory_depends_on="eval:doc.half_day",
				description="Which half of the day is the leave for. The other half is the working half.",
			),
			dict(
				fieldname="custom_supporting_document",
				label="Supporting Document",
				fieldtype="Attach",
				insert_after="description",
				mandatory_depends_on="eval:doc.total_leave_days > 3",
				description="Proof is mandatory when total leave is more than 3 days.",
			),
		]
	}

	try:
		create_custom_fields(custom_fields, update=True)
		frappe.db.commit()
		print("✅ Added Leave Application custom fields (supporting document, half day period)")
	except Exception as e:
		print(f"⚠️  Could not add Leave Application custom fields: {str(e)}")
		frappe.log_error(
			f"Error adding Leave Application custom fields: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Add Leave Application Custom Fields",
		)
