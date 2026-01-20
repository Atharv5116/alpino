"""
Create default Policy records for each policy field in Employee Onboarding
"""

import frappe


def create_default_policies():
	"""Create Policy records for each policy field"""
	
	policy_names = [
		"Policy Assignment",
		"Leave Policy",
		"Document Policy",
		"Shift Policy",
		"Overtime Policy",
		"Holiday Policy",
		"Comp Off Policy",
		"Attendance Policy",
		"Work From Home (WFH) Policy",
		"Grace Policy",
		"Reimbursement Policy",
		"Geo-Fencing Policy",
		"Other Policy",
	]
	
	created_count = 0
	existing_count = 0
	
	for policy_name in policy_names:
		try:
			# Check if policy already exists by policy_name
			existing_policy = frappe.db.get_value("Policy", {"policy_name": policy_name}, "name")
			if existing_policy:
				print(f"ℹ️  Policy '{policy_name}' already exists (name: {existing_policy})")
				existing_count += 1
				continue
			
			# Create new policy - use policy_name as the document name
			policy = frappe.get_doc({
				"doctype": "Policy",
				"name": policy_name,  # Set name explicitly since autoname is "prompt"
				"policy_name": policy_name,
				"description": f"Default {policy_name} - Please update description and attach document as needed.",
			})
			policy.insert(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Created Policy: {policy_name}")
			created_count += 1
			
		except Exception as e:
			print(f"❌ Error creating Policy '{policy_name}': {str(e)}")
			frappe.db.rollback()
	
	print(f"\n📊 Summary:")
	print(f"   Created: {created_count} policies")
	print(f"   Already existed: {existing_count} policies")
	print(f"   Total: {len(policy_names)} policies")


if __name__ == "__main__":
	frappe.init(site='alpino')
	frappe.connect()
	create_default_policies()
	frappe.destroy()

