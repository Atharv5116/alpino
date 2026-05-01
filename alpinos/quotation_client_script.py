"""
Client Script for Quotation custom calculations.
"""

import frappe


QUOTATION_CLIENT_SCRIPT = """
frappe.ui.form.on('Quotation', {
    onload: function(frm) {
        toggle_partial_payment_fields(frm);
        enforce_percentage_discounts(frm);
    },

    custom_cash_discount: function(frm) {
        recalculate_quotation_totals(frm);
    },

    custom_advance_amount: function(frm) {
        recalculate_quotation_totals(frm);
    },

    custom_payment_mode: function(frm) {
        toggle_partial_payment_fields(frm);
    }
});

frappe.ui.form.on('Quotation Item', {
    item_code: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;

        frappe.db.get_value('Item', row.item_code, 'item_name')
            .then((r) => {
                if (r && r.message && r.message.item_name) {
                    frappe.model.set_value(cdt, cdn, 'item_name', r.message.item_name);
                }
            });

        if (frm.doc.party_name) {
            frappe.call({
                method: 'alpinos.sales_order_api.get_customer_item_mrp',
                args: {
                    customer: frm.doc.party_name,
                    item_code: row.item_code
                },
                callback: function(r) {
                    if (r.message) {
                        locals[cdt][cdn].custom_mrp = flt(r.message);
                        frm.refresh_field('items');
                        recalculate_row_values(frm, cdt, cdn);
                    }
                }
            });
        }
    },

    qty: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const int_qty = Math.round(flt(row.qty));
        if (row.qty !== int_qty) {
            frappe.model.set_value(cdt, cdn, 'qty', int_qty);
            return;
        }
        update_boxes_from_qty(cdt, cdn);
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_boxes: function(frm, cdt, cdn) {
        update_qty_from_boxes(cdt, cdn);
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_mrp: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_discount_type: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_flat_discount: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_offer: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_additional_discount_type: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_additional_discount: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_item_tax_percent: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    items_remove: function(frm) {
        recalculate_quotation_totals(frm);
    }
});

function get_conversion_factor(item_code, callback) {
    if (!item_code) {
        callback(null);
        return;
    }
    frappe.call({
        method: 'alpinos.sales_order_api.get_box_conversion_factor',
        args: { item_code: item_code },
        callback: function(r) {
            callback(r.message || null);
        }
    });
}

function update_boxes_from_qty(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code || !row.qty) return;

    get_conversion_factor(row.item_code, function(factor) {
        if (!factor) return;
        frappe.model.set_value(cdt, cdn, 'custom_boxes', flt(row.qty / factor, 0));
    });
}

function update_qty_from_boxes(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code || !row.custom_boxes) return;

    get_conversion_factor(row.item_code, function(factor) {
        if (!factor) return;
        frappe.model.set_value(cdt, cdn, 'qty', flt(row.custom_boxes * factor, 2));
    });
}

function recalculate_row_values(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const qty = flt(row.qty);
    const mrp = flt(row.custom_mrp);

    // If MRP is not set yet, leave rate/amount untouched so user can still enter manually.
    if (!mrp) {
        recalculate_quotation_totals(frm);
        return;
    }

    const gross = qty * mrp;

    const discount_type = row.custom_discount_type || 'Percentage';
    const flat_discount_input = flt(row.custom_flat_discount);
    let flat_discount_amount = 0;
    if (discount_type === 'Percentage') {
        flat_discount_amount = gross * flat_discount_input / 100.0;
    } else {
        flat_discount_amount = flat_discount_input;
    }

    const offer_amount = gross * flt(row.custom_offer) / 100.0;
    const after_offer = gross - flat_discount_amount - offer_amount;

    const additional_type = 'Percentage';
    const additional_input = flt(row.custom_additional_discount);
    let additional_amount = 0;
    additional_amount = after_offer * additional_input / 100.0;

    let taxable = after_offer - additional_amount;
    if (taxable < 0) taxable = 0;

    const tax_percent = flt(row.custom_item_tax_percent);
    const tax_amount = taxable * tax_percent / 100.0;

    const new_rate = qty ? flt(taxable / qty, 2) : 0;

    // Write directly to locals to avoid triggering ERPNext's async rate→calculate chain
    // which can race-condition and reset amount to 0 using stale values.
    row.custom_item_tax = flt(tax_amount, 2);
    row.rate = new_rate;
    row.amount = flt(taxable, 2);
    row.base_rate = new_rate;
    row.base_amount = flt(taxable, 2);

    frm.refresh_field('items');
    recalculate_quotation_totals(frm);
}

function recalculate_quotation_totals(frm) {
    const rows = frm.doc.items || [];
    let sub_total = 0;
    let over_discount = 0;
    let additional_discount = 0;
    let gst = 0;

    rows.forEach((row) => {
        const qty = flt(row.qty);
        const mrp = flt(row.custom_mrp);
        const gross = qty * mrp;
        sub_total += gross;

        const flat_input = flt(row.custom_flat_discount);
        if ((row.custom_discount_type || 'Percentage') === 'Percentage') {
            over_discount += gross * flat_input / 100.0;
        } else {
            over_discount += flat_input;
        }

        const offer_pct = flt(row.custom_offer);
        const offer_amt = gross * offer_pct / 100.0;
        const after_offer = gross - ((row.custom_discount_type || 'Percentage') === 'Percentage' ? (gross * flat_input / 100.0) : flat_input) - offer_amt;
        const add_input = flt(row.custom_additional_discount);
        additional_discount += after_offer * add_input / 100.0;

        gst += flt(row.custom_item_tax);
    });

    const cash_discount_pct = flt(frm.doc.custom_cash_discount);
    const pre_cash_total = sub_total - over_discount - additional_discount + gst;
    const cash_discount_amount = pre_cash_total > 0 ? pre_cash_total * cash_discount_pct / 100.0 : 0;
    const final_total = pre_cash_total - cash_discount_amount;
    const advance = flt(frm.doc.custom_advance_amount);
    const remaining = final_total - advance;

    frm.set_value('custom_sub_total', flt(sub_total, 2));
    frm.set_value('custom_over_discount', flt(over_discount, 2));
    frm.set_value('custom_additional_discount_total', flt(additional_discount, 2));
    frm.set_value('custom_gst_total', flt(gst, 2));
    frm.set_value('custom_total_payable', flt(final_total, 2));
    frm.set_value('custom_remaining_amount', flt(remaining, 2));
    frm.set_value('total', flt(final_total, 2));
    frm.set_value('grand_total', flt(final_total, 2));
}

function toggle_partial_payment_fields(frm) {
    const is_partial = frm.doc.custom_payment_mode === 'Partial';
    frm.toggle_display('custom_advance_amount', is_partial);
    frm.toggle_reqd('custom_advance_amount', is_partial);
    frm.toggle_display('custom_attachment_proof', is_partial);
    frm.toggle_reqd('custom_attachment_proof', is_partial);
}

function enforce_percentage_discounts(frm) {
    (frm.doc.items || []).forEach((row) => {
        if (row.custom_additional_discount_type !== 'Percentage') {
            frappe.model.set_value(row.doctype, row.name, 'custom_additional_discount_type', 'Percentage');
        }
    });
    frm.set_df_property('custom_additional_discount_type', 'read_only', 1);
}
"""


def create_quotation_client_script():
	"""Create or update client script for Quotation"""
	script_name = "Quotation - Alpinos Customization"
	existing = frappe.db.exists("Client Script", {"name": script_name})

	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = QUOTATION_CLIENT_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Quotation",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": QUOTATION_CLIENT_SCRIPT,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
