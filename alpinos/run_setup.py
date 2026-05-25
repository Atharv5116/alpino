import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def add_shift_type_custom_fields():
    custom_fields = {
        "Shift Type": [
            dict(
                fieldname="saturday_working_hours_threshold",
                label="Saturday Working Hours Threshold for Present",
                fieldtype="Float",
                insert_after="working_hours_threshold_for_half_day",
                description="Minimum working hours required on Saturday to be marked as Present. If hours are less, Employee will be marked Absent."
            ),
        ]
    }
    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()
    print("Done")

if __name__ == "__main__":
    add_shift_type_custom_fields()
