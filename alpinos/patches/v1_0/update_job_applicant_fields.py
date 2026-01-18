"""
Patch to update existing Job Applicant fields:
1. Update field labels (phone_number -> Mobile Number, resume_attachment -> Resume/CV)
2. Update status field options to match SRS requirements
3. Hide unwanted fields (Resume Link, Salary Expectation, Country, etc.)
4. Hide child table fields (if they exist)
5. Configure field visibility for web form and regular form
"""

import frappe


def execute():
	"""Execute patch to update Job Applicant fields"""
	
	# ============================================
	# FIELD LABEL UPDATES
	# ============================================
	
	# 1. Update phone_number label to "Mobile Number"
	update_property_setter(
		"Job Applicant",
		"phone_number",
		"label",
		"Mobile Number",
		"Data"
	)
	
	# 2. Update resume_attachment label to "Resume/CV"
	update_property_setter(
		"Job Applicant",
		"resume_attachment",
		"label",
		"Resume/CV",
		"Data"
	)
	
	# 3. Make resume_attachment mandatory
	update_field_property("Job Applicant", "resume_attachment", "reqd", 1)
	
	# ============================================
	# STATUS FIELD CONFIGURATION
	# ============================================
	
	# 4. Update status field options to match SRS requirements
	status_options = (
		"Draft\n"
		"Submitted\n"
		"New Application\n"
		"Rejected\n"
		"Archived"
	)
	update_property_setter(
		"Job Applicant",
		"status",
		"options",
		status_options,
		"Text"
	)
	
	# 5. Set default status to "Draft"
	update_property_setter(
		"Job Applicant",
		"status",
		"default",
		"Draft",
		"Data"
	)
	
	# 6. Hide status from web form (HR-only field)
	update_property_setter(
		"Job Applicant",
		"status",
		"show_in_web_form",
		0,
		"Check"
	)
	
	# ============================================
	# HIDE UNWANTED FIELDS (Completely Remove from View)
	# ============================================
	
	# 7. Hide Country field (not in SRS)
	hide_field_completely("Job Applicant", "country")
	
	# 8. Hide Resume Link (only use Resume Attachment)
	hide_field_completely("Job Applicant", "resume_link")
	
	# 9. Hide Salary Expectation section fields (not in SRS)
	hide_field_completely("Job Applicant", "currency")
	hide_field_completely("Job Applicant", "lower_range")
	hide_field_completely("Job Applicant", "upper_range")
	
	# 10. Hide additional unwanted fields
	hide_field_completely("Job Applicant", "notes")
	hide_field_completely("Job Applicant", "source_name")
	hide_field_completely("Job Applicant", "employee_referral")
	
	# 10a. Hide flat reference fields (we use Reference table instead)
	hide_field_completely("Job Applicant", "reference_name")
	hide_field_completely("Job Applicant", "reference_mobile_number")
	
	# 11. Hide any child table fields if they exist (except reference - keep it visible)
	hide_field_completely("Job Applicant", "employment_history")
	hide_field_completely("Job Applicant", "qualification")
	# Reference table should be visible - don't hide it
	
	# 12. Hide Qualification section break
	hide_field_completely("Job Applicant", "qualification_section")
	
	# 13. Hide degree field (non-mandatory, hidden)
	hide_field_completely("Job Applicant", "degree")
	
	# ============================================
	# AUTO-POPULATED FIELDS (Read-only, Hidden from Web Form)
	# ============================================
	
	# 12. Make main Designation field read-only and hidden from web form
	# Note: This is auto-populated from Job Opening/Requisition
	# The employment_designation field in Employment History section is separate
	update_property_setter(
		"Job Applicant",
		"designation",
		"read_only",
		1,
		"Check"
	)
	update_property_setter(
		"Job Applicant",
		"designation",
		"show_in_web_form",
		0,
		"Check"
	)
	
	# 13. Make Job Opening (job_title) read-only and hidden from web form
	# Note: This is auto-populated from Job Requisition
	update_property_setter(
		"Job Applicant",
		"job_title",
		"read_only",
		1,
		"Check"
	)
	update_property_setter(
		"Job Applicant",
		"job_title",
		"show_in_web_form",
		0,
		"Check"
	)
	
	# ============================================
	# CANDIDATE ID CONFIGURATION
	# ============================================
	
	# 14. Hide Candidate ID from web form (HR-only field)
	update_property_setter(
		"Job Applicant",
		"candidate_id",
		"show_in_web_form",
		0,
		"Check"
	)
	
	# 15. Show Candidate ID in list view (for HR)
	update_property_setter(
		"Job Applicant",
		"candidate_id",
		"in_list_view",
		1,
		"Check"
	)
	
	# ============================================
	# FIELD POSITIONING (Move fields to Work Details section)
	# ============================================
	
	# 16. Move Source field to Work Details section (after total_experience)
	update_property_setter(
		"Job Applicant",
		"source",
		"insert_after",
		"total_experience",
		"Data"
	)
	
	# 17. Move Portfolio after Source
	update_property_setter(
		"Job Applicant",
		"portfolio",
		"insert_after",
		"source",
		"Data"
	)
	
	# 18. Move Expected Date of Joining after Portfolio
	update_property_setter(
		"Job Applicant",
		"expected_date_of_joining",
		"insert_after",
		"portfolio",
		"Data"
	)
	
	# 19. Move Reference table after Expected Date of Joining (in Work Details, no separate section)
	update_property_setter(
		"Job Applicant",
		"reference",
		"insert_after",
		"expected_date_of_joining",
		"Data"
	)
	
	# 20. Hide reference_section (no separate section needed - keep in Work Details)
	hide_field_completely("Job Applicant", "reference_section")
	
	# ============================================
	# JOB REQUISITION FIELD VISIBILITY
	# ============================================
	
	# 21. Make Job Requisition visible in doctype (Work Details section)
	update_property_setter(
		"Job Applicant",
		"job_requisition",
		"hidden",
		0,
		"Check"
	)
	
	# 22. Show Job Requisition in web form
	update_property_setter(
		"Job Applicant",
		"job_requisition",
		"show_in_web_form",
		1,
		"Check"
	)
	
	# 23. Make Job Requisition required
	update_property_setter(
		"Job Applicant",
		"job_requisition",
		"reqd",
		1,
		"Check"
	)
	
	# ============================================
	# APPLIED POSITION FIELD - MAKE NOT REQUIRED
	# ============================================
	
	# 24. Make applied_position NOT required (use job_requisition instead)
	update_property_setter(
		"Job Applicant",
		"applied_position",
		"reqd",
		0,
		"Check"
	)
	
	# 25. Hide applied_position from web form (use job_requisition instead)
	update_property_setter(
		"Job Applicant",
		"applied_position",
		"show_in_web_form",
		0,
		"Check"
	)
	
	# ============================================
	# UPDATE WEB FORM FIELD LABEL AND OPTIONS
	# ============================================
	
	# 26. Update web form job_requisition field label and options to "Job Opening"
	update_web_form_field("job-application", "job_requisition", {
		"label": "Job Opening",
		"options": "Job Opening"
	})
	
	frappe.clear_cache()
	print("✅ Job Applicant fields updated successfully")
	print("   - Field labels updated")
	print("   - Unwanted fields hidden:")
	print("     • Country")
	print("     • Resume Link")
	print("     • Salary Expectation (Currency, Lower Range, Upper Range)")
	print("     • Notes")
	print("     • Source Name")
	print("     • Employee Referral")
	print("     • Reference Name (flat field)")
	print("     • Reference Mobile Number (flat field)")
	print("   - Source and Reference moved to Work Details section")
	print("   - Child table fields hidden")
	print("   - Auto-populated fields configured (Designation, Job Opening)")
	print("   - Status field options updated")
	print("   - Field labels updated")
	print("   - Unwanted fields hidden:")
	print("     • Country")
	print("     • Resume Link")
	print("     • Salary Expectation (Currency, Lower Range, Upper Range)")
	print("     • Notes")
	print("     • Source Name")
	print("     • Employee Referral")
	print("   - Child table fields hidden")
	print("   - Auto-populated fields configured (Designation, Job Opening)")
	print("   - Status field options updated")


