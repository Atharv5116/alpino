"""
Patch to update Job Applicant autoname to CAND-#### format
"""

import frappe
from frappe.model.naming import make_autoname


def execute():
	"""Update Job Applicant naming rule to CAND-.#####"""
	
	try:
		# Update the DocType's naming rule via Property Setter
		update_property_setter(
			"Job Applicant",
			"naming_rule",
			"CAND-.#####",
			"Data"
		)
		
		# Also update autoname field in DocType
		doc_type = frappe.get_doc("DocType", "Job Applicant")
		if doc_type.autoname != "CAND-.#####":
			doc_type.autoname = "CAND-.#####"
			doc_type.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Updated Job Applicant autoname to CAND-.#####")
		else:
			print("ℹ️  Job Applicant autoname already set to CAND-.#####")
			
		frappe.clear_cache()
		
	except Exception as e:
		print(f"⚠️  Could not update naming rule: {str(e)}")
		frappe.db.rollback()


def update_property_setter(doctype, property_name, value, property_type="Data"):
	"""Create or update a property setter"""
	existing = frappe.db.exists(
		"Property Setter",
		{
			"doc_type": doctype,
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
			"doctype_or_field": "DocType",
			"doc_type": doctype,
			"property": property_name,
			"value": value,
			"property_type": property_type,
		})
		ps.insert(ignore_permissions=True)
	
	frappe.db.commit()

