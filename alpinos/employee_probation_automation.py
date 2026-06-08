"""Auto-calculate Probation End Date on the Employee doctype.

Probation End Date = Date of Joining + Probation Period (days). Mirrors the Employee
Onboarding behaviour so that an Employee edited directly (not created from onboarding) also
gets the end date filled.

  - calculate_probation_end_date : validate doc_event — the source of truth (covers API /
    import / direct edits).
  - setup_employee_probation : after_migrate — marks probation_end_date read-only (it is
    derived) and installs a client script for a live preview as the days / DOJ are edited.

The probation_period / probation_end_date fields are assumed to already exist on Employee;
everything here is defensive (guards on field presence) so it is a no-op where they don't.
"""

import frappe
from frappe.utils import add_days, getdate


CLIENT_SCRIPT_NAME = "Employee - Probation End Date Auto-calc"


def calculate_probation_end_date(doc, method=None):
	"""Set Probation End Date = Date of Joining + Probation Period (days)."""
	if getattr(doc, "doctype", None) != "Employee":
		return
	if not doc.meta.has_field("probation_end_date") or not doc.meta.has_field("probation_period"):
		return
	doj = doc.get("date_of_joining")
	days = int(doc.get("probation_period") or 0)
	if not doj or days <= 0:
		return
	doc.probation_end_date = add_days(getdate(doj), days)


def setup_employee_probation():
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	try:
		# Probation End Date is derived — make it read-only on the form.
		if frappe.get_meta("Employee").has_field("probation_end_date"):
			make_property_setter(
				"Employee", "probation_end_date", "read_only", 1, "Check",
				validate_fields_for_doctype=False,
			)

		# Live preview as days / DOJ change (server-side validate stays the source of truth).
		script = """
frappe.ui.form.on('Employee', {
	probation_period: function(frm) { alp_emp_probation_end(frm); },
	date_of_joining: function(frm) { alp_emp_probation_end(frm); }
});

function alp_emp_probation_end(frm) {
	if (!frm.doc.date_of_joining) return;
	var days = parseInt(frm.doc.probation_period) || 0;
	if (days <= 0) return;
	var end = frappe.datetime.add_days(frm.doc.date_of_joining, days);
	if (frm.doc.probation_end_date !== end) {
		frm.set_value('probation_end_date', end);
	}
}
"""
		if frappe.db.exists("Client Script", CLIENT_SCRIPT_NAME):
			cs = frappe.get_doc("Client Script", CLIENT_SCRIPT_NAME)
			cs.script = script
			cs.enabled = 1
			cs.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Client Script",
					"name": CLIENT_SCRIPT_NAME,
					"dt": "Employee",
					"view": "Form",
					"enabled": 1,
					"script": script,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()
		print("✅ Employee probation end-date auto-calc set up (read-only + client script)")
	except Exception as e:
		print(f"⚠️  Could not set up Employee probation auto-calc: {str(e)}")
		frappe.log_error(frappe.get_traceback(), "Employee probation auto-calc setup")
