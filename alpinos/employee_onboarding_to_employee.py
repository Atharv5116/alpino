"""
Custom Employee creation from Employee Onboarding.

This extends the standard HRMS mapping by:
- Copying all salary and bank details from onboarding to employee
- Copying qualification and work experience summary fields
- Creating rows in the Policy and Company Documents child tables
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc


@frappe.whitelist()
def make_employee_with_details(source_name: str, target_doc: str | None = None):
	"""
	Create an `Employee` from `Employee Onboarding` with Alpinos-specific mappings.

	This is meant to be called via `frappe.model.open_mapped_doc` from the
	Employee Onboarding form.
	"""

	if not source_name:
		frappe.throw(_("Employee Onboarding name is required"))

	# Import the core helper to reuse validation logic
	from hrms.hr.doctype.employee_onboarding import employee_onboarding as core_onboarding

	source_doc = frappe.get_doc("Employee Onboarding", source_name)
	source_doc.validate_employee_creation()

	def set_missing_values(source, target):
		# Call the same helper used in core HRMS make_employee
		if hasattr(core_onboarding, "EmployeeOnboarding"):
			# Personal email from Job Applicant (same as core implementation)
			if source.job_applicant:
				target.personal_email = frappe.db.get_value(
					"Job Applicant", source.job_applicant, "email_id"
				)

		# Ensure new employee starts as Active
		if not target.status:
			target.status = "Active"

		# ---- 1) Policies -> policy_child (Policy child table) ----
		try:
			if not target.policy_child:
				row = target.append("policy_child", {})
			else:
				row = target.policy_child[0]

			# Fieldname differences: wfh/geofencing names differ slightly
			policy_field_map = {
				"policy_assignment": "policy_assignment",
				"leave_policy": "leave_policy",
				"document_policy": "document_policy",
				"shift_policy": "shift_policy",
				"overtime_policy": "overtime_policy",
				"holiday_policy": "holiday_policy",
				"comp_off_policy": "comp_off_policy",
				"attendance_policy": "attendance_policy",
				"wfh_policy": "work_from_home_wfh_policy",
				"grace_policy": "grace_policy",
				"reimbursement_policy": "reimbursement_policy",
				"geofencing_policy": "geo_fencing_policy",
				"other_policy": "other_policy",
			}

			for src_field, tgt_field in policy_field_map.items():
				if hasattr(source, src_field):
					row.set(tgt_field, source.get(src_field))
		except Exception:
			# Don't block employee creation if policies mapping fails
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping policies from Employee Onboarding",
			)

		# ---- 2) Company Documents -> company_document_child ----
		try:
			if not target.company_document_child:
				company_row = target.append("company_document_child", {})
			else:
				company_row = target.company_document_child[0]

			for field in ("offer_letter", "bond_letter"):
				if hasattr(source, field):
					company_row.set(field, source.get(field))

			# Optional: carry over current onboarding status as initial document status
			# Only set if it's a valid status for the child table
			if hasattr(company_row, "status") and source.get("boarding_status"):
				boarding_status = source.boarding_status
				# Don't set "Pending" as it's not valid for company documents
				if boarding_status and boarding_status != "Pending":
					company_row.status = boarding_status
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping company documents from Employee Onboarding",
			)

		# ---- 2b) Company Details Section -> Employee main fields ----
		try:
			company_details_field_map = {
				"company_mobile_number": "company_mobile_number",
				"company_email": "company_email",
				"designation_company_profile": "designation",
				"department": "department",
				"location": "location",
				"reporting_manager": "reports_to",
				"hod": "hod",
				"category": "employment_type",
				"date_of_joining_onboarding": "date_of_joining",
			}
			
			# Link fields that should not accept "NA" values
			# Note: employment_type is now a Select field, not a Link field
			link_fields = {"location", "reports_to", "hod", "designation", "department"}

			for src_field, tgt_field in company_details_field_map.items():
				if hasattr(source, src_field) and hasattr(target, tgt_field):
					value = source.get(src_field)
					# Skip "NA" values for link fields
					if value and (value != "NA" or tgt_field not in link_fields):
						target.set(tgt_field, value)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping company details from Employee Onboarding",
			)

		# ---- 3) Qualification Child Table -> qualification_child table ----
		try:
			# Reload source to ensure child tables are loaded
			source.reload()
			
			# Get qualification_child table from source
			qualification_child = source.get("qualification_child") or []
			
			frappe.log_error(
				f"DEBUG: Employee Onboarding {source.name} - qualification_child count: {len(qualification_child)}, has attr: {hasattr(source, 'qualification_child')}",
				"Alpinos: Qualification Child Debug"
			)
			
			if qualification_child and len(qualification_child) > 0:
				for qual_row in qualification_child:
					# Create new row in Employee's qualification_child table
					qual_data = {
						"degree": qual_row.get("degree") or "",
						"grade": qual_row.get("grade") or "",
						"university": qual_row.get("university") or "",
						"graduation_year": qual_row.get("graduation_year") or "",
						"degree_certificate_upload": qual_row.get("degree_certificate_upload") or "",
					}
					
					# Append the row
					new_row = target.append("qualification_child", qual_data)
					frappe.log_error(
						f"DEBUG: Appended qualification_child row - degree: {qual_data.get('degree')}, university: {qual_data.get('university')}",
						"Alpinos: Qualification Child Append"
					)
			else:
				# Log if no qualification_child data found for debugging
				frappe.log_error(
					f"No qualification_child rows found in Employee Onboarding {source.name}. Row count: {len(qualification_child)}",
					"Alpinos: Qualification Child Table Mapping"
				)
		except Exception as e:
			frappe.log_error(
				frappe.get_traceback(),
				f"Alpinos: Error while mapping qualification_child table from Employee Onboarding {source.name} to Employee: {str(e)}",
			)

		# ---- 4) Experience Table -> experience table ----
		try:
			# Reload source to ensure child tables are loaded
			source.reload()
			
			# Get experience table from source
			experience = source.get("experience") or []
			
			frappe.log_error(
				f"DEBUG: Employee Onboarding {source.name} - experience count: {len(experience)}, has attr: {hasattr(source, 'experience')}",
				"Alpinos: Experience Debug"
			)
			
			if experience and len(experience) > 0:
				for exp_row in experience:
					# Create new row in Employee's experience table
					exp_data = {
						"company_name": exp_row.get("company_name") or "",
						"start_date": exp_row.get("start_date") or None,
						"end_date": exp_row.get("end_date") or None,
						"designation": exp_row.get("designation") or "",
						"city": exp_row.get("city") or "",
					}
					
					# Append the row
					new_row = target.append("experience", exp_data)
					frappe.log_error(
						f"DEBUG: Appended experience row - company: {exp_data.get('company_name')}, designation: {exp_data.get('designation')}",
						"Alpinos: Experience Append"
					)
			else:
				# Log if no experience data found for debugging
				frappe.log_error(
					f"No experience rows found in Employee Onboarding {source.name}. Row count: {len(experience)}",
					"Alpinos: Experience Table Mapping"
				)
		except Exception as e:
			frappe.log_error(
				frappe.get_traceback(),
				f"Alpinos: Error while mapping experience table from Employee Onboarding {source.name} to Employee: {str(e)}",
			)

		# ---- 5) Salary & Bank details ----
		salary_field_map = {
			"ctc_monthly": "ctc_monthly",
			"salary_template": "salary_template",
			"salary_start_date": "salary_start_date",
			"salary_end_date": "salary_end_date",
			"period_in_months": "period_in_months",
			"pay_frequency": "pay_frequency",
			"notice_period_salary": "notice_period",
			"probation_period": "probation_period",
			"probation_end_date": "probation_end_date",
			"salary_mode": "salary_mode",
			"increment_cycle": "increment_cycle",
			"tax_regime": "tax_regime",
		}

		# Link fields in salary that should not accept "NA"
		salary_link_fields = {"salary_template"}
		
		for src_field, tgt_field in salary_field_map.items():
			if hasattr(source, src_field) and hasattr(target, tgt_field):
				value = source.get(src_field)
				# Skip "NA" values for link fields
				if value and (value != "NA" or tgt_field not in salary_link_fields):
					target.set(tgt_field, value)

		# Bank details mapping
		bank_field_map = {
			"bank_name": "bank_name",
			"account_number": "bank_account_number",
			"account_type": "bank_account_type",
			"branch": "bank_branch",
			"ifsc_code": "ifsc_code",
			"bank_account_proof": "bank_account_proof",
		}

		for src_field, tgt_field in bank_field_map.items():
			if hasattr(source, src_field) and hasattr(target, tgt_field):
				target.set(tgt_field, source.get(src_field))

		# ---- 6) Family Details ----
		try:
			family_field_map = {
				"family_name": "family_member_name",
				"family_relation": "family_relation",
				"family_contact_number": "family_contact_number",
				"family_occupation": "family_occupation",
			}
			
			for src_field, tgt_field in family_field_map.items():
				if hasattr(source, src_field) and hasattr(target, tgt_field):
					value = source.get(src_field)
					if value:
						target.set(tgt_field, value)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping family details from Employee Onboarding to Employee",
			)

		# ---- 7) Emergency Contact Details ----
		try:
			emergency_field_map = {
				"emergency_contact_name": "person_to_be_contacted",
				"emergency_contact_relation": "relation",
				"emergency_contact_number": "emergency_phone_number",
			}
			
			for src_field, tgt_field in emergency_field_map.items():
				if hasattr(source, src_field) and hasattr(target, tgt_field):
					value = source.get(src_field)
					if value:
						target.set(tgt_field, value)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping emergency contact details from Employee Onboarding to Employee",
			)

	# Base mapping – similar to hrms.hr.doctype.employee_onboarding.employee_onboarding.make_employee
	# Note: Child tables are handled manually in set_missing_values to ensure they're copied correctly
	doc = get_mapped_doc(
		"Employee Onboarding",
		source_name,
		{
			"Employee Onboarding": {
				"doctype": "Employee",
				"field_map": {
					"first_name": "employee_name",
					"employee_grade": "grade",
				},
			},
			# Prevent automatic mapping of child tables - we'll handle them manually
			"Qualification Child": {
				"doctype": "Qualification Child",
				"ignore": True,  # Ignore automatic mapping, we'll do it manually
			},
			"Experience": {
				"doctype": "Experience",
				"ignore": True,  # Ignore automatic mapping, we'll do it manually
			},
		},
		target_doc,
		set_missing_values,
	)

	return doc


