"""
Client Script for Sales Order customizations:
- Auto-fetch Order Type from Customer master
- Auto-fetch MRP from Customer Item MRP table
- Units ↔ Boxes auto-calculation using Item UOM conversion factor
- Flat Discount calculation based on MRP
- Cash Discount calculation
"""

import frappe

SALES_ORDER_CLIENT_SCRIPT = """
frappe.ui.form.on('Sales Order', {
    customer: function(frm) {
        // Auto-fetch Order Type from Customer master
        if (frm.doc.customer) {
            frappe.db.get_value('Customer', frm.doc.customer, 'custom_order_type', function(r) {
                if (r && r.custom_order_type) {
                    frm.set_value('order_type', r.custom_order_type);
                }
            });
        }
    },

    custom_cash_discount: function(frm) {
        calculate_cash_discount(frm);
    }
});

frappe.ui.form.on('Sales Order Item', {
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item_code && frm.doc.customer) {
            // Fetch MRP from Customer Item MRP table
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Customer Item MRP',
                    filters: {
                        parent: frm.doc.customer,
                        parenttype: 'Customer',
                        item_code: row.item_code
                    },
                    fields: ['mrp'],
                    limit_page_length: 1
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        frappe.model.set_value(cdt, cdn, 'custom_customer_mrp', r.message[0].mrp);
                    }
                }
            });

            // Fetch Box conversion factor from Item UOM table
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'UOM Conversion Detail',
                    filters: {
                        parent: row.item_code,
                        parenttype: 'Item',
                        uom: 'Box'
                    },
                    fields: ['conversion_factor'],
                    limit_page_length: 1
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        // Store conversion factor for later use
                        row._box_conversion_factor = r.message[0].conversion_factor;
                        // If qty is set, calculate boxes
                        if (row.qty) {
                            let boxes = row.qty / r.message[0].conversion_factor;
                            frappe.model.set_value(cdt, cdn, 'custom_box', flt(boxes, 2));
                        }
                    }
                }
            });
        }
    },

    qty: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        // Auto-calculate boxes from qty
        if (row.item_code && row.qty) {
            get_box_conversion(row.item_code, function(conversion_factor) {
                if (conversion_factor) {
                    let boxes = row.qty / conversion_factor;
                    frappe.model.set_value(cdt, cdn, 'custom_box', flt(boxes, 2));
                }
            });
        }
    },

    custom_box: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        // Auto-calculate qty from boxes
        if (row.item_code && row.custom_box) {
            get_box_conversion(row.item_code, function(conversion_factor) {
                if (conversion_factor) {
                    let qty = row.custom_box * conversion_factor;
                    frappe.model.set_value(cdt, cdn, 'qty', flt(qty, 2));
                }
            });
        }
    },

    custom_customer_mrp: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
    },

    custom_flat_discount: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
    },

    custom_additional_discount: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
    }
});

function get_box_conversion(item_code, callback) {
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'UOM Conversion Detail',
            filters: {
                parent: item_code,
                parenttype: 'Item',
                uom: 'Box'
            },
            fields: ['conversion_factor'],
            limit_page_length: 1
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                callback(r.message[0].conversion_factor);
            } else {
                callback(null);
            }
        }
    });
}

function calculate_item_values(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    let mrp = flt(row.custom_customer_mrp);
    let flat_discount = flt(row.custom_flat_discount);
    let additional_discount = flt(row.custom_additional_discount);

    if (mrp > 0) {
        // Rate = MRP - Flat Discount - Additional Discount
        let effective_rate = mrp - flat_discount - additional_discount;
        if (effective_rate < 0) effective_rate = 0;
        frappe.model.set_value(cdt, cdn, 'rate', effective_rate);
    }
}

function calculate_cash_discount(frm) {
    let cash_discount_pct = flt(frm.doc.custom_cash_discount);
    let grand_total = flt(frm.doc.grand_total);

    if (cash_discount_pct > 0 && grand_total > 0) {
        let discount_amount = grand_total * cash_discount_pct / 100;
        frm.set_value('custom_cash_discount_amount', flt(discount_amount, 2));
    } else {
        frm.set_value('custom_cash_discount_amount', 0);
    }
}
"""


def create_sales_order_client_script():
	"""Create or update client script for Sales Order"""
	script_name = "Sales Order - Alpinos Customization"

	existing = frappe.db.exists("Client Script", {"name": script_name})

	if existing:
		doc = frappe.get_doc("Client Script", script_name)
		doc.script = SALES_ORDER_CLIENT_SCRIPT
		doc.save(ignore_permissions=True)
		print(f"✅ Updated client script: {script_name}")
	else:
		doc = frappe.get_doc({
			"doctype": "Client Script",
			"name": script_name,
			"dt": "Sales Order",
			"script": SALES_ORDER_CLIENT_SCRIPT,
			"enabled": 1,
			"module": "Alpinos Development",
		})
		doc.insert(ignore_permissions=True)
		print(f"✅ Created client script: {script_name}")

	frappe.db.commit()
