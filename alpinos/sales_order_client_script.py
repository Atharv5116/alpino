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
        if (frm.doc.customer) {
            frappe.call({
                method: 'alpinos.sales_order_offline_buyer.get_offline_buyer_for_customer',
                args: { customer: frm.doc.customer },
                callback: function(r) {
                    const m = r.message || {};
                    if (m.customer_type) {
                        frm.set_value('order_type', m.customer_type);
                        frm.set_value('custom_offline_buyer_customer_type', m.customer_type);
                    }
                    if (m.offline_buyer_master) {
                        frm.set_value('custom_offline_buyer_master', m.offline_buyer_master);
                    }
                }
            });
        }
    },

    setup: function(frm) {
        set_variant_item_queries(frm);
    },

    refresh: function(frm) {
        set_variant_item_queries(frm);
        
        if (!frm.is_new()) {
            frm.add_custom_button(__('Pick List'), function() {
                frappe.call({
                    method: 'alpinos.sales_order_api.create_pick_list_from_so',
                    args: { sales_order: frm.doc.name },
                    freeze: true,
                    callback: function(r) {
                        if (r.message) {
                            frappe.set_route('pick_list_entry', r.message);
                        }
                    }
                });
            }, __('Create'));
        }
    },

    custom_cash_discount: function(frm) {
        calculate_cash_discount(frm);
    }
});

frappe.ui.form.on('Sales Order Item', {
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.item_code) return;

        const apply_pricing = function(mrp, margin_percent) {
            frappe.model.set_value(cdt, cdn, 'custom_customer_mrp', flt(mrp));
            frappe.model.set_value(cdt, cdn, 'custom_flat_discount', flt(margin_percent || 0));
            calculate_item_values(frm, cdt, cdn);
        };

        // Fetch MRP + buyer margin from Offline Buyer catalog/master first.
        if (frm.doc.customer) {
            frappe.call({
                method: 'alpinos.sales_order_offline_buyer.get_offline_buyer_item_rate',
                args: { customer: frm.doc.customer, item_code: row.item_code },
                callback: function(r) {
                    if (r.message && flt(r.message.mrp) > 0) {
                        apply_pricing(r.message.mrp, r.message.margin_percent);
                        return;
                    }

                    frappe.call({
                        method: 'alpinos.sales_order_api.get_customer_item_mrp',
                        args: { customer: frm.doc.customer, item_code: row.item_code },
                        callback: function(r2) {
                            if (r2.message) {
                                apply_pricing(r2.message, 0);
                            }
                        }
                    });
                }
            });
        }

        // Fetch Box conversion factor
        frappe.call({
            method: 'alpinos.sales_order_api.get_box_conversion_factor',
            args: { item_code: row.item_code },
            callback: function(r) {
                if (r.message) {
                    row._box_conversion_factor = r.message;
                    if (row.qty) {
                        let boxes = row.qty / r.message;
                        frappe.model.set_value(cdt, cdn, 'custom_box', flt(boxes, 2));
                    }
                }
            }
        });
    },

    qty: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item_code && row.qty) {
            get_box_conversion(row.item_code, function(conversion_factor) {
                if (conversion_factor) {
                    // Business rule: round boxes up; if qty not divisible, bump qty to full boxes.
                    let boxes = Math.ceil(flt(row.qty) / flt(conversion_factor));
                    let adjusted_qty = boxes * flt(conversion_factor);
                    frappe.model.set_value(cdt, cdn, 'custom_box', boxes);
                    if (adjusted_qty !== flt(row.qty)) {
                        frappe.model.set_value(cdt, cdn, 'qty', flt(adjusted_qty, 2));
                    }
                    calculate_item_values(frm, cdt, cdn);
                }
            });
        }
        calculate_item_values(frm, cdt, cdn);
    },

    custom_box: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item_code && row.custom_box) {
            get_box_conversion(row.item_code, function(conversion_factor) {
                if (conversion_factor) {
                    let qty = Math.ceil(flt(row.custom_box)) * flt(conversion_factor);
                    frappe.model.set_value(cdt, cdn, 'custom_box', Math.ceil(flt(row.custom_box)));
                    frappe.model.set_value(cdt, cdn, 'qty', flt(qty, 2));
                    calculate_item_values(frm, cdt, cdn);
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

    custom_offer: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
    },

    custom_additional_discount: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
    },

    items_remove: function(frm) {
        calculate_cash_discount(frm);
    }
});

function get_box_conversion(item_code, callback) {
    frappe.call({
        method: 'alpinos.sales_order_api.get_box_conversion_factor',
        args: { item_code: item_code },
        callback: function(r) {
            callback(r.message || null);
        }
    });
}

function set_variant_item_queries(frm) {
    const q_freebies = function() {
        return {
            filters: {
                disabled: 0,
                is_sales_item: 1,
                has_variants: 0
            }
        };
    };
    const q_variants = function() {
        return {
            filters: {
                disabled: 0,
                is_sales_item: 1,
                variant_of: ['!=', '']
            }
        };
    };
    frm.set_query('item_code', 'items', q_variants);
    frm.set_query('item_code', 'custom_marketing_freebies', q_freebies);
    frm.set_query('item_code', 'custom_scheme_item_table', q_freebies);
    frm.set_query('item_code', 'custom_additional_units_damage_items', q_variants);
}

function calculate_item_values(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    let mrp = flt(row.custom_customer_mrp);
    let qty = flt(row.qty);
    let flat_discount = flt(row.custom_flat_discount);
    let offer_pct = flt(row.custom_offer);
    let additional_discount_pct = flt(row.custom_additional_discount);

    if (mrp > 0 && qty > 0) {
        // Apply offer/additional discounts after flat discount, as percentages on running amount.
        let gross_amount = mrp * qty;
        let flat_discount_amount = gross_amount * flat_discount / 100;
        let after_flat = gross_amount - flat_discount_amount;
        let offer_amount = after_flat * offer_pct / 100;
        let after_offer = after_flat - offer_amount;
        let additional_discount_amount = after_offer * additional_discount_pct / 100;
        let net_amount = after_offer - additional_discount_amount;
        if (net_amount < 0) net_amount = 0;
        let effective_rate = net_amount / qty;
        frappe.model.set_value(cdt, cdn, 'rate', flt(effective_rate, 2));
        frappe.model.set_value(cdt, cdn, 'amount', flt(net_amount, 2));
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
