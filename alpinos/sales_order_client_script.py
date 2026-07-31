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
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.custom_dispatch_date) {
            _set_default_dispatch_date(frm);
        }
    },

    custom_dispatch_date: function(frm) {
        if (!frm.doc.custom_dispatch_date) return;
        frappe.call({
            method: 'alpinos.dispatch_date_utils.validate_dispatch_date',
            args: { date: frm.doc.custom_dispatch_date },
            callback: function(r) {
                if (r.message && !r.message.valid) {
                    frappe.msgprint({
                        title: __('Invalid Dispatch Date'),
                        message: __(r.message.message),
                        indicator: 'red'
                    });
                    frm.set_value('custom_dispatch_date', '');
                }
            }
        });
    },

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
            frm.add_custom_button(__('Fetch PO PDF'), function() {
                if (!frm.doc.custom_po_no_for_pdf) {
                    frappe.msgprint(__('Set "PO No for PDF" first.'));
                    return;
                }
                _fetch_po_pdf(frm);
            });
        }
        
        if (!frm.is_new()) {
            frappe.call({
                method: 'alpinos.sales_order_api.get_so_pick_list_status',
                args: { sales_order: frm.doc.name },
                callback: function(r) {
                    const status = r.message || {};
                    frm.remove_custom_button(__('Create'), __('Pick List'));
                    frm.remove_custom_button(__('Edit'), __('Pick List'));
                    frm.remove_custom_button(__('Pick List'));

                    if (status.fully_picked) {
                        // All items fully picked — no button needed
                        return;
                    }

                    if (status.has_draft) {
                        // Draft pick list exists — allow editing it
                        frm.add_custom_button(__('Edit'), function() {
                            frappe.set_route('pick_list_entry', status.draft_name);
                        }, __('Pick List'));
                    } else if (status.has_pick_list) {
                        // A submitted pick list exists but not fully picked — don't allow creating new
                        // (no button shown)
                    } else {
                        // No pick list at all — allow creating
                        frm.add_custom_button(__('Create'), function() {
                            frappe.route_options = { "so_name": frm.doc.name };
                            frappe.set_route('pick_list_entry', 'New Pick List');
                        }, __('Pick List'));
                    }
                }
            });
        }
    },

    custom_cash_discount: function(frm) {
        calculate_cash_discount(frm);
    },

    // Leaving the field fetches the PO PDF from the folder configured in
    // Alpino General Settings (file name = this value + .pdf).
    custom_po_no_for_pdf: function(frm) {
        if (frm.doc.custom_po_no_for_pdf && !frm.is_new()) {
            _fetch_po_pdf(frm);
        }
    }
});

function _fetch_po_pdf(frm) {
    frappe.call({
        method: 'alpinos.po_pdf.fetch_po_pdf',
        args: {
            sales_order: frm.doc.name,
            po_no_for_pdf: frm.doc.custom_po_no_for_pdf || ''
        },
        freeze: true,
        freeze_message: __('Fetching PO PDF...'),
        callback: function(r) {
            if (r.message && r.message.file_url) {
                frappe.show_alert({ message: __('PO PDF attached: {0}', [r.message.file_name]), indicator: 'green' }, 5);
                frm.reload_doc();
            }
        }
    });
}

frappe.ui.form.on('Sales Order Item', {
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.item_code) return;

        const apply_pricing = function(mrp, margin_percent, rate) {
            frappe.model.set_value(cdt, cdn, 'custom_customer_mrp', flt(mrp));
            frappe.model.set_value(cdt, cdn, 'custom_flat_discount', flt(margin_percent || 0));
            frappe.model.set_value(cdt, cdn, 'custom_selling_price', flt(rate || (mrp * (1 - (margin_percent || 0) / 100))));
            calculate_item_values(frm, cdt, cdn);
        };

        // Fetch MRP + buyer margin from Offline Buyer catalog/master first.
        if (frm.doc.customer) {
            frappe.call({
                method: 'alpinos.sales_order_offline_buyer.get_offline_buyer_item_rate',
                args: { customer: frm.doc.customer, item_code: row.item_code },
                callback: function(r) {
                    if (r.message && flt(r.message.mrp) > 0) {
                        apply_pricing(r.message.mrp, r.message.margin_percent, r.message.rate);
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

    custom_selling_price: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn, true);
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
        // Variants OR bundles (bundles have empty variant_of); templates stay hidden.
        // Gate by the order's customer type so only items that allow it appear.
        const ct = frm.doc.custom_offline_buyer_customer_type;
        return {
            query: 'alpinos.offline_buyer_api.sellable_item_link_query',
            filters: ct ? { customer_type: ct } : {}
        };
    };
    frm.set_query('item_code', 'items', q_variants);
    frm.set_query('item_code', 'custom_marketing_freebies', q_freebies);
    frm.set_query('item_code', 'custom_scheme_item_table', q_freebies);
    frm.set_query('item_code', 'custom_additional_units_damage_items', q_variants);
}

function calculate_item_values(frm, cdt, cdn, selling_price_edited) {
    let row = locals[cdt][cdn];
    let mrp = flt(row.custom_customer_mrp);
    let qty = flt(row.qty);
    let flat_discount = flt(row.custom_flat_discount);
    let offer_pct = flt(row.custom_offer);
    let additional_discount_pct = flt(row.custom_additional_discount);

    let selling_price = flt(row.custom_selling_price);

    if (!selling_price_edited) {
        // Recalculate Selling Price (price after flat and offer discounts)
        selling_price = mrp * (1 - flat_discount / 100) * (1 - offer_pct / 100);
        frappe.model.set_value(cdt, cdn, 'custom_selling_price', flt(selling_price, 2));
    }

    if (selling_price > 0 && qty > 0) {
        // Apply additional discount directly on selling price
        let gross_amount = selling_price * qty;
        let additional_discount_amount = gross_amount * additional_discount_pct / 100;
        let net_amount = gross_amount - additional_discount_amount;
        if (net_amount < 0) net_amount = 0;
        let effective_rate = net_amount / qty;
        frappe.model.set_value(cdt, cdn, 'rate', flt(effective_rate, 2));
        frappe.model.set_value(cdt, cdn, 'amount', flt(net_amount, 2));
    }
}

function _set_default_dispatch_date(frm) {
    frappe.call({
        method: 'alpinos.dispatch_date_utils.get_default_dispatch_date',
        callback: function(r) {
            if (r.message && r.message.date) {
                frm.set_value('custom_dispatch_date', r.message.date);
            }
        }
    });
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
