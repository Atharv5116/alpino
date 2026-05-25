import frappe

def create_log_doctype():
    if not frappe.db.exists("DocType", "Employee Checkin Log"):
        dt = frappe.get_doc({
            "doctype": "DocType",
            "name": "Employee Checkin Log",
            "module": "Alpinos Development",
            "custom": 1,
            "fields": [
                {"fieldname": "employee", "label": "Employee", "fieldtype": "Link", "options": "Employee", "in_list_view": 1},
                {"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "reqd": 1, "in_list_view": 1},
                {"fieldname": "action", "label": "Action", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "log_type", "label": "Log Type", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "ip_address", "label": "IP Address", "fieldtype": "Data"},
                {"fieldname": "request_path", "label": "Request Path", "fieldtype": "Data"},
                {"fieldname": "details", "label": "Details", "fieldtype": "Text"}
            ],
            "permissions": [
                {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
                {"role": "HR Manager", "read": 1, "write": 1, "create": 1, "delete": 1}
            ]
        })
        dt.insert(ignore_permissions=True)
        print("Created Employee Checkin Log DocType.")

    # auto delete after 30 days
    try:
        log_settings = frappe.get_single('Log Settings')
        exists = False
        for row in log_settings.get("logs_to_clear"):
            if row.ref_doctype == "Employee Checkin Log":
                row.days = 30
                exists = True
                break
        
        if not exists:
            log_settings.append("logs_to_clear", {
                "ref_doctype": "Employee Checkin Log",
                "days": 30
            })
        
        log_settings.save(ignore_permissions=True)
        print("Updated Log Settings for 30-day retention.")
    except Exception as e:
        print(f"Could not setup auto-delete: {e}")

if __name__ == "__main__":
    create_log_doctype()
