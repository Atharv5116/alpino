import frappe


PICK_LIST_CLIENT_SCRIPT = """
frappe.ui.form.on('Pick List', {
	onload(frm) {
		set_defaults(frm);
		sync_order_information(frm);
		sync_all_pick_list_batch_dates(frm);
	},

	refresh(frm) {
		set_defaults(frm);
		sync_order_information(frm);
		recalculate_pick_list_totals(frm);
		sync_all_pick_list_batch_dates(frm);
	},

	locations_add(frm) {
		setTimeout(() => recalculate_pick_list_totals(frm), 200);
	},
	
	validate(frm) {
		// Aggressively bypass all batch fields and validations before submit!
		if (frm.doc.locations) {
			frm.doc.locations.forEach(row => {
				row.has_batch_no = 0;
				row.use_serial_batch_fields = 0;
				
				// Fix Frappe's inner cache which save.js uses!
				if (frappe.meta.docfield_copy && 
					frappe.meta.docfield_copy["Pick List Item"] && 
					frappe.meta.docfield_copy["Pick List Item"][row.name]) {
					
					let df_copy = frappe.meta.docfield_copy["Pick List Item"][row.name]["batch_no"];
					if (df_copy) {
						df_copy.reqd = 0;
					}
				}
			});
		}
		let df = frappe.meta.get_docfield("Pick List Item", "batch_no");
		if (df) {
			df.reqd = 0;
		}
		
		if (frm.fields_dict.locations && frm.fields_dict.locations.grid) {
			frm.fields_dict.locations.grid.update_docfield_property("batch_no", "reqd", 0);
		}
	}
});

frappe.ui.form.on('Pick List Item', {
	qty(frm, cdt, cdn) {
		recalculate_pick_list_row(frm, cdt, cdn);
	},

	custom_weight_per_box(frm, cdt, cdn) {
		recalculate_pick_list_totals(frm);
	},

	batch_no(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.batch_no) {
			frappe.model.set_value(cdt, cdn, 'custom_mfg_date', null);
			frappe.model.set_value(cdt, cdn, 'custom_expiry_date', null);
			return;
		}
		frappe.db.get_value('Batch', row.batch_no, ['manufacturing_date', 'expiry_date']).then((r) => {
			const d = r.message || {};
			frappe.model.set_value(cdt, cdn, 'custom_mfg_date', d.manufacturing_date || null);
			frappe.model.set_value(cdt, cdn, 'custom_expiry_date', d.expiry_date || null);
		});
	},

	item_code(frm, cdt, cdn) {
		recalculate_pick_list_row(frm, cdt, cdn);
	},

	locations_remove(frm) {
		recalculate_pick_list_totals(frm);
	}
});

function set_defaults(frm) {
	if (frm.is_new() && !frm.doc.custom_qc_attended_by) {
		frm.set_value('custom_qc_attended_by', frappe.session.user);
	}
	if (frm.is_new() && !frm.doc.custom_order_date) {
		frm.set_value('custom_order_date', frappe.datetime.now_datetime());
	}
}

function sync_order_information(frm) {
	const rows = frm.doc.locations || [];
	const first_so = (rows.find(r => r.sales_order) || {}).sales_order;
	if (first_so && frm.doc.custom_sales_order_id !== first_so) {
		frm.set_value('custom_sales_order_id', first_so);
	}
	if (first_so) {
		frappe.db.get_value('Sales Order', first_so, ['customer_name']).then((r) => {
			const d = r.message || {};
			if (d.customer_name && frm.doc.custom_customer_name !== d.customer_name) {
				frm.set_value('custom_customer_name', d.customer_name);
			}
		});
	}
}

/** Rows from "Get Item Locations" often have batch_no without firing batch_no; fill read-only MFG/Expiry from Batch. */
function sync_all_pick_list_batch_dates(frm) {
	const rows = frm.doc.locations || [];
	const jobs = rows
		.filter((row) => row.batch_no && (!row.custom_mfg_date || !row.custom_expiry_date))
		.map((row) =>
			frappe.db.get_value('Batch', row.batch_no, ['manufacturing_date', 'expiry_date']).then((r) => {
				const d = r.message || {};
				if (d.manufacturing_date) {
					frappe.model.set_value(row.doctype, row.name, 'custom_mfg_date', d.manufacturing_date);
				}
				if (d.expiry_date) {
					frappe.model.set_value(row.doctype, row.name, 'custom_expiry_date', d.expiry_date);
				}
			})
		);
	return Promise.all(jobs);
}

function recalculate_pick_list_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row) return;

	const qty = flt(row.qty);

	if (!row.item_code) {
		frappe.model.set_value(cdt, cdn, 'custom_box', 0);
		frappe.model.set_value(cdt, cdn, 'custom_sample_box', 0);
		recalculate_pick_list_totals(frm);
		return;
	}

	const table_name = row.custom_source_table || "Items";
	if (table_name !== "Items") {
		// Keep the box field blank (or 0) by default for non-Items tables, don't auto-calculate from quantity.
		recalculate_pick_list_totals(frm);
		return;
	}

	frappe.call({
		method: 'alpinos.sales_order_api.get_box_conversion_factor',
		args: { item_code: row.item_code },
		callback: function(r) {
			const factor = flt(r.message) || 1;
			const box = factor ? Math.ceil(qty / factor) : 0;
			frappe.model.set_value(cdt, cdn, 'custom_box', box);
			frappe.model.set_value(cdt, cdn, 'custom_sample_box', 0);
			frappe.model.set_value(cdt, cdn, 'custom_sample_quantity', 0);
			recalculate_pick_list_totals(frm);
		}
	});
}

function recalculate_pick_list_totals(frm) {
	let actual_box = 0;
	let sample_box = 0;
	let sample_weight = 0;
	let gross_weight = 0;
	let total_unit = 0;

	(frm.doc.locations || []).forEach((row) => {
		// Round manually edited values or DB values to integer
		const row_box = row.custom_box ? Math.round(flt(row.custom_box)) : 0;
		if (row.custom_box && flt(row.custom_box) !== row_box) {
			frappe.model.set_value(row.doctype, row.name, 'custom_box', row_box);
		}
		const row_weight_per_box = flt(row.custom_weight_per_box);
		const table_name = row.custom_source_table || "Items";
		
		if (table_name === "Items") {
			actual_box += row_box;
		} else {
			sample_box += row_box;
			sample_weight += row_box * row_weight_per_box;
		}
		gross_weight += row_box * row_weight_per_box;
		total_unit += flt(row.qty);
	});

	frm.set_value('custom_actual_box', cint(actual_box));
	frm.set_value('custom_sample_box', cint(sample_box));
	frm.set_value('custom_sample_weight', flt(sample_weight, 2));
	frm.set_value('custom_total_box', cint(actual_box + sample_box));
	frm.set_value('custom_gross_weight', flt(gross_weight, 2));
	frm.set_value('custom_total_unit', flt(total_unit, 2));

	sync_order_information(frm);
}
"""


def create_pick_list_client_script():
	script_name = "Pick List - Alpinos Customization"
	existing = frappe.db.exists("Client Script", {"name": script_name})

	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = PICK_LIST_CLIENT_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Pick List",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": PICK_LIST_CLIENT_SCRIPT,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
