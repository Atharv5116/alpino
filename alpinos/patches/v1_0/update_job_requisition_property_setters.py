"""Update property setters for Job Requisition standard fields."""

import frappe


def execute():
	make_field_mandatory("Job Requisition", "department")
	make_field_mandatory("Job Requisition", "designation")
	make_field_mandatory("Job Requisition", "description")
	make_field_mandatory("Job Requisition", "no_of_positions")
	make_field_mandatory("Job Requisition", "company")
	make_field_mandatory("Job Requisition", "expected_compensation")
	
	update_field_label("Job Requisition", "description", "Job Description")
	update_field_label("Job Requisition", "expected_compensation", "CTC Lower Range")
	update_field_label("Job Requisition", "posting_date", "Requested On")
	update_field_label("Job Requisition", "no_of_positions", "Number of Positions")
	
	update_field_property("Job Requisition", "posting_date", "read_only", 1)
	
	frappe.clear_cache()
	print("Job Requisition property setters updated successfully")


def make_field_mandatory(doctype, fieldname):
	try:
		update_property_setter(doctype, fieldname, "reqd", 1, "Check")
		print(f"Made {fieldname} mandatory in {doctype}")
	except Exception as e:
		print(f"Could not make {fieldname} mandatory: {str(e)}")


def update_field_label(doctype, fieldname, new_label):
	try:
		update_property_setter(doctype, fieldname, "label", new_label, "Data")
		print(f"Updated {fieldname} label to '{new_label}' in {doctype}")
	except Exception as e:
		print(f"Could not update {fieldname} label: {str(e)}")


def update_field_property(doctype, fieldname, property_name, value):
	try:
		property_type = "Check" if isinstance(value, (bool, int)) and property_name in ["read_only", "reqd", "hidden"] else "Data"
		update_property_setter(doctype, fieldname, property_name, value, property_type)
		print(f"Updated {fieldname} {property_name} to {value} in {doctype}")
	except Exception as e:
		print(f"Could not update {fieldname} {property_name}: {str(e)}")


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
		ps.property_type = property_type
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
