import frappe

def execute():
    leave_applications = frappe.get_all(
        "Leave Application",
        filters={
            "docstatus": 1,
            "status": "Approved"
        },
        fields=["name"]
    )

    fixed_count = 0

    # regenerate ledger entries for approved applications that are missing them
    for la in leave_applications:
        has_ledger = frappe.db.exists(
            "Leave Ledger Entry",
            {
                "transaction_type": "Leave Application",
                "transaction_name": la.name
            }
        )

        if not has_ledger:
            doc = frappe.get_doc("Leave Application", la.name)
            try:
                doc.create_leave_ledger_entry(submit=True)
                frappe.db.commit()
                fixed_count += 1
                print(f"Generated missing ledger entry for: {la.name}")
            except Exception as e:
                frappe.db.rollback()
                print(f"Failed to fix {la.name}: {str(e)}")

    print(f"Done! Total missing ledger entries fixed: {fixed_count}")
