"""
Client Script for Stock Entry customizations:
- Auto set Entry By to logged-in user
- Keep qty in Nos and synchronize Box <-> Qty
"""

import frappe


STOCK_ENTRY_CLIENT_SCRIPT = """
frappe.ui.form.on('Stock Entry', {
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.custom_entry_by) {
            frm.set_value('custom_entry_by', frappe.session.user);
        }
    }
});

frappe.ui.form.on('Stock Entry Detail', {
    item_code: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;

        // Qty should be treated as Nos by default.
        frappe.model.set_value(cdt, cdn, 'uom', 'Nos');

        get_conversion_factor(row.item_code, function(factor) {
            if (!factor || !row.qty) return;
            const boxes = Math.ceil(flt(row.qty) / flt(factor));
            frappe.model.set_value(cdt, cdn, 'custom_box', boxes);
            frappe.model.set_value(cdt, cdn, 'qty', flt(boxes * factor, 2));
        });
    },

    qty: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code || !row.qty) return;

        get_conversion_factor(row.item_code, function(factor) {
            if (!factor) return;
            const boxes = Math.ceil(flt(row.qty) / flt(factor));
            frappe.model.set_value(cdt, cdn, 'custom_box', boxes);
            frappe.model.set_value(cdt, cdn, 'qty', flt(boxes * factor, 2));
        });
    },

    custom_box: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code || !row.custom_box) return;

        get_conversion_factor(row.item_code, function(factor) {
            if (!factor) return;
            const boxes = Math.ceil(flt(row.custom_box));
            frappe.model.set_value(cdt, cdn, 'custom_box', boxes);
            frappe.model.set_value(cdt, cdn, 'qty', flt(boxes * factor, 2));
        });
    }
});

function get_conversion_factor(item_code, callback) {
    frappe.call({
        method: 'alpinos.sales_order_api.get_box_conversion_factor',
        args: { item_code: item_code },
        callback: function(r) {
            callback(r.message || null);
        }
    });
}
"""


def create_stock_entry_client_script():
	"""Create or update client script for Stock Entry"""
	script_name = "Stock Entry - Alpinos Customization"
	existing = frappe.db.exists("Client Script", {"name": script_name})

	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = STOCK_ENTRY_CLIENT_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Stock Entry",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": STOCK_ENTRY_CLIENT_SCRIPT,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
