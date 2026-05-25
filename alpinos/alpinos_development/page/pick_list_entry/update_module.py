import frappe

def update():
    fields = [
        "Stock Entry-custom_customer_type",
        "Pick List Item-custom_batch_code",
        "Pick List Item-custom_box",
        "Pick List Item-custom_sample_quantity",
        "Pick List Item-custom_mfg_date",
        "Pick List Item-custom_expiry_date"
    ]
    for f in fields:
        if frappe.db.exists("Custom Field", f):
            frappe.db.set_value("Custom Field", f, "module", "Alpinos Development")
    frappe.db.commit()
