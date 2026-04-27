"""
Client Script for Opportunity custom flow:
- SKU (Item) link driven row setup
- Qty <-> Boxes conversion
- Item discount/tax amount handling
- Header totals calculation
"""

import frappe


OPPORTUNITY_CLIENT_SCRIPT = """
frappe.ui.form.on('Opportunity', {
    setup: function(frm) {
        // opportunity_from is Link -> DocType (not Select). Options must remain "DocType" in meta.
        // Restrict picker to standard party types plus Offline Buyer Master (same pattern as erpnext opportunity.js).
        frm.set_query('opportunity_from', function () {
            return {
                filters: {
                    name: ['in', ['Customer', 'Lead', 'Prospect', 'Offline Buyer Master']],
                },
            };
        });
    },

    onload: function(frm) {
        if (frm.is_new() && !frm.doc.opportunity_owner) {
            frm.set_value('opportunity_owner', frappe.session.user);
        }
    },

    custom_cash_discount: function(frm) {
        recalculate_opportunity_totals(frm);
    }
});

frappe.ui.form.on('Opportunity Item', {
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
                        frappe.model.set_value(cdt, cdn, 'custom_mrp', flt(r.message));
                    }
                }
            });
        }
    },

    qty: function(frm, cdt, cdn) {
        update_boxes_from_qty(frm, cdt, cdn);
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_boxes: function(frm, cdt, cdn) {
        update_qty_from_boxes(frm, cdt, cdn);
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_mrp: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_flat_discount: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_additional_discount: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_item_tax: function(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    items_remove: function(frm) {
        recalculate_opportunity_totals(frm);
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

function update_boxes_from_qty(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code || !row.qty) return;

    get_conversion_factor(row.item_code, function(factor) {
        if (!factor) return;
        frappe.model.set_value(cdt, cdn, 'custom_boxes', flt(row.qty / factor, 2));
    });
}

function update_qty_from_boxes(frm, cdt, cdn) {
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
    const flat_discount_pct = flt(row.custom_flat_discount);
    const offer_pct = flt(row.custom_offer);
    const additional_discount_pct = flt(row.custom_additional_discount);

    const gross_amount = qty * mrp;
    const flat_discount_amount = gross_amount * flat_discount_pct / 100.0;
    const after_flat = gross_amount - flat_discount_amount;
    const offer_amount = after_flat * offer_pct / 100.0;
    const after_offer = after_flat - offer_amount;
    const additional_discount_amount = after_offer * additional_discount_pct / 100.0;
    let net_amount = after_offer - additional_discount_amount;
    if (net_amount < 0) net_amount = 0;

    frappe.model.set_value(cdt, cdn, 'rate', qty ? flt(net_amount / qty, 2) : 0);
    frappe.model.set_value(cdt, cdn, 'amount', flt(net_amount, 2));
    frappe.model.set_value(cdt, cdn, 'base_amount', flt(net_amount, 2));

    recalculate_opportunity_totals(frm);
}

function recalculate_opportunity_totals(frm) {
    const rows = frm.doc.items || [];
    let sub_total = 0.0;
    let over_discount_total = 0.0;
    let additional_discount_total = 0.0;
    let gst_total = 0.0;

    rows.forEach((row) => {
        const qty = flt(row.qty);
        const mrp = flt(row.custom_mrp);
        const flat_discount_pct = flt(row.custom_flat_discount);
        const offer_pct = flt(row.custom_offer);
        const additional_discount_pct = flt(row.custom_additional_discount);
        const item_tax = flt(row.custom_item_tax);

        const gross = qty * mrp;
        const after_flat = gross - (gross * flat_discount_pct / 100.0);
        const offer_amount = after_flat * offer_pct / 100.0;
        const after_offer = after_flat - offer_amount;
        const additional_discount = after_offer * additional_discount_pct / 100.0;
        sub_total += gross;
        over_discount_total += gross * flat_discount_pct / 100.0;
        additional_discount_total += additional_discount;
        gst_total += item_tax;
    });

    const cash_discount_pct = flt(frm.doc.custom_cash_discount);
    const pre_cash_total = sub_total - over_discount_total - additional_discount_total + gst_total;
    const cash_discount_amount = pre_cash_total > 0 ? pre_cash_total * cash_discount_pct / 100.0 : 0;
    const final_total = pre_cash_total - cash_discount_amount;

    frm.set_value('custom_over_discount', flt(over_discount_total, 2));
    frm.set_value('custom_additional_discount_total', flt(additional_discount_total, 2));
    frm.set_value('custom_gst_total', flt(gst_total, 2));
    frm.set_value('total', flt(final_total, 2));
    frm.set_value('opportunity_amount', flt(final_total, 2));
}
"""


def create_opportunity_client_script():
	"""Create or update client script for Opportunity"""
	script_name = "Opportunity - Alpinos Customization"
	existing = frappe.db.exists("Client Script", {"name": script_name})

	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = OPPORTUNITY_CLIENT_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Opportunity",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": OPPORTUNITY_CLIENT_SCRIPT,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