def update_field_property(doctype, fieldname, property_name, value):
	"""Update a field property directly"""
	try:
		field = frappe.get_doc("DocField", {"parent": doctype, "fieldname": fieldname})
		if field:
			setattr(field, property_name, value)
			field.save(ignore_permissions=True)
			frappe.db.commit()
	except frappe.DoesNotExistError:
		print(f"Field {fieldname} not found in {doctype}")


def hide_field_completely(doctype, fieldname):
	"""Hide a field completely from both web form and regular form"""
	# Hide from web form
	update_property_setter(
		doctype,
		fieldname,
		"show_in_web_form",
		0,
		"Check"
	)
	
	# Hide from regular form
	update_property_setter(
		doctype,
		fieldname,
		"hidden",
		1,
		"Check"
	)


def update_property_setter(doctype, fieldname, property_name, value, property_type="Data"):
	"""Create or update a property setter"""
	# Check if property setter already exists
	existing = frappe.db.exists(
		"Property Setter",
		{
			"doc_type": doctype,
			"field_name": fieldname,
			"property": property_name,
		}
	)
	
	if existing:
		# Update existing property setter
		ps = frappe.get_doc("Property Setter", existing)
		ps.value = value
		ps.save(ignore_permissions=True)
	else:
		# Create new property setter
		ps = frappe.get_doc({
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": property_name,
			"value": value,
			"property_type": property_type,
		})
		ps.insert(ignore_permissions=True)
	
	frappe.db.commit()


def update_web_form_field(web_form_name, fieldname, updates):
	"""Update a web form field's properties"""
	try:
		if not frappe.db.exists("Web Form", web_form_name):
			print(f"   ⚠️  Web Form {web_form_name} does not exist, skipping web form field update")
			return
		
		web_form = frappe.get_doc("Web Form", web_form_name)
		field_updated = False
		
		for field in web_form.web_form_fields:
			if field.fieldname == fieldname:
				for key, value in updates.items():
					setattr(field, key, value)
					field_updated = True
				break
		
		if field_updated:
			web_form.save(ignore_permissions=True)
			frappe.db.commit()
			print(f"   ✅ Updated web form field {fieldname}: {updates}")
		else:
			print(f"   ⚠️  Web form field {fieldname} not found in {web_form_name}")
	except Exception as e:
		frappe.log_error(f"Error updating web form field {fieldname}: {str(e)}", "Web Form Update Error")

