"""
Update existing Web Form to match SRS requirements
Removes fields that should not be in web form
"""

import frappe


def update_job_application_webform():
	"""Update existing Job Application Web Form to match SRS and doctype field order"""
	
	if not frappe.db.exists("Web Form", "job-application"):
		print("ℹ️  Web Form does not exist, skipping update")
		return
	
	web_form = frappe.get_doc("Web Form", "job-application")
	
	# Fields to remove from web form (keep for HR but hide from candidates)
	fields_to_hide = [
		"country",
		"resume_link",
		"designation",
		"job_title",  # Job Opening - auto-populated, not manual
		"currency",
		"lower_range",
		"upper_range",
		"candidate_id",  # HR-only field
		"status",  # HR-only field
		"applied_position",  # Remove - use job_requisition instead
		# "job_requisition",  # Keep in web form - candidates need to select it
		# Remove any child table fields if they exist (except reference - keep it)
		"employment_history",  # Old child table
		"qualification",  # Old child table
		"qualification_degree",  # Removed field
		# Remove section breaks and column breaks that are hidden
		"source_and_rating_section",
		"reference_section",
		"section_break_6",
		"section_break_16",
		"column_break_3",
		"column_break_13",
		"column_break_18",
		# Remove hidden fields
		"source_name",
		"employee_referral",
		"applicant_rating",
		"notes",
		"cover_letter",
	]
	
	# Define field order matching doctype exactly (from property_setter field_order)
	# Only include fields that should be visible in web form (excluding hidden fields)
	# Order matches Job Applicant doctype: details_section -> work_details_section -> employment_history_section -> qualification_section
	field_order = [
		# Details Section (fields in same order as doctype)
		"applicant_name",
		"email_id",
		"phone_number",
		"marital_status",
		"city_state",
		"resume_attachment",
		# Work Details Section (same order as doctype)
		"work_details_section",
		"job_requisition",  # Candidates select Job Requisition (replaces applied_position)
		"application_date",
		"total_experience",
		"source",
		"portfolio",
		"expected_date_of_joining",
		# Employment History Section (same order as doctype)
		"employment_history_section",
		"employment_company_name",
		"employment_designation",
		"employment_current_ctc",
		"employment_expected_ctc",
		"employment_start_date",
		"employment_end_date",
		"employment_reason_for_leaving",
		"employment_notice_period",
		# Qualification Section (same order as doctype)
		"qualification_section",
		"degree",
		# Reference
		"reference",
	]
	
	# Create a dict of existing fields for quick lookup (extract data as dict)
	# Exclude fields that should be hidden/removed
	existing_fields = {}
	for f in web_form.web_form_fields:
		if f.fieldname not in fields_to_hide:
			field_dict = f.as_dict()
			# Ensure marital_status has options
			if f.fieldname == "marital_status" and f.fieldtype == "Select":
				if not field_dict.get("options") or field_dict.get("options", "").strip() == "":
					field_dict["options"] = "\nSingle\nMarried\nDivorced\nWidowed"
			existing_fields[f.fieldname] = field_dict
		# Explicitly remove applied_position if it exists (in case it's not in fields_to_hide check)
		elif f.fieldname == "applied_position":
			continue  # Skip this field completely
	
	# Rebuild web_form_fields in correct order
	new_web_form_fields = []
	for fieldname in field_order:
		if fieldname in existing_fields:
			# Use existing field data
			field_dict = existing_fields[fieldname]
			new_web_form_fields.append(field_dict)
		else:
			# Create new field from config
			field_config = get_field_config(fieldname)
			if field_config:
				new_web_form_fields.append(field_config)
			else:
				# Debug: warn if field config not found for important fields
				if fieldname == "job_requisition":
					print(f"   ⚠️  WARNING: job_requisition config not found in get_field_config!")
	
	# Replace web_form_fields completely to ensure correct order and remove unwanted fields
	web_form.web_form_fields = []
	for idx, field_dict in enumerate(new_web_form_fields):
		# Skip applied_position if it somehow made it through
		if field_dict.get("fieldname") == "applied_position":
			continue
		
		# Update job_requisition label and options if it exists
		if field_dict.get("fieldname") == "job_requisition":
			field_dict["label"] = "Job Opening"
			field_dict["options"] = "Job Opening"
		
		# Remove doctype from dict as it will be set automatically
		field_dict_clean = {k: v for k, v in field_dict.items() if k != "doctype"}
		field_doc = web_form.append("web_form_fields", field_dict_clean)
		field_doc.idx = idx + 1  # Set explicit index for ordering
	
	# Ensure job_requisition field exists - explicitly add if missing
	job_req_exists = any(f.fieldname == "job_requisition" for f in web_form.web_form_fields)
	if not job_req_exists:
		print("   ⚠️  job_requisition not found, adding it explicitly...")
		# Add job_requisition field explicitly
		job_req_config = get_field_config("job_requisition")
		if job_req_config:
			field_dict_clean = {k: v for k, v in job_req_config.items() if k != "doctype"}
			# Find the correct position (after work_details_section)
			work_details_idx = None
			for idx, field in enumerate(web_form.web_form_fields):
				if field.fieldname == "work_details_section":
					work_details_idx = idx
					break
			
			if work_details_idx is not None:
				# Append job_requisition at correct position (right after work_details_section)
				field_doc = web_form.append("web_form_fields", field_dict_clean, position=work_details_idx + 1)
				print(f"   ✅ Added job_requisition at position {work_details_idx + 1} (after work_details_section)")
			else:
				# If section break not found, find position from field_order
				# job_requisition should be right after work_details_section in field_order
				try:
					work_details_pos = field_order.index("work_details_section")
					insert_pos = work_details_pos + 1
					field_doc = web_form.append("web_form_fields", field_dict_clean, position=insert_pos)
					print(f"   ✅ Added job_requisition at position {insert_pos} (based on field_order)")
				except (ValueError, IndexError):
					# Last resort - append to end
					field_doc = web_form.append("web_form_fields", field_dict_clean)
					print("   ✅ Added job_requisition at end of form")
			
			# Update all indices
			for idx, field in enumerate(web_form.web_form_fields):
				field.idx = idx + 1
			
			# Save immediately before reload to ensure field is persisted
			web_form.save(ignore_permissions=True)
			frappe.db.commit()
		else:
			print("   ❌ ERROR: job_requisition config not found in get_field_config!")
	
	# Save and reload to ensure order is applied
	web_form.save(ignore_permissions=True)
	frappe.db.commit()
	web_form.reload()
	
	# Update existing job_requisition field label and options if it exists
	for field in web_form.web_form_fields:
		if field.fieldname == "job_requisition":
			field.label = "Job Opening"
			field.options = "Job Opening"
			break
	
	# Save again to persist label/options changes
	web_form.save(ignore_permissions=True)
	frappe.db.commit()
	
	# Verify job_requisition exists
	job_req_found = any(f.fieldname == "job_requisition" for f in web_form.web_form_fields)
	job_req_label = None
	if job_req_found:
		for f in web_form.web_form_fields:
			if f.fieldname == "job_requisition":
				job_req_label = f.label
				break
	
	print("✅ Job Application Web Form updated successfully")
	print(f"   Total fields: {len(web_form.web_form_fields)}")
	print(f"   Job Opening field: {'✅ Present' if job_req_found else '❌ Missing'}")
	if job_req_label:
		print(f"   Field label: {job_req_label} (linking to Job Opening)")
	print("   Removed fields: Applied Position (use Job Opening instead), Country, Resume Link, Designation, Salary fields, Hidden sections")
	print("   Kept field: Job Opening (candidates select open job openings)")
	print("   Field order matches Job Applicant doctype")
	print("   Sections: Details -> Work Details -> Employment History -> Qualification -> Reference")
	print("   Marital Status options updated")


