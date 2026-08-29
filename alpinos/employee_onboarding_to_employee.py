"""Create an Employee from Employee Onboarding with Alpinos-specific field mappings."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc


@frappe.whitelist()
def make_employee_with_details(source_name: str, target_doc: str | None = None):
	"""Create an Employee from Employee Onboarding (called via open_mapped_doc)."""

	if not source_name:
		frappe.throw(_("Employee Onboarding name is required"))

	from hrms.hr.doctype.employee_onboarding import employee_onboarding as core_onboarding

	source_doc = frappe.get_doc("Employee Onboarding", source_name)
	source_doc.validate_employee_creation()

	def set_missing_values(source, target):
		if hasattr(core_onboarding, "EmployeeOnboarding"):
			if source.job_applicant:
				target.personal_email = frappe.db.get_value(
					"Job Applicant", source.job_applicant, "email_id"
				)

		if not target.status:
			target.status = "Active"

		# Policies
		try:
			if not target.policy_child:
				row = target.append("policy_child", {})
			else:
				row = target.policy_child[0]

			# wfh/geofencing fieldnames differ
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
			# don't block employee creation if policies mapping fails
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping policies from Employee Onboarding",
			)

		# Company Documents
		try:
			if not target.company_document_child:
				company_row = target.append("company_document_child", {})
			else:
				company_row = target.company_document_child[0]

			for field in ("offer_letter", "bond_letter"):
				if hasattr(source, field):
					company_row.set(field, source.get(field))

			# Carry onboarding status as the initial document status.
			if hasattr(company_row, "status") and source.get("boarding_status"):
				boarding_status = source.boarding_status
				# "Pending" isn't valid for company documents
				if boarding_status and boarding_status != "Pending":
					company_row.status = boarding_status
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping company documents from Employee Onboarding",
			)

		# Company Details
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
				"salary_category": "salary_category",
				"date_of_joining_onboarding": "date_of_joining",
			}

			# Link fields that must reject "NA".
			link_fields = {"location", "reports_to", "hod", "designation", "department", "salary_category"}

			for src_field, tgt_field in company_details_field_map.items():
				if hasattr(source, src_field) and hasattr(target, tgt_field):
					value = source.get(src_field)
					if value and (value != "NA" or tgt_field not in link_fields):
						target.set(tgt_field, value)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Alpinos: Error while mapping company details from Employee Onboarding",
			)

		# Qualification
		try:
			# reload so child tables load
			source.reload()

			qualification_child = source.get("qualification_child") or []
			
			frappe.log_error(
				f"DEBUG: Employee Onboarding {source.name} - qualification_child count: {len(qualification_child)}, has attr: {hasattr(source, 'qualification_child')}",
				"Alpinos: Qualification Child Debug"
			)
			
			if qualification_child and len(qualification_child) > 0:
				for qual_row in qualification_child:
					qual_data = {
						"degree": qual_row.get("degree") or "",
						"grade": qual_row.get("grade") or "",
						"university": qual_row.get("university") or "",
						"graduation_year": qual_row.get("graduation_year") or "",
						"degree_certificate_upload": qual_row.get("degree_certificate_upload") or "",
					}

					new_row = target.append("qualification_child", qual_data)
					frappe.log_error(
						f"DEBUG: Appended qualification_child row - degree: {qual_data.get('degree')}, university: {qual_data.get('university')}",
						"Alpinos: Qualification Child Append"
					)
			else:
				frappe.log_error(
					f"No qualification_child rows found in Employee Onboarding {source.name}. Row count: {len(qualification_child)}",
					"Alpinos: Qualification Child Table Mapping"
				)
		except Exception as e:
			frappe.log_error(
				frappe.get_traceback(),
				f"Alpinos: Error while mapping qualification_child table from Employee Onboarding {source.name} to Employee: {str(e)}",
			)

		# Experience
		try:
			source.reload()

			experience = source.get("experience") or []
			
			frappe.log_error(
				f"DEBUG: Employee Onboarding {source.name} - experience count: {len(experience)}, has attr: {hasattr(source, 'experience')}",
				"Alpinos: Experience Debug"
			)
			
			if experience and len(experience) > 0:
				for exp_row in experience:
					exp_data = {
						"company_name": exp_row.get("company_name") or "",
						"start_date": exp_row.get("start_date") or None,
						"end_date": exp_row.get("end_date") or None,
						"designation": exp_row.get("designation") or "",
						"city": exp_row.get("city") or "",
					}

					new_row = target.append("experience", exp_data)
					frappe.log_error(
						f"DEBUG: Appended experience row - company: {exp_data.get('company_name')}, designation: {exp_data.get('designation')}",
						"Alpinos: Experience Append"
					)
			else:
				frappe.log_error(
					f"No experience rows found in Employee Onboarding {source.name}. Row count: {len(experience)}",
					"Alpinos: Experience Table Mapping"
				)
		except Exception as e:
			frappe.log_error(
				frappe.get_traceback(),
				f"Alpinos: Error while mapping experience table from Employee Onboarding {source.name} to Employee: {str(e)}",
			)

		# Salary & bank details
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

		# Salary link fields that must reject "NA".
		salary_link_fields = {"salary_template"}

		for src_field, tgt_field in salary_field_map.items():
			if hasattr(source, src_field) and hasattr(target, tgt_field):
				value = source.get(src_field)
				if value and (value != "NA" or tgt_field not in salary_link_fields):
					target.set(tgt_field, value)

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

		# Family details
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

		# Emergency contact
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

	# Child tables are mapped manually in set_missing_values.
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
			"Qualification Child": {
				"doctype": "Qualification Child",
				"ignore": True,
			},
			"Experience": {
				"doctype": "Experience",
				"ignore": True,
			},
		},
		target_doc,
		set_missing_values,
	)

	return doc


