"""Branch-wise policy access on Designation, auto-filled into Employee Onboarding.

- Adds a "Branch Policy Access" child table to Designation (one row per Branch, holding
  the 13 Link->Policy values).
- On Employee Onboarding, when `designation_company_profile` or `branch` changes, the 13
  policy fields are auto-filled from the matching Designation/branch row. All values stay
  editable and are not re-overwritten on a normal save. NOTE: designation_company_profile
  is a free-text Data field, so a match requires its text to equal a Designation record's
  name (get_branch_policy returns {} otherwise -> no fill).

Wired via the after_migrate hook (setup_designation_branch_policy).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# The 13 policy fields, identical fieldnames on both the child table and Employee Onboarding.
POLICY_FIELDS = [
	"policy_assignment",
	"leave_policy",
	"document_policy",
	"shift_policy",
	"overtime_policy",
	"holiday_policy",
	"comp_off_policy",
	"attendance_policy",
	"wfh_policy",
	"grace_policy",
	"reimbursement_policy",
	"geofencing_policy",
	"other_policy",
]

ONBOARDING_CLIENT_SCRIPT = "Employee Onboarding - Branch Policy Auto-fill"


def setup_designation_branch_policy():
	_add_designation_table_field()
	_create_onboarding_client_script()


def _add_designation_table_field():
	custom_fields = {
		"Designation": [
			dict(
				fieldname="branch_policy_access",
				label="Branch Policy Access",
				fieldtype="Table",
				options="Branch Policy Access",
				insert_after="description",
				description="Per-branch policy access. Used to auto-fill the Policy section in Employee Onboarding by designation + branch.",
			),
		]
	}
	try:
		create_custom_fields(custom_fields, update=True)
		frappe.db.commit()
		print("✅ Added 'Branch Policy Access' table to Designation")
	except Exception as e:
		print(f"⚠️  Could not add Designation Branch Policy Access field: {e}")
		frappe.log_error(frappe.get_traceback(), "Designation Branch Policy Access field")


@frappe.whitelist()
def get_branch_policy(designation, branch):
	"""Return {policy_fieldname: value} from the Designation's Branch Policy Access row
	matching `branch`. Empty dict when designation/branch is missing or no row matches.
	"""
	if not designation or not branch:
		return {}
	rows = frappe.get_all(
		"Branch Policy Access",
		filters={
			"parent": designation,
			"parenttype": "Designation",
			"parentfield": "branch_policy_access",
			"branch": branch,
		},
		fields=["name"] + POLICY_FIELDS,
		limit=1,
	)
	if not rows:
		return {}
	row = rows[0]
	return {f: row.get(f) for f in POLICY_FIELDS}


def autofill_onboarding_policy(doc, method=None):
	"""Server-side auto-fill of the Employee Onboarding Policy section.

	Runs on validate (save) so it works regardless of how the onboarding was created — including
	records auto-created from a Job Applicant, where the client-script field-change events never
	fire. Fills the 13 policy fields from the Designation's Branch Policy Access row matching the
	office Branch (`location`). Only EMPTY policy fields are filled, so manually entered values are
	preserved and a normal re-save does not overwrite them.
	"""
	designation = doc.get("designation")
	# `designation_company_profile` is free text; fall back to matching it to a Designation name.
	if not designation and doc.get("designation_company_profile"):
		designation = frappe.db.exists("Designation", doc.get("designation_company_profile"))
	branch = doc.get("location")
	if not designation or not branch:
		return

	policy = get_branch_policy(designation, branch)
	if not policy:
		return

	for fieldname in POLICY_FIELDS:
		if not doc.get(fieldname) and policy.get(fieldname):
			doc.set(fieldname, policy.get(fieldname))


def _create_onboarding_client_script():
	fields_js = str(POLICY_FIELDS).replace("'", '"')
	script = """
frappe.ui.form.on('Employee Onboarding', {
	designation_company_profile: function(frm) { alp_fetch_branch_policy(frm); },
	location: function(frm) { alp_fetch_branch_policy(frm); }
});

function alp_fetch_branch_policy(frm) {
	// `location` is the office Branch (Link -> Branch), matched against the Branch key
	// in Designation.branch_policy_access. (The `branch` field on Onboarding is the bank
	// branch and is intentionally NOT used here.)
	if (!frm.doc.designation_company_profile || !frm.doc.location) return;
	frappe.call({
		method: 'alpinos.designation_branch_policy.get_branch_policy',
		args: { designation: frm.doc.designation_company_profile, branch: frm.doc.location },
		callback: function(r) {
			if (!r.message) return;
			var p = r.message;
			var fields = __POLICY_FIELDS__;
			fields.forEach(function(f) {
				if (f in p) frm.set_value(f, p[f] || null);
			});
		}
	});
}
""".replace("__POLICY_FIELDS__", fields_js)

	try:
		if frappe.db.exists("Client Script", ONBOARDING_CLIENT_SCRIPT):
			cs = frappe.get_doc("Client Script", ONBOARDING_CLIENT_SCRIPT)
			cs.script = script
			cs.enabled = 1
			cs.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Client Script",
					"name": ONBOARDING_CLIENT_SCRIPT,
					"dt": "Employee Onboarding",
					"view": "Form",
					"enabled": 1,
					"script": script,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()
		print("✅ Created Employee Onboarding branch-policy auto-fill client script")
	except Exception as e:
		print(f"⚠️  Could not create onboarding branch-policy client script: {e}")
		frappe.log_error(frappe.get_traceback(), "Onboarding Branch Policy Client Script")
