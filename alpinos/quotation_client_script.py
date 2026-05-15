"""
Client Script for Quotation custom calculations.
"""

import frappe


QUOTATION_CLIENT_SCRIPT = """
frappe.ui.form.on('Quotation', {
    setup(frm) {
        frm.set_query('quotation_to', () => ({
            filters: { name: ['in', ['Customer', 'Lead', 'Prospect', 'Offline Buyer Master']] },
        }));
        frm.set_query('party_name', () => {
            if (frm.doc.quotation_to === 'Offline Buyer Master') {
                return { filters: { customer: ['!=', ''] } };
            }
            return {};
        });
        set_variant_item_queries(frm);
    },

    onload(frm) {
        disable_rounded_total(frm);
        toggle_payment_fields(frm);
        enforce_percentage_discounts(frm);
        apply_quotation_party_layout(frm);
        setTimeout(() => apply_quotation_address_queries(frm), 0);
    },

    refresh(frm) {
        disable_rounded_total(frm);
        toggle_payment_fields(frm);
        enforce_percentage_discounts(frm);
        apply_quotation_party_layout(frm);
        setTimeout(() => {
            fix_dynamic_link_for_obm(frm);
            apply_quotation_address_queries(frm);
        }, 0);
    },

    quotation_to(frm) {
        apply_quotation_party_layout(frm);
        setTimeout(() => apply_quotation_address_queries(frm), 0);
    },

    party_name(frm) {
        if (frm.doc.quotation_to === 'Offline Buyer Master') {
            sync_obm_quotation_header(frm);
        } else if (frm.doc.quotation_to === 'Customer' && frm.doc.party_name) {
            frappe.db.get_value('Customer', frm.doc.party_name, 'custom_order_type', (r) => {
                if (r && r.custom_order_type) {
                    frm.set_value('order_type', r.custom_order_type);
                }
            });
            frappe.model.set_value(frm.doctype, frm.doc.name, 'custom_resolved_customer', frm.doc.party_name);
        } else {
            frappe.model.set_value(frm.doctype, frm.doc.name, 'custom_resolved_customer', '');
        }
    },

    custom_cash_discount(frm) {
        recalculate_quotation_totals(frm);
    },

    custom_advance_amount(frm) {
        recalculate_quotation_totals(frm);
    },

    custom_payment_mode(frm) {
        toggle_payment_fields(frm);
    },
});

function disable_rounded_total(frm) {
    if (frm.fields_dict.disable_rounded_total && !frm.doc.disable_rounded_total) {
        frm.set_value('disable_rounded_total', 1);
    }
}

function fix_dynamic_link_for_obm(frm) {
    // ERPNext's QuotationController.refresh() sets frappe.dynamic_link.doctype to
    // "Offline Buyer Master", which causes SQL errors ("Unknown column 'offline_buyer_master'")
    // in Address/Contact queries. Reset to "Customer" using the resolved customer.
    if (
        frm.doc.quotation_to === 'Offline Buyer Master' &&
        frappe.dynamic_link &&
        frappe.dynamic_link.doctype === 'Offline Buyer Master'
    ) {
        const resolved = frm.doc.custom_resolved_customer || frm.doc.party_name;
        frappe.dynamic_link = {
            doc: frm.doc,
            fieldname: 'party_name',
            doctype: 'Customer',
        };
        if (resolved) {
            frappe.dynamic_link.doc = Object.assign({}, frm.doc, {
                quotation_to: 'Customer',
                party_name: resolved,
            });
        }
    }
}

function apply_quotation_party_layout(frm) {
    const obm = frm.doc.quotation_to === 'Offline Buyer Master';
    if (obm) {
        frm.set_df_property('party_name', 'label', __('Offline Buyer Master'));
        if (frm.doc.party_name) {
            sync_obm_quotation_header(frm);
        }
    }
}

function apply_quotation_address_queries(frm) {
    const customer_addr = (link_name) => ({
        query: 'frappe.contacts.doctype.address.address.address_query',
        filters: { link_doctype: 'Customer', link_name },
    });

    const dynamic_party_addr = () => ({
        query: 'frappe.contacts.doctype.address.address.address_query',
        filters: {
            link_doctype: frm.doc.quotation_to,
            link_name: frm.doc.party_name,
        },
    });

    if (frm.doc.quotation_to === 'Customer' && frm.doc.party_name) {
        frm.set_query('customer_address', () => customer_addr(frm.doc.party_name));
        frm.set_query('shipping_address_name', () => customer_addr(frm.doc.party_name));
        return;
    }
    if (frm.doc.quotation_to === 'Offline Buyer Master' && frm.doc.custom_resolved_customer) {
        frm.set_query('customer_address', () =>
            customer_addr(frm.doc.custom_resolved_customer)
        );
        frm.set_query('shipping_address_name', () =>
            customer_addr(frm.doc.custom_resolved_customer)
        );
        return;
    }

    frm.set_query('customer_address', dynamic_party_addr);
    frm.set_query('shipping_address_name', dynamic_party_addr);
}

function sync_obm_quotation_header(frm) {
    const name = frm.doc.party_name;
    if (!name) {
        frappe.model.set_value(frm.doctype, frm.doc.name, 'customer_name', '');
        frappe.model.set_value(frm.doctype, frm.doc.name, 'custom_resolved_customer', '');
        return;
    }
    frappe.call({
        method: 'alpinos.sales_order_api.get_opportunity_obm_party_data',
        args: { offline_buyer_master: name },
        callback(r) {
            const d = r.message || {};
            if (d.customer_business_name) {
                frappe.model.set_value(frm.doctype, frm.doc.name, 'customer_name', d.customer_business_name);
            } else {
                frappe.model.set_value(frm.doctype, frm.doc.name, 'customer_name', '');
            }
            if (d.customer_type) {
                frm.set_value('order_type', d.customer_type);
            }
            if (d.payment_term) {
                frm.set_value('custom_payment_mode', map_obm_payment_mode(d.payment_term));
            }
            if (d.customer) {
                frappe.model.set_value(frm.doctype, frm.doc.name, 'custom_resolved_customer', d.customer);
                // Auto-populate billing & shipping address from OBM
                frappe.call({
                    method: 'alpinos.sales_order_offline_buyer.sync_offline_buyer_master_addresses',
                    args: { customer: d.customer },
                    callback(r2) {
                        const ad = r2.message || {};
                        if (ad.default_billing && !frm.doc.customer_address) {
                            frm.set_value('customer_address', ad.default_billing);
                        }
                        if (ad.default_shipping && !frm.doc.shipping_address_name) {
                            frm.set_value('shipping_address_name', ad.default_shipping);
                        }
                        setTimeout(() => apply_quotation_address_queries(frm), 0);
                    },
                });
            }
        },
    });
}

function map_obm_payment_mode(payment_term) {
    if (payment_term === 'Credit') return 'Debit';
    if (payment_term === 'Partial') return 'Partial';
    return 'Advance';
}

frappe.ui.form.on('Quotation Item', {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;

        frappe.db.get_value('Item', row.item_code, 'item_name').then((r) => {
            if (r && r.message && r.message.item_name) {
                frappe.model.set_value(cdt, cdn, 'item_name', r.message.item_name);
            }
        });

        const pf = frm.doc.quotation_to;
        const pn = frm.doc.party_name;
        if (row.qty) update_boxes_from_qty(cdt, cdn);
        if (row.custom_boxes) update_qty_from_boxes(cdt, cdn);
        if (!pf || !pn) return;

        frappe.call({
            method: 'alpinos.sales_order_api.get_opportunity_line_pricing',
            args: {
                opportunity_from: pf,
                party_name: pn,
                item_code: row.item_code,
            },
            callback(r) {
                const msg = r.message || {};
                if (msg.mrp !== undefined && msg.mrp !== null) {
                    frappe.model.set_value(cdt, cdn, 'custom_mrp', flt(msg.mrp));
                }
                frappe.model.set_value(
                    cdt,
                    cdn,
                    'custom_buyer_margin_percent',
                    msg.margin_percent != null ? flt(msg.margin_percent) : 0
                );
                if (msg.margin_percent != null) {
                    frappe.model.set_value(cdt, cdn, 'custom_flat_discount', flt(msg.margin_percent));
                }
                frm.refresh_field('items');
                recalculate_row_values(frm, cdt, cdn);
            },
        });
    },

    custom_buyer_margin_percent(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    qty(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const int_qty = Math.round(flt(row.qty));
        if (row.qty !== int_qty) {
            frappe.model.set_value(cdt, cdn, 'qty', int_qty);
            return;
        }
        update_boxes_from_qty(cdt, cdn);
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_boxes(frm, cdt, cdn) {
        update_qty_from_boxes(cdt, cdn);
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_mrp(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_discount_type(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_flat_discount(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_offer(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_additional_discount_type(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_additional_discount(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    custom_item_tax_percent(frm, cdt, cdn) {
        recalculate_row_values(frm, cdt, cdn);
    },

    items_remove(frm) {
        recalculate_quotation_totals(frm);
    },
});

function get_conversion_factor(item_code, callback) {
    if (!item_code) {
        callback(null);
        return;
    }
    frappe.call({
        method: 'alpinos.sales_order_api.get_box_conversion_factor',
        args: { item_code: item_code },
        callback(r) {
            callback(r.message || null);
        },
    });
}

function update_boxes_from_qty(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code || !row.qty) return;

    get_conversion_factor(row.item_code, function (factor) {
        if (!factor) return;
        const boxes = Math.ceil(flt(row.qty) / flt(factor));
        const adjusted_qty = boxes * flt(factor);
        frappe.model.set_value(cdt, cdn, 'custom_boxes', boxes);
        if (adjusted_qty !== flt(row.qty)) {
            frappe.model.set_value(cdt, cdn, 'qty', flt(adjusted_qty, 2));
        }
    });
}

function update_qty_from_boxes(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code || !row.custom_boxes) return;

    get_conversion_factor(row.item_code, function (factor) {
        if (!factor) return;
        const boxes = Math.ceil(flt(row.custom_boxes));
        frappe.model.set_value(cdt, cdn, 'custom_boxes', boxes);
        frappe.model.set_value(cdt, cdn, 'qty', flt(boxes * factor, 2));
    });
}

function recalculate_row_values(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const qty = flt(row.qty);
    const mrp = flt(row.custom_mrp);

    if (!mrp) {
        recalculate_quotation_totals(frm);
        return;
    }

    const gross = mrp * qty;

    const discount_type = row.custom_discount_type || 'Percentage';
    const flat_in = flt(row.custom_flat_discount || row.custom_buyer_margin_percent);
    let flat_amt = 0;
    if (discount_type === 'Percentage') {
        flat_amt = gross * flat_in / 100.0;
    } else {
        flat_amt = flat_in;
    }

    const after_flat = gross - flat_amt;
    const offer_amt = after_flat * flt(row.custom_offer) / 100.0;
    const after_offer = after_flat - offer_amt;

    const add_in = flt(row.custom_additional_discount);
    const additional_amt = after_offer * add_in / 100.0;

    let taxable = after_offer - additional_amt;
    if (taxable < 0) taxable = 0;

    const tax_pct = flt(row.custom_item_tax_percent);
    const tax_amount = taxable * tax_pct / 100.0;

    const new_rate = qty ? flt(taxable / qty, 2) : 0;

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

    rows.forEach((row) => {
        const qty = flt(row.qty);
        const mrp = flt(row.custom_mrp);
        if (!mrp) return;

        const gross = qty * mrp;
        sub_total += gross;

        const flat_in = flt(row.custom_flat_discount || row.custom_buyer_margin_percent);
        let flat_discount_amount = 0;
        if ((row.custom_discount_type || 'Percentage') === 'Percentage') {
            flat_discount_amount = gross * flat_in / 100.0;
        } else {
            flat_discount_amount = flat_in;
        }

        const after_flat = gross - flat_discount_amount;
        const offer_amt = after_flat * flt(row.custom_offer) / 100.0;
        const after_offer = after_flat - offer_amt;

        over_discount += flat_discount_amount;

        const add_in = flt(row.custom_additional_discount);
        additional_discount += after_offer * add_in / 100.0;
    });

    let sum_taxable = 0;
    let sum_gst = 0;
    rows.forEach((row) => {
        sum_taxable += flt(row.amount);
        sum_gst += flt(row.custom_item_tax);
    });

    const cash_discount_pct = flt(frm.doc.custom_cash_discount);
    const pre_cash_total = sum_taxable + sum_gst;
    const cash_discount_amount = pre_cash_total > 0 ? pre_cash_total * cash_discount_pct / 100.0 : 0;
    const final_total = pre_cash_total - cash_discount_amount;
    const advance = flt(frm.doc.custom_advance_amount);
    const remaining = final_total - advance;

    frm.set_value('custom_sub_total', flt(sub_total, 2));
    frm.set_value('custom_over_discount', flt(over_discount, 2));
    frm.set_value('custom_additional_discount_total', flt(additional_discount, 2));
    frm.set_value('custom_gst_total', flt(sum_gst, 2));
    frm.set_value('custom_total_payable', flt(final_total, 2));
    frm.set_value('custom_remaining_amount', flt(remaining, 2));
    frm.set_value('total', flt(final_total, 2));
    frm.set_value('grand_total', flt(final_total, 2));
}

function toggle_payment_fields(frm) {
    const is_partial = frm.doc.custom_payment_mode === 'Partial';
    const need_proof =
        frm.doc.custom_payment_mode === 'Advance' || frm.doc.custom_payment_mode === 'Partial';
    frm.toggle_display('custom_advance_amount', is_partial);
    frm.toggle_reqd('custom_advance_amount', is_partial);
    frm.toggle_display('custom_attachment_proof', need_proof);
    frm.toggle_reqd('custom_attachment_proof', need_proof);
}

function enforce_percentage_discounts(frm) {
    (frm.doc.items || []).forEach((row) => {
        if (row.custom_additional_discount_type !== 'Percentage') {
            frappe.model.set_value(row.doctype, row.name, 'custom_additional_discount_type', 'Percentage');
        }
    });
    frm.set_df_property('custom_additional_discount_type', 'read_only', 1);
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
