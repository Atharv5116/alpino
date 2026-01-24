"""
Setup script to create default Welcome Formalities Config records
Run: bench --site alpino console
Then: exec(open('apps/alpinos/alpinos/setup_welcome_formalities_config.py').read())
"""

import frappe

def setup_welcome_formalities_config():
	"""
	Create default configuration records for all 11 Welcome Formalities fields
	"""
	field_configs = [
		{
			"field_name": "collect_documents",
			"tat_days": 2
		},
		{
			"field_name": "prepare_the_system",
			"tat_days": 1
		},
		{
			"field_name": "welcome_kit",
			"tat_days": 1
		},
		{
			"field_name": "introduction_session_and_sops_allocation",
			"tat_days": 3
		},
		{
			"field_name": "bond_letter",
			"tat_days": 5
		},
		{
			"field_name": "hrms_training",
			"tat_days": 7
		},
		{
			"field_name": "culture_training",
			"tat_days": 7
		},
		{
			"field_name": "provide_credentials",
			"tat_days": 1
		},
		{
			"field_name": "system_training",
			"tat_days": 10
		},
		{
			"field_name": "product_training",
			"tat_days": 14
		},
		{
			"field_name": "meeting_with_department_head",
			"tat_days": 3
		}
	]
	
	created_count = 0
	updated_count = 0
	
	print("=" * 70)
	print("Setting up Welcome Formalities Config")
	print("=" * 70)
	
	for config in field_configs:
		try:
			# Check if config already exists
			existing = frappe.db.exists("Welcome Formalities Config", {"field_name": config["field_name"]})
			
			if existing:
				# Update existing
				config_doc = frappe.get_doc("Welcome Formalities Config", existing)
				config_doc.tat_days = config["tat_days"]
				config_doc.save()
				updated_count += 1
				print(f"✅ Updated: {config['field_name']} - TAT: {config['tat_days']} days")
			else:
				# Create new
				config_doc = frappe.get_doc({
					"doctype": "Welcome Formalities Config",
					"field_name": config["field_name"],
					"tat_days": config["tat_days"]
				})
				config_doc.insert()
				created_count += 1
				print(f"✅ Created: {config['field_name']} - TAT: {config['tat_days']} days")
				
		except Exception as e:
			print(f"❌ Error processing {config['field_name']}: {str(e)}")
			frappe.log_error(f"Error setting up config for {config['field_name']}: {str(e)}", "Welcome Formalities Config Setup Error")
	
	frappe.db.commit()
	
	print("\n" + "=" * 70)
	print(f"Setup Complete!")
	print(f"Created: {created_count} new config records")
	print(f"Updated: {updated_count} existing config records")
	print("=" * 70)
	
	# Verify all configs exist
	print("\nVerifying all config records exist...")
	all_configs = frappe.get_all("Welcome Formalities Config", fields=["field_name", "tat_days"])
	
	if len(all_configs) == len(field_configs):
		print(f"✅ All {len(field_configs)} config records are configured!")
		for config in all_configs:
			print(f"   - {config.field_name}: {config.tat_days} days")
	else:
		configured_fields = {c.field_name for c in all_configs}
		all_fields = {f["field_name"] for f in field_configs}
		missing = all_fields - configured_fields
		if missing:
			print(f"⚠️  Missing config records for: {', '.join(missing)}")
	
	return created_count, updated_count

if __name__ == "__main__":
	setup_welcome_formalities_config()

