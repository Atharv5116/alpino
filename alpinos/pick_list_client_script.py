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
		configure_grid_actions(frm);
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
	},
	
	custom_actual_box(frm) {
		frm.set_value('custom_total_box', cint(frm.doc.custom_actual_box || 0) + cint(frm.doc.custom_sample_box || 0));
	},
	
	custom_sample_box(frm) {
		frm.set_value('custom_total_box', cint(frm.doc.custom_actual_box || 0) + cint(frm.doc.custom_sample_box || 0));
	}
});

frappe.ui.form.on('Pick List Item', {
	qty(frm, cdt, cdn) {
		recalculate_pick_list_row(frm, cdt, cdn);
	},

	custom_box(frm, cdt, cdn) {
		recalculate_pick_list_totals(frm);
	},

	custom_sample_box(frm, cdt, cdn) {
		recalculate_pick_list_totals(frm);
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
			if (d.expiry_date && row.sales_order) {
				frappe.call({
					method: 'alpinos.expiry_validation.check_row_expiry_warning',
					args: {
						expiry_date: d.expiry_date,
						sales_order: row.sales_order,
						dispatch_date: frm.doc.custom_dispatch_date || null,
					},
				}).then((res) => {
					const m = res.message || {};
					if (!m.ok && m.message) {
						frappe.show_alert({ message: `Row #${row.idx}: ${m.message}`, indicator: 'orange' }, 7);
					}
				});
			}
		});
	},

	item_code(frm, cdt, cdn) {
		recalculate_pick_list_row(frm, cdt, cdn);
	},

	locations_remove(frm) {
		recalculate_pick_list_totals(frm);
	}
});

function configure_grid_actions(frm) {
	const grid = frm.fields_dict.locations && frm.fields_dict.locations.grid;
	if (!grid) return;

	// Disable Frappe's built-in row deletion entirely on this grid — we own removal via a custom button.
	grid.cannot_delete_rows = 1;
	grid.cannot_delete_all_rows = 1;

	// Custom buttons only on draft.
	frm.custom_buttons && frm.custom_buttons["Remove Selected Row"] && frm.custom_buttons["Remove Selected Row"].remove();
	frm.custom_buttons && frm.custom_buttons["Split Row"] && frm.custom_buttons["Split Row"].remove();
	if (frm.doc.docstatus !== 0) {
		grid.refresh();
		return;
	}

	frm.add_custom_button("Remove Selected Row", () => prompt_remove_selected_row(frm), "Pick List Actions");
	frm.add_custom_button("Split Row", () => prompt_split_selected_row(frm), "Pick List Actions");
	grid.refresh();
}

function get_one_selected_row(frm) {
	const grid = frm.fields_dict.locations.grid;
	const selected = grid.get_selected_children ? grid.get_selected_children() : [];
	if (!selected.length) {
		frappe.msgprint(__("Tick the row you want to act on, then press the button again."));
		return null;
	}
	if (selected.length > 1) {
		frappe.msgprint(__("Tick only one row at a time."));
		return null;
	}
	return selected[0];
}

function prompt_remove_selected_row(frm) {
	const row = get_one_selected_row(frm);
	if (!row) return;
	frappe.prompt(
		[{ fieldname: "reason", fieldtype: "Small Text", label: "Reason for Removal", reqd: 1 }],
		(values) => {
			const audit = frm.add_child("custom_removed_items", {
				item_code: row.item_code,
				item_name: row.item_name,
				removed_qty: flt(row.qty),
				removed_box: flt(row.custom_box),
				batch_no: row.batch_no || row.custom_batch_code || null,
				reason: values.reason,
				removed_by: frappe.session.user,
				removed_on: frappe.datetime.now_datetime(),
			});
			frm.refresh_field("custom_removed_items");
			// Remove the source row from locations.
			frm.doc.locations = (frm.doc.locations || []).filter((r) => r.name !== row.name);
			frm.refresh_field("locations");
			recalculate_pick_list_totals(frm);
		},
		__("Remove Row"),
		__("Confirm")
	);
}

function prompt_split_selected_row(frm) {
	const row = get_one_selected_row(frm);
	if (!row) return;
	const current_box = cint(row.custom_box);
	if (current_box <= 1) {
		frappe.msgprint(__("Row must have at least 2 boxes to split."));
		return;
	}
	frappe.prompt(
		[{ fieldname: "split_box", fieldtype: "Int", label: `Boxes to split (current: ${current_box})`, reqd: 1 }],
		(values) => {
			const split_box = cint(values.split_box);
			if (split_box <= 0 || split_box >= current_box) {
				frappe.msgprint(__(`Split box must be between 1 and ${current_box - 1}.`));
				return;
			}
			frappe.call({
				method: 'alpinos.pick_list_api.get_box_conversion_factor',
				args: { item_code: row.item_code },
			}).then((r) => {
				const factor = flt(r.message);
				if (!factor) {
					frappe.throw(__(`Define UOM 'Box' on Item ${row.item_code} before splitting.`));
					return;
				}
				const new_row = frm.add_child("locations", {
					item_code: row.item_code,
					item_name: row.item_name,
					custom_ordered_qty: row.custom_ordered_qty,
					qty: flt(split_box * factor, 2),
					stock_qty: flt(split_box * factor, 2),
					picked_qty: flt(split_box * factor, 2),
					conversion_factor: row.conversion_factor || 1,
					warehouse: row.warehouse,
					sales_order: row.sales_order,
					sales_order_item: row.sales_order_item,
					custom_box: split_box,
					custom_sample_quantity: 0,
					custom_sample_box: 0,
					custom_weight_per_box: row.custom_weight_per_box,
					custom_source_table: row.custom_source_table,
					custom_remark: (row.custom_remark || "") + " [split]",
				});
				// Decrement source row by the split amount.
				const remaining_box = current_box - split_box;
				frappe.model.set_value(row.doctype, row.name, "custom_box", remaining_box);
				frappe.model.set_value(row.doctype, row.name, "qty", flt(remaining_box * factor, 2));
				frm.refresh_field("locations");
				recalculate_pick_list_totals(frm);
			});
		},
		__("Split Row"),
		__("Split")
	);
}

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
