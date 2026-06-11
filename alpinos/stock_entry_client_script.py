"""
Client Script for Stock Entry customizations:
- Auto set Entry By to logged-in user
- Default item UOM to Nos
- Material Transfer warehouse rules
"""

import frappe


STOCK_ENTRY_CLIENT_SCRIPT = """
frappe.ui.form.on('Stock Entry', {
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.custom_entry_by) {
            frm.set_value('custom_entry_by', frappe.session.user);
        }
        apply_material_transfer_rules(frm);
    },

    refresh: function(frm) {
        apply_material_transfer_rules(frm);
    },

    stock_entry_type: function(frm) {
        apply_material_transfer_rules(frm);
    },

    from_warehouse: function(frm) {
        sync_item_warehouses_from_header(frm);
    },

    to_warehouse: function(frm) {
        sync_item_warehouses_from_header(frm);
    },

    items_add: function(frm) {
        sync_item_warehouses_from_header(frm);
    }
});

frappe.ui.form.on('Stock Entry Detail', {
    item_code: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;

        // Qty should be treated as Nos by default.
        frappe.model.set_value(cdt, cdn, 'uom', 'Nos');
    }
});

function is_material_transfer(frm) {
    return frm.doc.stock_entry_type === 'Material Transfer';
}

function apply_material_transfer_rules(frm) {
    const mt = is_material_transfer(frm);

    // Header fields must be mandatory for Material Transfer only.
    frm.toggle_reqd('from_warehouse', mt);
    frm.toggle_reqd('to_warehouse', mt);

    // Hide item-level source/target warehouses and force header-driven values.
    if (frm.fields_dict.items && frm.fields_dict.items.grid) {
        frm.fields_dict.items.grid.update_docfield_property('s_warehouse', 'hidden', mt ? 1 : 0);
        frm.fields_dict.items.grid.update_docfield_property('t_warehouse', 'hidden', mt ? 1 : 0);
        frm.refresh_field('items');
    }

    if (mt) {
        sync_item_warehouses_from_header(frm);
    }
}

function sync_item_warehouses_from_header(frm) {
    if (!is_material_transfer(frm)) return;

    (frm.doc.items || []).forEach((row) => {
        if (frm.doc.from_warehouse && row.s_warehouse !== frm.doc.from_warehouse) {
            frappe.model.set_value(row.doctype, row.name, 's_warehouse', frm.doc.from_warehouse);
        }
        if (frm.doc.to_warehouse && row.t_warehouse !== frm.doc.to_warehouse) {
            frappe.model.set_value(row.doctype, row.name, 't_warehouse', frm.doc.to_warehouse);
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
