"""Client Script for Quotation custom calculations."""

import frappe


QUOTATION_CLIENT_SCRIPT = """
// Party, addresses and item pickers of the Quotation. Prices, totals and the Payment section are
// the Offline Sales Quotation's (alpinos.offline_sales.quotation, public/js/quotation_offline.js):
// the Sales Order engine prices the lines, and the Payment Term comes from the Buyer Master once,
// when the Quotation is created.
frappe.ui.form.on('Quotation', {
    setup(frm) {
        frm.set_query('quotation_to', () => ({
            filters: { name: ['in', ['Customer', 'Lead', 'Prospect', 'Buyer Master']] },
        }));
        frm.set_query('party_name', () => {
            if (frm.doc.quotation_to === 'Buyer Master') {
                return { filters: { customer: ['!=', ''] } };
            }
            return {};
        });
        set_variant_item_queries(frm);
    },

    onload(frm) {
        disable_rounded_total(frm);
        apply_quotation_party_layout(frm);
        setTimeout(() => apply_quotation_address_queries(frm), 0);
    },

    refresh(frm) {
        disable_rounded_total(frm);
        apply_quotation_party_layout(frm);
        set_variant_item_queries(frm);
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
        if (frm.doc.quotation_to === 'Buyer Master') {
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
});

function disable_rounded_total(frm) {
    if (frm.doc.docstatus === 0 && frm.fields_dict.disable_rounded_total && !frm.doc.disable_rounded_total) {
        frm.set_value('disable_rounded_total', 1);
    }
}

function fix_dynamic_link_for_obm(frm) {
    // ERPNext's QuotationController.refresh() sets frappe.dynamic_link.doctype to
    // "Buyer Master", which causes SQL errors ("Unknown column 'offline_buyer_master'")
    // in Address/Contact queries. Reset to "Customer" using the resolved customer.
    if (
        frm.doc.quotation_to === 'Buyer Master' &&
        frappe.dynamic_link &&
        frappe.dynamic_link.doctype === 'Buyer Master'
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
    if (frm.doc.quotation_to === 'Buyer Master') {
        frm.set_df_property('party_name', 'label', __('Customer'));
        // the header follows the Buyer while the Quotation can still change
        if (frm.doc.party_name && frm.doc.docstatus === 0 && frm.is_new()) {
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
    if (frm.doc.quotation_to === 'Buyer Master' && frm.doc.custom_resolved_customer) {
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
            frappe.model.set_value(frm.doctype, frm.doc.name, 'customer_name', d.customer_business_name || '');
            if (d.customer_type) {
                frm.set_value('order_type', d.customer_type);
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
        // Gate by the quotation's customer type so only items that allow it appear.
        const ct = frm.doc.order_type;
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
		print(f"✅ Updated client script: {script_name}")
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
		print(f"✅ Created client script: {script_name}")

	frappe.db.commit()
