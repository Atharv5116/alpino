"""Update Job Requisition fields for the approval workflow."""

import frappe


def execute():
	make_doctype_submittable("Job Requisition")

	update_field_property("Job Requisition", "department", "reqd", 1)

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

	# allow_on_submit lets the workflow update status after submit
	update_field_property("Job Requisition", "status", "allow_on_submit", 1)

	# Rename via label property setters; fieldnames stay the same for compatibility
	update_property_setter(
		"Job Requisition",
		"expected_compensation",
		"label",
		"CTC Lower Range",
		"Data"
	)

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
	try:
		doc_type = frappe.get_doc("DocType", doctype)
		if not doc_type.is_submittable:
			doc_type.is_submittable = 1
			doc_type.make_amendable()
			doc_type.save(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Made {doctype} submittable")
		else:
			print(f"ℹ️  {doctype} is already submittable")
			doc_type.make_amendable()
			if doc_type.has_value_changed("fields"):
				doc_type.save(ignore_permissions=True)
				frappe.db.commit()

		amended_from_exists = frappe.db.exists(
			"DocField", 
			{"parent": doctype, "fieldname": "amended_from"}
		)
		if amended_from_exists:
			print(f"✅ Verified amended_from field exists in {doctype}")
		else:
			add_amended_from_field(doctype)
	except Exception as e:
		print(f"⚠️  Could not make {doctype} submittable: {str(e)}")
		import traceback
		traceback.print_exc()


def add_amended_from_field(doctype):
	try:
		if frappe.db.exists("DocField", {"parent": doctype, "fieldname": "amended_from"}):
			return

		last_field = frappe.db.get_value(
			"DocField",
			{"parent": doctype},
			"fieldname",
			order_by="idx desc"
		)

		amended_field = frappe.get_doc({
			"doctype": "DocField",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "fields",
			"label": "Amended From",
			"fieldtype": "Link",
			"fieldname": "amended_from",
			"options": doctype,
			"read_only": 1,
			"print_hide": 1,
			"no_copy": 1,
			"search_index": 1,
			"insert_after": last_field or "",
		})
		amended_field.insert(ignore_permissions=True)
		frappe.db.commit()
		print(f"✅ Added amended_from field to {doctype}")
	except Exception as e:
		print(f"⚠️  Could not add amended_from field to {doctype}: {str(e)}")


def update_field_property(doctype, fieldname, property_name, value):
	try:
		field = frappe.get_doc("DocField", {"parent": doctype, "fieldname": fieldname})
		if field:
			setattr(field, property_name, value)
			field.save(ignore_permissions=True)
			frappe.db.commit()
	except frappe.DoesNotExistError:
		print(f"Field {fieldname} not found in {doctype}")


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
