"""
Custom Fields for Job Requisition and Job Applicant DocTypes
Adds required fields as per SRS requirements
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def delete_qualification_field():
	"""Delete qualification table field if it exists (references non-existent Qualification DocType)"""
	try:
		qual_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Job Applicant", "fieldname": "qualification"},
			"name"
		)
		if qual_field:
			frappe.delete_doc("Custom Field", qual_field, force=1, ignore_permissions=True)
			frappe.db.commit()
			print("✅ Deleted qualification table field (references non-existent Qualification DocType)")
	except Exception as e:
		print(f"⚠️  Could not delete qualification field: {str(e)}")


def update_degree_field_position():
	"""Update degree field to be in qualification section"""
	try:
		# Update degree custom field's insert_after to qualification_section
		custom_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Job Applicant", "fieldname": "degree"},
			"name"
		)
		if custom_field:
			cf = frappe.get_doc("Custom Field", custom_field)
			cf.insert_after = "qualification_section"
			cf.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Updated degree field position to qualification section")
	except Exception as e:
		print(f"⚠️  Could not update degree field position: {str(e)}")


def hide_status_field():
	"""Hide status field in Job Applicant"""
	try:
		update_property_setter("Job Applicant", "status", "hidden", "1", "Check")
		print("✅ Hidden status field in Job Applicant")
	except Exception as e:
		print(f"⚠️  Could not hide status field: {str(e)}")


def remove_custom_requested_by_default():
	"""Remove any property setters that set default='user' for custom_requested_by field"""
	try:
		# Remove property setters for custom_requested_by
		property_setters = frappe.get_all(
			"Property Setter",
			filters={
				"doc_type": "Job Requisition",
				"field_name": "custom_requested_by",
				"property": "default"
			},
			fields=["name", "value"]
		)
		
		for ps in property_setters:
			if ps.value == "user" or not ps.value:
				frappe.delete_doc("Property Setter", ps.name, force=1, ignore_permissions=True)
				print(f"✅ Removed property setter: {ps.name}")
		
		# Also check and update Custom Field default value
		custom_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Job Requisition", "fieldname": "custom_requested_by"},
			["name", "default"],
			as_dict=True
		)
		
		if custom_field and (custom_field.default == "user" or custom_field.default):
			frappe.db.set_value("Custom Field", custom_field.name, "default", None)
			print(f"✅ Removed default value from Custom Field: {custom_field.name}")
		
		# Fix any existing Job Requisition records that have "user" as value
		invalid_records = frappe.get_all(
			"Job Requisition",
			filters={"custom_requested_by": "user"},
			fields=["name"]
		)
		
		if invalid_records:
			for record in invalid_records:
				# Try to get the owner or creator as fallback
				owner = frappe.db.get_value("Job Requisition", record.name, "owner")
				if owner and frappe.db.exists("User", owner):
					frappe.db.set_value("Job Requisition", record.name, "custom_requested_by", owner)
					print(f"✅ Fixed Job Requisition {record.name}: set custom_requested_by to {owner}")
		
		if property_setters or (custom_field and custom_field.default):
			frappe.db.commit()
	except Exception as e:
		print(f"⚠️  Could not remove custom_requested_by default property setters: {str(e)}")
		frappe.log_error(f"Error in remove_custom_requested_by_default: {str(e)}", "Custom Fields Setup")


def update_property_setter(doctype, fieldname, property_name, value, property_type="Data"):
	"""Create or update a property setter"""
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


def setup_custom_fields():
	"""Create custom fields for Job Requisition and Job Applicant"""
	
	custom_fields = {
		"Job Requisition": [
			# Section Break for Requisition Details (only shown in Edit view)
			dict(
				fieldname="requisition_details_section",
				label="Requisition Details",
				fieldtype="Section Break",
				insert_after="naming_series",
				collapsible=1,
				# Always visible (new + saved docs)
			),
			
			# Column Break for Status and Approval
			dict(
				fieldname="column_break_requisition",
				fieldtype="Column Break",
				insert_after="requisition_details_section",
			),
			
			# Approved On - Datetime (auto-set, but editable if needed)
			dict(
				fieldname="approved_on",
				label="Approved On",
				fieldtype="Datetime",
				read_only=0,
				insert_after="column_break_requisition",
			),
			
			# Approved By - Link to User (auto-set, but editable if needed)
			dict(
				fieldname="approved_by",
				label="Approved By",
				fieldtype="Link",
				options="User",
				read_only=0,
				insert_after="approved_on",
			),
			
			# Profile Details Section
			dict(
				fieldname="profile_details_section",
				label="Profile Details",
				fieldtype="Section Break",
				insert_after="approved_by",
				collapsible=0,
			),
			
			
			# Location - Link to Branch (after additional_description)
			dict(
				fieldname="location",
				label="Location",
				fieldtype="Link",
				options="Branch",
				insert_after="no_of_positions",
				reqd=1,
			),
			
			# Hiring Deadline - Date
			dict(
				fieldname="hiring_deadline",
				label="Hiring Deadline",
				fieldtype="Date",
				insert_after="location",
				reqd=1,
			),
			
			# Min. Experience - Int (Years)
			dict(
				fieldname="min_experience",
				label="Min. Experience (Years)",
				fieldtype="Int",
				insert_after="hiring_deadline",
				reqd=1,
			),
			
			# Priority - Select
			dict(
				fieldname="priority",
				label="Priority",
				fieldtype="Select",
				options="\nUrgent\nHigh\nMedium\nLow",
				insert_after="min_experience",
				reqd=1,
			),
			
			# Vacancy Type - Select
			dict(
				fieldname="vacancy_type",
				label="Vacancy Type",
				fieldtype="Select",
				options="\nNew\nReplace",
				insert_after="priority",
				reqd=1,
			),
			
			# Employee Details Section (for replacement positions)
			dict(
				fieldname="employee_details_section",
				label="Employee Details",
				fieldtype="Section Break",
				insert_after="vacancy_type",
				collapsible=1,
				depends_on='eval:doc.vacancy_type=="Replace"',
			),
			
			# Linked Employee - Link to Employee (for replacement)
			dict(
				fieldname="linked_employee",
				label="Linked Employee",
				fieldtype="Link",
				options="Employee",
				insert_after="employee_details_section",
				description="Select the employee being replaced (for replacement positions)",
				ignore_user_permissions=1,
			),
			
			# Column Break
			dict(
				fieldname="column_break_employee",
				fieldtype="Column Break",
				insert_after="linked_employee",
			),
			
			# Reporting Manager - Link to Employee (fetched from linked employee)
			dict(
				fieldname="reporting_manager",
				label="Reporting Manager",
				fieldtype="Link",
				options="Employee",
				insert_after="column_break_employee",
				read_only=1,
				fetch_from="linked_employee.reports_to",
				description="Auto-fetched from linked employee's reporting structure",
				ignore_user_permissions=1,
			),
			
			# Reporting Manager User - Link to User (hidden, for workflow)
			dict(
				fieldname="reporting_manager_user",
				label="Reporting Manager User",
				fieldtype="Link",
				options="User",
				insert_after="reporting_manager",
				read_only=1,
				hidden=1,
				description="User ID of reporting manager (for workflow)",
			),
			
			# Company Details Section
			dict(
				fieldname="company_details_section",
				label="Company Details",
				fieldtype="Section Break",
				insert_after="reporting_manager",
				collapsible=0,
			),
			
			# Salary Details Section
			dict(
				fieldname="salary_details_section",
				label="Salary Details",
				fieldtype="Section Break",
				insert_after="company_details_section",
				collapsible=0,
			),
			
			# CTC Upper Range - Currency (after salary section)
			dict(
				fieldname="ctc_upper_range",
				label="CTC Upper Range / Monthly",
				fieldtype="Currency",
				options="Company:company:default_currency",
				insert_after="salary_details_section",
				reqd=1,
			),
			
			# Requested By (in Timelines, after posting_date/Requested On)
			dict(
				fieldname="custom_requested_by",
				label="Requested By",
				fieldtype="Link",
				options="User",
				insert_after="posting_date",
				read_only=1,
				reqd=1,
				# No default - will be set by automation function set_requested_by
			),
			
			# Column Break for Employee Info
			dict(
				fieldname="column_break_requestor",
				fieldtype="Column Break",
				insert_after="custom_requested_by",
			),
			
			# Requested By Employee - Link to Employee (fetched from user)
			dict(
				fieldname="requested_by_employee",
				label="Requested By Employee",
				fieldtype="Link",
				options="Employee",
				insert_after="column_break_requestor",
				read_only=1,
				description="Employee record of the person requesting",
				ignore_user_permissions=1,
			),
			
			# Requestor's Reporting Manager - Link to Employee
			dict(
				fieldname="requestor_reporting_manager",
				label="Requestor's Manager",
				fieldtype="Link",
				options="Employee",
				insert_after="requested_by_employee",
				read_only=1,
				description="Reporting manager of the requesting employee",
				ignore_user_permissions=1,
			),
			
			# Requestor's Manager User - Link to User (hidden, for workflow)
			dict(
				fieldname="requestor_manager_user",
				label="Requestor Manager User",
				fieldtype="Link",
				options="User",
				insert_after="requestor_reporting_manager",
				read_only=1,
				hidden=1,
				description="User ID of requestor's manager (for workflow)",
			),
			
			# Required Skills Section Break (in job_description_tab)
			dict(
				fieldname="required_skills_section",
				label="Skills",
				fieldtype="Section Break",
				insert_after="reason_for_requesting",
				collapsible=1,
			),
			
			# Skills - Table (Designation Skill)
			dict(
				fieldname="skills",
				label="Skills",
				fieldtype="Table",
				options="Designation Skill",
				insert_after="required_skills_section",
			),
			
			# Required Languages Section Break
			dict(
				fieldname="required_languages_section",
				label="Language Proficiency",
				fieldtype="Section Break",
				insert_after="skills",
				collapsible=1,
			),
			
			# Languages - Table (Language Child)
			dict(
				fieldname="languages",
				label="Languages",
				fieldtype="Table",
				options="Language Child",
				insert_after="required_languages_section",
			),
		],
		"Job Opening": [
			dict(
				fieldname="source_linkedin",
				label="Source LinkedIn URL",
				fieldtype="Data",
				options="URL",
				read_only=1,
				insert_after="job_application_route",
			),
			dict(
				fieldname="source_indeed",
				label="Source Indeed URL",
				fieldtype="Data",
				options="URL",
				read_only=1,
				insert_after="source_linkedin",
			),
			dict(
				fieldname="source_naukari",
				label="Source Naukari.com URL",
				fieldtype="Data",
				options="URL",
				read_only=1,
				insert_after="source_indeed",
			),
		],
	"Job Applicant": [
		# Qualification Section Break (after notice_period or last employment field)
		dict(
			fieldname="qualification_section",
			label="Qualification",
			fieldtype="Section Break",
			insert_after="notice_period",
			collapsible=1,
		),
		
		# Screening Section Break
		dict(
			fieldname="screening_section",
			label="Screening",
			fieldtype="Section Break",
			insert_after="applicant_rating",
			collapsible=1,
		),
		
		# Candidate Category - Select (White/Hold/Black)
		# allow_on_submit=1 so screening page can update category on submitted applicants
		dict(
			fieldname="candidate_category",
			label="Candidate Category",
			fieldtype="Select",
			options="\nWhite\nHold\nBlack",
			insert_after="screening_section",
			allow_on_submit=1,
		),
		
		# Screening Status - Select (Read-only, auto-updated)
		dict(
			fieldname="screening_status",
			label="Screening Status",
			fieldtype="Select",
			options="\nPending Screening\nShortlisted\nScreening Call Scheduled\nOn Hold\nNot Eligible\nInterview Scheduled\nAccepted\nRejected\nHired",
			insert_after="candidate_category",
			read_only=1,
		),
	],
	"Employee": [
		# Welcome Formalities Section Break (below Company Details section)
		dict(
			fieldname="todo_checklist_section",
			label="Welcome Formalities",
			fieldtype="Section Break",
			insert_after="grade",
			collapsible=1,
		),
		
		# Todo Checklist Checkbox Fields
		dict(
			fieldname="collect_documents",
			label="Collect Documents",
			fieldtype="Check",
			insert_after="todo_checklist_section",
			default=0,
		),
		dict(
			fieldname="prepare_the_system",
			label="Prepare the System",
			fieldtype="Check",
			insert_after="collect_documents",
			default=0,
		),
		dict(
			fieldname="welcome_kit",
			label="Welcome Kit",
			fieldtype="Check",
			insert_after="prepare_the_system",
			default=0,
		),
		dict(
			fieldname="introduction_session_and_sops_allocation",
			label="Introduction Session + SOPs Allocation",
			fieldtype="Check",
			insert_after="welcome_kit",
			default=0,
		),
		dict(
			fieldname="bond_letter",
			label="Bond Letter",
			fieldtype="Check",
			insert_after="introduction_session_and_sops_allocation",
			default=0,
		),
		dict(
			fieldname="hrms_training",
			label="HRMS Training",
			fieldtype="Check",
			insert_after="bond_letter",
			default=0,
		),
		dict(
			fieldname="culture_training",
			label="Culture Training",
			fieldtype="Check",
			insert_after="hrms_training",
			default=0,
		),
		dict(
			fieldname="provide_credentials",
			label="Provide Credentials",
			fieldtype="Check",
			insert_after="culture_training",
			default=0,
		),
		dict(
			fieldname="system_training",
			label="System Training",
			fieldtype="Check",
			insert_after="provide_credentials",
			default=0,
		),
		dict(
			fieldname="product_training",
			label="Product Training",
			fieldtype="Check",
			insert_after="system_training",
			default=0,
		),
		dict(
			fieldname="meeting_with_department_head",
			label="Meeting with Department Head",
			fieldtype="Check",
			insert_after="product_training",
			default=0,
		),
	],
	"Employee Checkin": [
		dict(
			fieldname="checkout_reason",
			label="Checkout Reason (Outside Location)",
			fieldtype="Small Text",
			insert_after="geolocation",
			description="Required when checking out from outside the office geo-fence.",
		),
		dict(
			fieldname="from_attendance_request",
			label="From Attendance Request",
			fieldtype="Check",
			insert_after="checkout_reason",
			default=0,
			hidden=1,
			description="Set when check-in/check-out is created from Attendance Request; skips location validation.",
		),
	],
	"Attendance": [
		dict(
			fieldname="checkout_reason",
			label="Checkout Reason (Outside Location)",
			fieldtype="Small Text",
			insert_after="out_time",
			read_only=1,
			description="Reason provided when employee checked out from outside office location (from Employee Checkin).",
		),
	],
	"Sales Order": [
		dict(
			fieldname="custom_offline_buyer_section",
			label="Offline Buyer",
			fieldtype="Section Break",
			insert_after="customer",
			collapsible=1,
		),
		dict(
			fieldname="custom_offline_buyer_master",
			label="Offline Buyer Master",
			fieldtype="Link",
			options="Offline Buyer Master",
			insert_after="custom_offline_buyer_section",
			read_only=1,
			allow_on_submit=1,
		),
		dict(
			fieldname="custom_offline_buyer_customer_type",
			label="Customer Type (Offline Buyer)",
			fieldtype="Data",
			insert_after="custom_offline_buyer_master",
			read_only=1,
			allow_on_submit=1,
		),
	],
	# Delete qualification table field if it exists (references non-existent Qualification DocType)
	# This is handled separately to avoid validation errors
	}

	if not frappe.db.exists("DocType", "Offline Buyer Master"):
		custom_fields.pop("Sales Order", None)

	create_custom_fields(custom_fields, update=True)
	print("Custom fields created for Job Requisition, Job Opening, and Job Applicant")
	
	# Remove any property setters that set default="user" for custom_requested_by
	remove_custom_requested_by_default()
	
	# Delete qualification table field if it exists (it references non-existent Qualification DocType)
	delete_qualification_field()
	
	# Update degree field to be in qualification section
	update_degree_field_position()
	
	# Hide status field
	hide_status_field()

	# Make Interview Feedback skill assessment optional
	update_property_setter("Interview Feedback", "skill_assessment", "reqd", "0", "Check")
	print("✅ Made Interview Feedback skill assessment optional")
	
	# Delete exit_letter custom field from Employee if it exists
	delete_exit_letter_field()
	
	# Delete individual work experience fields (keep only experience child table)
	delete_employee_work_experience_individual_fields()
	
	# Ensure work experience section and experience child table exist (restore if deleted)
	ensure_work_experience_fields()
	
	# Delete qualification fields from Employee (keep only qualification_child table)
	delete_employee_qualification_fields()
	
	# Delete address fields from Employee
	delete_employee_address_fields()
	
	# Update bank_account_type and increment_cycle to Data fields
	update_employee_fields_to_data()

	try:
		from alpinos.delivery_note_custom_fields import setup_delivery_note_alpinos

		setup_delivery_note_alpinos()
	except Exception as e:
		print(f"⚠️  Delivery Note (Alpinos) setup skipped: {str(e)}")

	print("✅ Job Requisition custom fields created (property setters loaded from fixtures/property_setter.json)")


def delete_exit_letter_field():
	"""Delete exit_letter custom field from Employee if it exists and ensure it's hidden"""
	try:
		# First, try to delete custom field if it exists
		custom_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Employee", "fieldname": "exit_letter"},
			"name"
		)
		if custom_field:
			frappe.delete_doc("Custom Field", custom_field, force=1, ignore_permissions=True)
			frappe.db.commit()
			print("✅ Deleted exit_letter custom field from Employee")
		
		# Ensure property setters are applied (hide and make non-mandatory)
		update_property_setter("Employee", "exit_letter", "hidden", "1", "Check")
		update_property_setter("Employee", "exit_letter", "reqd", "0", "Check")
		print("✅ Applied property setters to hide exit_letter field in Employee")
	except Exception as e:
		print(f"⚠️  Could not delete/hide exit_letter field: {str(e)}")



