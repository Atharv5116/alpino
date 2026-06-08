"""Custom fields + single-day setup on Work From Home Request.

  - custom_half_day_period : which half (First/Second) a half-day WFH is for. Shown and
    mandatory only when the Half Day box is ticked. Mirrors the Leave Application field
    (alpinos.leave_application_custom_fields).

  - Work From Home is single-day only: the To Date field is hidden and kept equal to the
    date on save (see alpinos.work_from_home_request_automation.enforce_single_day).

Created on every migrate via the after_migrate hook.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def setup_work_from_home_custom_fields():
	custom_fields = {
		"Work From Home Request": [
			dict(
				fieldname="custom_half_day_period",
				label="Half Day Period",
				fieldtype="Select",
				options="\nFirst Half\nSecond Half",
				insert_after="half_day",
				depends_on="eval:doc.half_day",
				mandatory_depends_on="eval:doc.half_day",
				description="Which half of the day is the work-from-home for. The other half is the working half.",
			),
		]
	}

	try:
		create_custom_fields(custom_fields, update=True)

		# Single-day only: hide the To Date field (kept equal to the date on save) and relabel
		# the single date field. reqd=0 so the hidden field never blocks a save.
		make_property_setter(
			"Work From Home Request", "to_date", "hidden", 1, "Check",
			validate_fields_for_doctype=False,
		)
		make_property_setter(
			"Work From Home Request", "to_date", "reqd", 0, "Check",
			validate_fields_for_doctype=False,
		)
		make_property_setter(
			"Work From Home Request", "date", "label", "Date", "Data",
			validate_fields_for_doctype=False,
		)

		frappe.db.commit()
		print("✅ Added Work From Home custom fields (half day period) + single-day setup")
	except Exception as e:
		print(f"⚠️  Could not add Work From Home custom fields: {str(e)}")
		frappe.log_error(frappe.get_traceback(), "Work From Home custom fields")
