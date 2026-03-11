import frappe

def execute():
    # 1. Get all Leave Applications that are Submitted and Approved
    leave_applications = frappe.get_all(
        "Leave Application",
        filters={
            "docstatus": 1,
            "status": "Approved"
        },
        fields=["name"]
    )

    fixed_count = 0

    # 2. Iterate through them to see which ones are missing ledger entries
    for la in leave_applications:
        # Check if any Leave Ledger Entry exists linked to this application
        has_ledger = frappe.db.exists(
            "Leave Ledger Entry",
            {
                "transaction_type": "Leave Application",
                "transaction_name": la.name
            }
        )

        # 3. If no ledger entry exists, we trigger it manually
        if not has_ledger:
            doc = frappe.get_doc("Leave Application", la.name)
            try:
                # Call Frappe's native function to generate the ledger entry
                doc.create_leave_ledger_entry(submit=True)
                frappe.db.commit()
                fixed_count += 1
                print(f"Generated missing ledger entry for: {la.name}")
            except Exception as e:
                frappe.db.rollback()
                print(f"Failed to fix {la.name}: {str(e)}")

    print(f"Done! Total missing ledger entries fixed: {fixed_count}")
