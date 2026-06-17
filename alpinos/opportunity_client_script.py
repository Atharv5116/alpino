"""
Client Script for Opportunity custom flow:
- Offline Buyer Master: show business name, hide org noise, Dynamic Link filtering
- SKU pricing from Offline Buyer Items / Offline Buyer Margin (MRP + buyer margin %) + editable
- Qty / boxes, totals (buyer margin before other line discounts)
"""

import frappe


OPPORTUNITY_CLIENT_SCRIPT = '''
const OBM_HIDE_FIELDS = [
	// Organization noise
	"organization_details_section",
	"no_of_employees",
	"annual_revenue",
	"industry",
	"market_segment",
	"column_break_23",
	"territory",
	"city",
	"state",
	"country",
];


frappe.ui.form.on("Opportunity", {
	setup(frm) {
		frm.set_query("opportunity_from", () => ({
			filters: { name: ["in", ["Customer", "Lead", "Prospect", "Offline Buyer Master"]] },
		}));
		frm.set_query("party_name", () => {
			const obm = frm.doc.opportunity_from === "Offline Buyer Master";
			return obm
				? { filters: { customer: ["!=", ""] } }
				: {};
		});
		set_variant_item_queries(frm);
	},

	onload(frm) {
		if (frm.is_new() && !frm.doc.opportunity_owner) {
			frappe.model.set_value(frm.doctype, frm.doc.name, "opportunity_owner", frappe.session.user);
		}
		apply_opportunity_party_layout(frm);
	},

	refresh(frm) {
		apply_opportunity_party_layout(frm);
		set_variant_item_queries(frm);
	},

	opportunity_from(frm) {
		apply_opportunity_party_layout(frm);
	},

	party_name(frm) {
		if (frm.doc.opportunity_from === "Offline Buyer Master") {
			sync_obm_header_from_master(frm);
		} else if (frm.doc.opportunity_from === "Customer" && frm.doc.party_name) {
			frappe.db.get_value("Customer", frm.doc.party_name, "custom_order_type", (r) => {
				if (r && r.custom_order_type) {
					frm.set_value("custom_order_type", r.custom_order_type);
				}
			});
		} else {
			frappe.model.set_value(frm.doctype, frm.doc.name, "customer_name", "");
		}
	},

	custom_cash_discount(frm) {
		recalculate_opportunity_totals(frm);
	},
});

function sync_obm_header_from_master(frm) {
	const name = frm.doc.party_name;
	if (!name) {
		frappe.model.set_value(frm.doctype, frm.doc.name, "customer_name", "");
		return;
	}
	frappe.call({
		method: "alpinos.sales_order_api.get_opportunity_obm_party_data",
		args: { offline_buyer_master: name },
		callback(r) {
			const d = r.message || {};
			if (d.customer_business_name)
				frappe.model.set_value(
					frm.doctype,
					frm.doc.name,
					"customer_name",
					d.customer_business_name
				);
			else frappe.model.set_value(frm.doctype, frm.doc.name, "customer_name", "");
			if (d.customer_type) frm.set_value("custom_order_type", d.customer_type);
			frm.toggle_display("customer_name", !!d.customer_business_name);

			// Auto-populate billing & shipping address from OBM
			if (d.customer) {
				frappe.call({
					method: "alpinos.sales_order_offline_buyer.sync_offline_buyer_master_addresses",
					args: { customer: d.customer },
					callback(r2) {
						const ad = r2.message || {};
						if (ad.default_billing && !frm.doc.custom_billing_address) {
							frm.set_value("custom_billing_address", ad.default_billing);
						}
						if (ad.default_shipping && !frm.doc.customer_address) {
							frm.set_value("customer_address", ad.default_shipping);
						}
					},
				});
			}
		},
	});
}

function apply_opportunity_party_layout(frm) {
	const is_obm = frm.doc.opportunity_from === "Offline Buyer Master";

	frm.set_df_property(
		"party_name",
		"label",
		is_obm ? __("Offline Buyer Master") : __("Customer")
	);

	OBM_HIDE_FIELDS.forEach((fn) => frm.toggle_display(fn, !is_obm));

	if (is_obm && frm.doc.party_name) sync_obm_header_from_master(frm);
	else frappe.model.set_value(frm.doctype, frm.doc.name, "customer_name", "");

	frm.toggle_display("customer_name", is_obm && !!frm.doc.customer_name);

	frm.refresh_field("party_name");
}

frappe.ui.form.on("Opportunity Item", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;

		frappe.db.get_value("Item", row.item_code, "item_name").then((x) => {
			if (x && x.message && x.message.item_name) {
				frappe.model.set_value(cdt, cdn, "item_name", x.message.item_name);
			}
		});

		const pf = frm.doc.opportunity_from;
		const pn = frm.doc.party_name;
		if (row.qty) update_boxes_from_qty(frm, cdt, cdn);
		if (row.custom_boxes) update_qty_from_boxes(frm, cdt, cdn);
		if (!pf || !pn) return;

		frappe.call({
			method: "alpinos.sales_order_api.get_opportunity_line_pricing",
			args: {
				opportunity_from: pf,
				party_name: pn,
				item_code: row.item_code,
			},
			callback(r) {
				const msg = r.message || {};
				if (msg.mrp !== undefined && msg.mrp !== null) {
					frappe.model.set_value(cdt, cdn, "custom_mrp", flt(msg.mrp));
				}
				frappe.model.set_value(
					cdt,
					cdn,
					"custom_buyer_margin_percent",
					msg.margin_percent !== undefined && msg.margin_percent !== null
						? flt(msg.margin_percent)
						: 0
				);
				if (msg.margin_percent != null) {
					frappe.model.set_value(cdt, cdn, "custom_flat_discount", flt(msg.margin_percent));
				}
				frm.refresh_field("items");
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
			frappe.model.set_value(cdt, cdn, "qty", int_qty);
			return;
		}
		update_boxes_from_qty(frm, cdt, cdn);
		recalculate_row_values(frm, cdt, cdn);
	},

	custom_boxes(frm, cdt, cdn) {
		update_qty_from_boxes(frm, cdt, cdn);
		recalculate_row_values(frm, cdt, cdn);
	},

	custom_mrp(frm, cdt, cdn) {
		recalculate_row_values(frm, cdt, cdn);
	},

	custom_flat_discount(frm, cdt, cdn) {
		recalculate_row_values(frm, cdt, cdn);
	},

	custom_offer(frm, cdt, cdn) {
		recalculate_row_values(frm, cdt, cdn);
	},

	custom_additional_discount(frm, cdt, cdn) {
		recalculate_row_values(frm, cdt, cdn);
	},

	custom_item_tax(frm, cdt, cdn) {
		recalculate_row_values(frm, cdt, cdn);
	},

	items_remove(frm) {
		recalculate_opportunity_totals(frm);
	},
});

function get_conversion_factor(item_code, callback) {
	if (!item_code) {
		callback(null);
		return;
	}
	frappe.call({
		method: "alpinos.sales_order_api.get_box_conversion_factor",
		args: { item_code: item_code },
		callback(r) {
			callback(r.message || null);
		},
	});
}

function update_boxes_from_qty(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.item_code || !row.qty) return;
	get_conversion_factor(row.item_code, (factor) => {
		if (!factor) return;
		const boxes = Math.ceil(flt(row.qty) / flt(factor));
		const adjusted_qty = boxes * flt(factor);
		frappe.model.set_value(cdt, cdn, "custom_boxes", boxes);
		if (adjusted_qty !== flt(row.qty)) {
			frappe.model.set_value(cdt, cdn, "qty", flt(adjusted_qty, 2));
		}
	});
}

function update_qty_from_boxes(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.item_code || !row.custom_boxes) return;
	get_conversion_factor(row.item_code, (factor) => {
		if (!factor) return;
		const boxes = Math.ceil(flt(row.custom_boxes));
		frappe.model.set_value(cdt, cdn, "custom_boxes", boxes);
		frappe.model.set_value(cdt, cdn, "qty", flt(boxes * factor, 2));
	});
}

function line_unit_base_before_trade_discount(row) {
	const mrp = flt(row.custom_mrp);
	const bm = flt(row.custom_buyer_margin_percent);
	if (!mrp) return 0;
	return mrp * (1.0 - bm / 100.0);
}

function recalculate_row_values(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const qty = flt(row.qty);
	const mrp = flt(row.custom_mrp);

	if (!mrp) {
		recalculate_opportunity_totals(frm);
		return;
	}

	const flat_discount = flt(row.custom_flat_discount || row.custom_buyer_margin_percent);
	const offer_pct = flt(row.custom_offer);
	const additional_discount_pct = flt(row.custom_additional_discount);

	let gst_pct = flt(row.custom_gst_percent || row.gst_percent || 0);

	const run_calc = (g_pct) => {
		const gross_incl = mrp * qty;
		const flat_disc_amt = gross_incl * flat_discount / 100.0;
		const after_flat = gross_incl - flat_disc_amt;
		const offer_amt = after_flat * offer_pct / 100.0;
		const after_offer = after_flat - offer_amt;
		const additional_amt = after_offer * additional_discount_pct / 100.0;
		const final_incl = Math.max(after_offer - additional_amt, 0);

		const div = 1 + (g_pct / 100.0);
		const taxable = div > 0 ? (final_incl / div) : final_incl;
		const tax_amount = Math.max(final_incl - taxable, 0);

		const new_rate = qty ? flt(taxable / qty, 2) : 0;

		frappe.model.set_value(cdt, cdn, "custom_item_tax", flt(tax_amount, 2));
		frappe.model.set_value(cdt, cdn, "rate", new_rate);
		frappe.model.set_value(cdt, cdn, "amount", flt(taxable, 2));
		frappe.model.set_value(cdt, cdn, "base_rate", new_rate);
		frappe.model.set_value(cdt, cdn, "base_amount", flt(taxable, 2));

		recalculate_opportunity_totals(frm);
	};

	if (!gst_pct && row.item_code) {
		frappe.db.get_value("Item", row.item_code, "custom_gst_percent", (r) => {
			gst_pct = flt(r && r.custom_gst_percent);
			run_calc(gst_pct);
		});
	} else {
		run_calc(gst_pct);
	}
}

function recalculate_opportunity_totals(frm) {
	const rows = frm.doc.items || [];
	let sub_total = 0.0;
	let over_discount_total = 0.0;
	let additional_discount_total = 0.0;
	let gst_total = 0.0;
	let sum_incl = 0.0;

	const promises = [];

	rows.forEach((row) => {
		const qty = flt(row.qty);
		const mrp = flt(row.custom_mrp);
		if (!mrp) return;

		const flat_discount = flt(row.custom_flat_discount || row.custom_buyer_margin_percent);
		const offer_pct = flt(row.custom_offer);
		const additional_discount_pct = flt(row.custom_additional_discount);

		let gst_pct = flt(row.custom_gst_percent || row.gst_percent || 0);

		const add_to_totals = (g_pct) => {
			const gross_incl = qty * mrp;
			sub_total += gross_incl;

			const flat_disc_amt = gross_incl * flat_discount / 100.0;
			const after_flat = gross_incl - flat_disc_amt;
			const offer_amt = after_flat * offer_pct / 100.0;
			const after_offer = after_flat - offer_amt;
			const additional_amt = after_offer * additional_discount_pct / 100.0;
			const final_incl = Math.max(after_offer - additional_amt, 0);

			const div = 1 + (g_pct / 100.0);
			const taxable = div > 0 ? (final_incl / div) : final_incl;
			const tax_amount = Math.max(final_incl - taxable, 0);

			over_discount_total += flat_disc_amt;
			additional_discount_total += additional_amt;
			gst_total += tax_amount;
			sum_incl += final_incl;
		};

		if (!gst_pct && row.item_code) {
			const p = new Promise((resolve) => {
				frappe.db.get_value("Item", row.item_code, "custom_gst_percent", (r) => {
					const g_val = flt(r && r.custom_gst_percent);
					add_to_totals(g_val);
					resolve();
				});
			});
			promises.push(p);
		} else {
			add_to_totals(gst_pct);
		}
	});

	const update_values = () => {
		const cash_discount_pct = flt(frm.doc.custom_cash_discount);
		const cash_discount_amount = sum_incl > 0 ? sum_incl * cash_discount_pct / 100.0 : 0;
		const final_total = sum_incl - cash_discount_amount;

		frm.set_value("custom_over_discount", flt(over_discount_total, 2));
		frm.set_value("custom_additional_discount_total", flt(additional_discount_total, 2));
		frm.set_value("custom_gst_total", flt(gst_total, 2));
		frm.set_value("total", flt(final_total, 2));
		frm.set_value("opportunity_amount", flt(final_total, 2));
	};

	if (promises.length > 0) {
		Promise.all(promises).then(update_values);
	} else {
		update_values();
	}
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
		return {
			query: 'alpinos.offline_buyer_api.sellable_item_link_query'
		};
	};
	console.log("Setting item queries for Opportunity");
	frm.set_query('item_code', 'items', q_variants);
	frm.set_query('item_code', 'custom_marketing_freebies', q_freebies);
	frm.set_query('item_code', 'custom_scheme_item_table', q_freebies);
	frm.set_query('item_code', 'custom_additional_units_damage_items', q_variants);
}
'''


def create_opportunity_client_script():
	"""Create or update client script for Opportunity"""
	script_name = "Opportunity - Alpinos Customization"
	existing = frappe.db.exists("Client Script", {"name": script_name})

	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = OPPORTUNITY_CLIENT_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
		print(f"✅ Updated client script: {script_name}")
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
		print(f"✅ Created client script: {script_name}")

	frappe.db.commit()
