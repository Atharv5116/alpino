"""Update existing Job Applicant fields: labels, status options and field visibility per SRS."""

import frappe


def execute():
	update_property_setter(
		"Job Applicant",
		"phone_number",
		"label",
		"Mobile Number",
		"Data"
	)
	
	update_property_setter(
		"Job Applicant",
		"resume_attachment",
		"label",
		"Resume/CV",
		"Data"
	)
	
	update_field_property("Job Applicant", "resume_attachment", "reqd", 1)
	
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
	
	update_property_setter(
		"Job Applicant",
		"status",
		"default",
		"Draft",
		"Data"
	)
	
	# HR-only field, hidden from the web form
	update_property_setter(
		"Job Applicant",
		"status",
		"show_in_web_form",
		0,
		"Check"
	)
	
	# Hide fields not in the SRS
	hide_field_completely("Job Applicant", "country")
	
	hide_field_completely("Job Applicant", "resume_link")
	
	hide_field_completely("Job Applicant", "currency")
	hide_field_completely("Job Applicant", "lower_range")
	hide_field_completely("Job Applicant", "upper_range")
	
	hide_field_completely("Job Applicant", "notes")
	hide_field_completely("Job Applicant", "source_name")
	hide_field_completely("Job Applicant", "employee_referral")
	
	# Flat reference fields - we use the Reference child table instead
	hide_field_completely("Job Applicant", "reference_name")
	hide_field_completely("Job Applicant", "reference_mobile_number")
	
	# Hide child table fields (keep reference visible)
	hide_field_completely("Job Applicant", "employment_history")
	
	# qualification / qualification_section link a Qualification DocType that does not exist here
	delete_field_if_exists("Job Applicant", "qualification")
	
	
	# Delete the Qualification section break (references a non-existent DocType)
	delete_field_if_exists("Job Applicant", "qualification_section")

	hide_field_completely("Job Applicant", "degree")
	
	# Auto-populated from Job Opening/Requisition; the Employment History designation is a separate field
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
	
	# Auto-populated from Job Requisition
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
	
	update_property_setter(
		"Job Applicant",
		"candidate_id",
		"show_in_web_form",
		0,
		"Check"
	)
	
	update_property_setter(
		"Job Applicant",
		"candidate_id",
		"in_list_view",
		1,
		"Check"
	)
	
	# Move Source, Portfolio, Expected Joining Date and Reference into the Work Details section
	update_property_setter(
		"Job Applicant",
		"source",
		"insert_after",
		"total_experience",
		"Data"
	)
	
	update_property_setter(
		"Job Applicant",
		"portfolio",
		"insert_after",
		"source",
		"Data"
	)
	
	update_property_setter(
		"Job Applicant",
		"expected_date_of_joining",
		"insert_after",
		"portfolio",
		"Data"
	)
	
	update_property_setter(
		"Job Applicant",
		"reference",
		"insert_after",
		"expected_date_of_joining",
		"Data"
	)
	
	hide_field_completely("Job Applicant", "reference_section")
	
	update_property_setter(
		"Job Applicant",
		"job_requisition",
		"hidden",
		0,
		"Check"
	)
	
	update_property_setter(
		"Job Applicant",
		"job_requisition",
		"show_in_web_form",
		1,
		"Check"
	)
	
	update_property_setter(
		"Job Applicant",
		"job_requisition",
		"reqd",
		1,
		"Check"
	)
	
	# Use job_requisition instead of applied_position
	update_property_setter(
		"Job Applicant",
		"applied_position",
		"reqd",
		0,
		"Check"
	)
	
	update_property_setter(
		"Job Applicant",
		"applied_position",
		"show_in_web_form",
		0,
		"Check"
	)
	
	# Relabel job_requisition to "Job Opening" on the public web form
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
	try:
		field = frappe.get_doc("DocField", {"parent": doctype, "fieldname": fieldname})
		if field:
			setattr(field, property_name, value)
			field.save(ignore_permissions=True)
			frappe.db.commit()
	except frappe.DoesNotExistError:
		print(f"Field {fieldname} not found in {doctype}")


def delete_field_if_exists(doctype, fieldname):
	try:
		custom_field = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname})
		if custom_field:
			frappe.delete_doc("Custom Field", custom_field, force=1, ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Deleted field: {doctype}.{fieldname}")
	except Exception as e:
		print(f"⚠️  Could not delete field {doctype}.{fieldname}: {str(e)}")


def hide_field_completely(doctype, fieldname):
	update_property_setter(
		doctype,
		fieldname,
		"show_in_web_form",
		0,
		"Check"
	)
	
	update_property_setter(
		doctype,
		fieldname,
		"hidden",
		1,
		"Check"
	)


def update_property_setter(doctype, fieldname, property_name, value, property_type="Data"):
	existing = frappe.db.exists(
		"Property Setter",
		{
			"doc_type": doctype,
			"field_name": fieldname,
			"property": property_name,
		}
	)
	
	if existing:
		ps = frappe.get_doc("Property Setter", existing)
		ps.value = value
		ps.save(ignore_permissions=True)
	else:
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