def delete_employee_work_experience_individual_fields():
	"""Delete individual work experience fields from Employee doctype, keeping only experience child table"""
	fields_to_delete = [
		"company_name",
		"start_date",
		"end_date",
		"work_experience_designation",
		"city"
	]
	
	try:
		for fieldname in fields_to_delete:
			# Delete custom field if it exists
			custom_field = frappe.db.get_value(
				"Custom Field",
				{"dt": "Employee", "fieldname": fieldname},
				"name"
			)
			if custom_field:
				frappe.delete_doc("Custom Field", custom_field, force=1, ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Deleted {fieldname} custom field from Employee")
			
			# Also delete property setters for this field
			property_setters = frappe.get_all(
				"Property Setter",
				filters={
					"doc_type": "Employee",
					"field_name": fieldname
				},
				pluck="name"
			)
			for ps_name in property_setters:
				frappe.delete_doc("Property Setter", ps_name, force=1, ignore_permissions=True)
				print(f"✅ Deleted property setter: {ps_name} for {fieldname}")
		
		# Remove from field order if they exist
		field_order_ps = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Employee", "property": "field_order", "doctype_or_field": "DocType"},
			"name"
		)
		if field_order_ps:
			ps = frappe.get_doc("Property Setter", field_order_ps)
			import json
			field_order = json.loads(ps.value) if isinstance(ps.value, str) else ps.value
			removed_any = False
			for fieldname in fields_to_delete:
				if fieldname in field_order:
					field_order.remove(fieldname)
					removed_any = True
					print(f"✅ Removed {fieldname} from field_order")
			
			if removed_any:
				ps.value = json.dumps(field_order)
				ps.save(ignore_permissions=True)
				frappe.db.commit()
		
		frappe.db.commit()
		print("✅ Deleted individual work experience fields from Employee doctype (kept experience child table)")
	except Exception as e:
		print(f"⚠️  Could not delete work experience individual fields: {str(e)}")


