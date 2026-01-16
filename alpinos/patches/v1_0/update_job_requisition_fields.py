"""
Patch to update existing Job Requisition fields:
1. Make department field required
2. Rename expected_compensation to ctc_lower_range (via property setter)
3. Rename posting_date to requested_on (via property setter)
4. Update status field options
"""

import frappe


def execute():
	"""Execute patch to update Job Requisition fields"""
	
	# 1. Make Job Requisition submittable (required for workflow)
	make_doctype_submittable("Job Requisition")
	
	# 2. Make department field required
	update_field_property("Job Requisition", "department", "reqd", 1)
	
	# 3. Update status field options to match workflow requirements
	status_options = (
		"Draft\n"
		"Pending Reporting Manager Approval\n"
		"Pending HOD Approval\n"
		"Pending HR Approval\n"
		"Approved\n"
		"Live\n"
		"Rejected\n"
		"Returned to Requestor\n"
		"On Hold"
	)
	update_field_property("Job Requisition", "status", "options", status_options)
	
	# 4. Update field labels via property setters
	# Note: We can't rename fields directly, so we'll use property setters for labels
	# The actual fieldnames remain the same for backward compatibility
	
	# Update label for expected_compensation
	update_property_setter(
		"Job Requisition",
		"expected_compensation",
		"label",
		"CTC Lower Range",
		"Data"
	)
	
	# Update label for posting_date
	update_property_setter(
		"Job Requisition",
		"posting_date",
		"label",
		"Requested On",
		"Data"
	)
	
	frappe.clear_cache()
	print("Job Requisition fields updated successfully")


def make_doctype_submittable(doctype):
	"""Make a DocType submittable (required for workflow)"""
	try:
		doc_type = frappe.get_doc("DocType", doctype)
		if not doc_type.is_submittable:
			doc_type.is_submittable = 1
			doc_type.save(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Made {doctype} submittable")
		else:
			print(f"ℹ️  {doctype} is already submittable")
	except Exception as e:
		print(f"⚠️  Could not make {doctype} submittable: {str(e)}")


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