def get_field_config(fieldname):
	"""Get field configuration for web form"""
	field_configs = {
		"applicant_name": {
			"doctype": "Web Form Field",
			"fieldname": "applicant_name",
			"fieldtype": "Data",
			"label": "Full Name",
			"reqd": 1,
		},
		"email_id": {
			"doctype": "Web Form Field",
			"fieldname": "email_id",
			"fieldtype": "Data",
			"label": "Email Address",
			"reqd": 1,
		},
		"phone_number": {
			"doctype": "Web Form Field",
			"fieldname": "phone_number",
			"fieldtype": "Data",
			"label": "Mobile Number",
			"reqd": 1,
		},
		"marital_status": {
			"doctype": "Web Form Field",
			"fieldname": "marital_status",
			"fieldtype": "Select",
			"label": "Marital Status",
			"options": "\nSingle\nMarried\nDivorced\nWidowed",
			"reqd": 1,
		},
		"city_state": {
			"doctype": "Web Form Field",
			"fieldname": "city_state",
			"fieldtype": "Data",
			"label": "City / State",
			"reqd": 1,
		},
		"resume_attachment": {
			"doctype": "Web Form Field",
			"fieldname": "resume_attachment",
			"fieldtype": "Attach",
			"label": "Resume/CV",
			"reqd": 1,
		},
		"work_details_section": {
			"doctype": "Web Form Field",
			"fieldname": "work_details_section",
			"fieldtype": "Section Break",
			"label": "Work Details",
		},
		"employment_history_section": {
			"doctype": "Web Form Field",
			"fieldname": "employment_history_section",
			"fieldtype": "Section Break",
			"label": "Employment History",
		},
		"qualification_section": {
			"doctype": "Web Form Field",
			"fieldname": "qualification_section",
			"fieldtype": "Section Break",
			"label": "Qualification",
		},
		"application_date": {
			"doctype": "Web Form Field",
			"fieldname": "application_date",
			"fieldtype": "Date",
			"label": "Application Date",
			"reqd": 1,
		},
		"job_requisition": {
			"doctype": "Web Form Field",
			"fieldname": "job_requisition",
			"fieldtype": "Link",
			"label": "Job Opening",
			"options": "Job Opening",
			"reqd": 1,
		},
		"source": {
			"doctype": "Web Form Field",
			"fieldname": "source",
			"fieldtype": "Link",
			"label": "Source",
			"options": "Job Applicant Source",
			"reqd": 1,
		},
		"total_experience": {
			"doctype": "Web Form Field",
			"fieldname": "total_experience",
			"fieldtype": "Data",
			"label": "Total Experience",
			"reqd": 1,
		},
		"portfolio": {
			"doctype": "Web Form Field",
			"fieldname": "portfolio",
			"fieldtype": "Data",
			"label": "Portfolio",
			"reqd": 0,
		},
		"expected_date_of_joining": {
			"doctype": "Web Form Field",
			"fieldname": "expected_date_of_joining",
			"fieldtype": "Date",
			"label": "Expected Date of Joining",
			"reqd": 0,
		},
		"reference": {
			"doctype": "Web Form Field",
			"fieldname": "reference",
			"fieldtype": "Table",
			"label": "Reference (If Any)",
			"options": "Job Application Reference",
		},
		"employment_company_name": {
			"doctype": "Web Form Field",
			"fieldname": "employment_company_name",
			"fieldtype": "Data",
			"label": "Company Name",
			"reqd": 1,
		},
		"employment_designation": {
			"doctype": "Web Form Field",
			"fieldname": "employment_designation",
			"fieldtype": "Data",
			"label": "Designation",
			"reqd": 1,
		},
		"employment_current_ctc": {
			"doctype": "Web Form Field",
			"fieldname": "employment_current_ctc",
			"fieldtype": "Data",
			"label": "Current CTC / Annum",
			"reqd": 1,
		},
		"employment_expected_ctc": {
			"doctype": "Web Form Field",
			"fieldname": "employment_expected_ctc",
			"fieldtype": "Data",
			"label": "Expected CTC / Annum",
			"reqd": 1,
		},
		"employment_reason_for_leaving": {
			"doctype": "Web Form Field",
			"fieldname": "employment_reason_for_leaving",
			"fieldtype": "Small Text",
			"label": "Reason for Leaving",
			"reqd": 1,
		},
		"employment_start_date": {
			"doctype": "Web Form Field",
			"fieldname": "employment_start_date",
			"fieldtype": "Date",
			"label": "Start Date",
			"reqd": 1,
		},
		"employment_end_date": {
			"doctype": "Web Form Field",
			"fieldname": "employment_end_date",
			"fieldtype": "Date",
			"label": "End Date",
			"reqd": 1,
		},
		"employment_notice_period": {
			"doctype": "Web Form Field",
			"fieldname": "employment_notice_period",
			"fieldtype": "Data",
			"label": "Notice Period",
			"reqd": 1,
		},
		"degree": {
			"doctype": "Web Form Field",
			"fieldname": "degree",
			"fieldtype": "Data",
			"label": "Degree",
			"reqd": 1,
		},
	}
	
	return field_configs.get(fieldname)


def execute():
	"""Execute web form update"""
	update_job_application_webform()