def ensure_work_experience_fields():
	"""Ensure work experience section and experience child table exist in Employee doctype (no individual fields)"""
	try:
		# Check if work_experience_section exists
		work_exp_section = frappe.db.get_value(
			"Custom Field",
			{"dt": "Employee", "fieldname": "work_experience_section"},
			"name"
		)
		
		if not work_exp_section:
			# Create work_experience_section if it doesn't exist
			work_exp_section_doc = frappe.get_doc({
				"doctype": "Custom Field",
				"dt": "Employee",
				"fieldname": "work_experience_section",
				"fieldtype": "Section Break",
				"label": "Work Experience Section",
				"insert_after": "qualification_child",
				"collapsible": 1,
				"is_system_generated": 1
			})
			work_exp_section_doc.insert(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Created work_experience_section in Employee doctype")
		
		# Only create the experience child table, not individual fields
		experience_exists = frappe.db.get_value(
			"Custom Field",
			{"dt": "Employee", "fieldname": "experience"},
			"name"
		)
		
		if not experience_exists:
			experience_doc = frappe.get_doc({
				"doctype": "Custom Field",
				"dt": "Employee",
				"fieldname": "experience",
				"fieldtype": "Table",
				"label": "Experience",
				"options": "Experience",
				"insert_after": "work_experience_section",
				"is_system_generated": 1
			})
			experience_doc.insert(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Created experience child table in Employee doctype")
		
		print("✅ Work experience section and experience child table verified/restored")
	except Exception as e:
		print(f"⚠️  Could not ensure work experience fields: {str(e)}")


def delete_employee_qualification_fields():
	"""Delete qualification fields from Employee doctype, keeping only qualification_child table"""
	fields_to_delete = [
		"degree",
		"grade",
		"university",
		"graduation_year",
		"degree_certificate_upload"
	]
	
	try:
		for fieldname in fields_to_delete:
			# Delete custom field if it exists
			custom_field = frappe.db.get_value(
				"Custom Field",
				{"dt": "Employee", "fieldname": fieldname},
				"name"
			)
			if custom_field:
				frappe.delete_doc("Custom Field", custom_field, force=1, ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Deleted {fieldname} custom field from Employee")
			
			# Also delete property setters for this field
			property_setters = frappe.get_all(
				"Property Setter",
				filters={
					"doc_type": "Employee",
					"field_name": fieldname
				},
				pluck="name"
			)
			for ps_name in property_setters:
				frappe.delete_doc("Property Setter", ps_name, force=1, ignore_permissions=True)
				print(f"✅ Deleted property setter: {ps_name} for {fieldname}")
		
		# Remove from field order if they exist
		field_order_ps = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Employee", "property": "field_order", "doctype_or_field": "DocType"},
			"name"
		)
		if field_order_ps:
			ps = frappe.get_doc("Property Setter", field_order_ps)
			import json
			field_order = json.loads(ps.value) if isinstance(ps.value, str) else ps.value
			removed_any = False
			for fieldname in fields_to_delete:
				if fieldname in field_order:
					field_order.remove(fieldname)
					removed_any = True
					print(f"✅ Removed {fieldname} from field_order")
			
			if removed_any:
				ps.value = json.dumps(field_order)
				ps.save(ignore_permissions=True)
				frappe.db.commit()
		
		frappe.db.commit()
		print("✅ Deleted qualification fields from Employee doctype (kept qualification_child table)")
	except Exception as e:
		print(f"⚠️  Could not delete qualification fields: {str(e)}")


def delete_employee_address_fields():
	"""Delete address fields from Employee doctype"""
	fields_to_delete = [
		"city_state_combined",
		"pincode",
		"address_line_2",
		"address_line_1"
	]
	
	try:
		for fieldname in fields_to_delete:
			# Delete custom field if it exists
			custom_field = frappe.db.get_value(
				"Custom Field",
				{"dt": "Employee", "fieldname": fieldname},
				"name"
			)
			if custom_field:
				frappe.delete_doc("Custom Field", custom_field, force=1, ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Deleted {fieldname} custom field from Employee")
			
			# Also delete property setters for this field
			property_setters = frappe.get_all(
				"Property Setter",
				filters={
					"doc_type": "Employee",
					"field_name": fieldname
				},
				pluck="name"
			)
			for ps_name in property_setters:
				frappe.delete_doc("Property Setter", ps_name, force=1, ignore_permissions=True)
				print(f"✅ Deleted property setter: {ps_name} for {fieldname}")
		
		# Remove from field order if they exist
		field_order_ps = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Employee", "property": "field_order", "doctype_or_field": "DocType"},
			"name"
		)
		if field_order_ps:
			ps = frappe.get_doc("Property Setter", field_order_ps)
			import json
			field_order = json.loads(ps.value) if isinstance(ps.value, str) else ps.value
			removed_any = False
			for fieldname in fields_to_delete:
				if fieldname in field_order:
					field_order.remove(fieldname)
					removed_any = True
					print(f"✅ Removed {fieldname} from field_order")
			
			if removed_any:
				ps.value = json.dumps(field_order)
				ps.save(ignore_permissions=True)
				frappe.db.commit()
		
		frappe.db.commit()
		print("✅ Deleted address fields from Employee doctype")
	except Exception as e:
		print(f"⚠️  Could not delete address fields: {str(e)}")


def update_employee_fields_to_data():
	"""Update bank_account_type and increment_cycle fields to Data type in Employee doctype"""
	fields_to_update = ["bank_account_type", "increment_cycle"]
	
	try:
		for fieldname in fields_to_update:
			# Update custom field if it exists
			custom_field = frappe.db.get_value(
				"Custom Field",
				{"dt": "Employee", "fieldname": fieldname},
				"name"
			)
			if custom_field:
				cf = frappe.get_doc("Custom Field", custom_field)
				cf.fieldtype = "Data"
				cf.options = None
				cf.save(ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Updated {fieldname} to Data field in Employee")
			
			# Update property setters to ensure fieldtype is Data
			update_property_setter("Employee", fieldname, "fieldtype", "Data", "Select")
			update_property_setter("Employee", fieldname, "options", None, "Text")
			print(f"✅ Updated property setters for {fieldname} in Employee")
		
		frappe.db.commit()
		print("✅ Updated bank_account_type and increment_cycle to Data fields in Employee doctype")
	except Exception as e:
		print(f"⚠️  Could not update fields to Data type: {str(e)}")