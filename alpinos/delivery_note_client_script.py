import frappe

DELIVERY_NOTE_CLIENT_SCRIPT = """
frappe.ui.form.on('Delivery Note', {
	refresh(frm) {
		configure_dn_grid_actions(frm);
		if (frm.doc.is_return) return;
		sync_sales_order_from_items(frm);
		sync_all_items_from_pick_list(frm).then(() => recalc_dn_totals(frm));
	},

	items_add(frm) {
		if (frm.doc.is_return) return;
		setTimeout(() => sync_all_items_from_pick_list(frm).then(() => recalc_dn_totals(frm)), 300);
	}
});

frappe.ui.form.on('Delivery Note Item', {
	item_code(frm, cdt, cdn) {
		if (frm.doc.is_return) return;
		sync_one_row_from_pick_list(frm, cdt, cdn).then(() => recalc_dn_totals(frm));
	},

	qty(frm, cdt, cdn) {
		if (frm.doc.is_return) return;
		recalc_box_for_row(frm, cdt, cdn).then(() => recalc_dn_totals(frm));
	},

	batch_no(frm, cdt, cdn) {
		if (frm.doc.is_return) return;
		const row = locals[cdt][cdn];
		if (!row.batch_no) {
			frappe.model.set_value(cdt, cdn, 'custom_mfg_date', null);
			frappe.model.set_value(cdt, cdn, 'custom_expiry_date', null);
			recalc_dn_totals(frm);
			return;
		}
		frappe.db.get_value('Batch', row.batch_no, ['manufacturing_date', 'expiry_date']).then((r) => {
			const d = r.message || {};
			frappe.model.set_value(cdt, cdn, 'custom_mfg_date', d.manufacturing_date || null);
			frappe.model.set_value(cdt, cdn, 'custom_expiry_date', d.expiry_date || null);
			recalc_dn_totals(frm);
			if (d.expiry_date && row.against_sales_order) {
				frappe.call({
					method: 'alpinos.expiry_validation.check_row_expiry_warning',
					args: {
						expiry_date: d.expiry_date,
						sales_order: row.against_sales_order,
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

	items_remove(frm) {
		if (frm.doc.is_return) return;
		recalc_dn_totals(frm);
	}
});

function sync_sales_order_from_items(frm) {
	const rows = frm.doc.items || [];
	const so = (rows.find(r => r.against_sales_order) || {}).against_sales_order;
	if (so && frm.doc.custom_sales_order_id !== so) {
		frm.set_value('custom_sales_order_id', so);
	}
}

function sync_all_items_from_pick_list(frm) {
	const rows = frm.doc.items || [];
	const jobs = rows.map((row) => sync_one_row_from_pick_list(frm, row.doctype, row.name));
	return Promise.all(jobs);
}

function sync_one_row_from_pick_list(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || !row.pick_list_item) {
		return Promise.resolve();
	}
	return frappe.call({
		method: 'alpinos.delivery_note_api.get_pick_list_row_for_delivery',
		args: { pick_list_item: row.pick_list_item },
	}).then((r) => {
		const d = r.message || {};
		if (d.batch_no && !row.batch_no) {
			frappe.model.set_value(cdt, cdn, 'batch_no', d.batch_no);
		}
		if (d.custom_box != null && d.custom_box !== undefined) {
			frappe.model.set_value(cdt, cdn, 'custom_box', d.custom_box);
		}
		if (d.custom_mfg_date) {
			frappe.model.set_value(cdt, cdn, 'custom_mfg_date', d.custom_mfg_date);
		}
		if (d.custom_expiry_date) {
			frappe.model.set_value(cdt, cdn, 'custom_expiry_date', d.custom_expiry_date);
		}
		const row2 = locals[cdt][cdn];
		if (d.custom_box == null && row2.item_code && row2.qty) {
			return recalc_box_for_row(frm, cdt, cdn);
		}
		if (row2.batch_no && (!row2.custom_mfg_date || !row2.custom_expiry_date)) {
			return frappe.db.get_value('Batch', row2.batch_no, ['manufacturing_date', 'expiry_date']).then((br) => {
				const b = br.message || {};
				if (!locals[cdt][cdn].custom_mfg_date && b.manufacturing_date) {
					frappe.model.set_value(cdt, cdn, 'custom_mfg_date', b.manufacturing_date);
				}
				if (!locals[cdt][cdn].custom_expiry_date && b.expiry_date) {
					frappe.model.set_value(cdt, cdn, 'custom_expiry_date', b.expiry_date);
				}
			});
		}
		return null;
	});
}

function recalc_box_for_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.item_code || !row.qty) {
		frappe.model.set_value(cdt, cdn, 'custom_box', 0);
		return Promise.resolve();
	}
	return frappe.db.get_value('UOM Conversion Detail', {
		parent: row.item_code,
		parenttype: 'Item',
		uom: 'Box'
	}, 'conversion_factor').then((r) => {
		const f = flt(r.message && r.message.conversion_factor) || 1;
		const box = Math.ceil(flt(row.qty) / f);
		frappe.model.set_value(cdt, cdn, 'custom_box', box);
	});
}

function recalc_dn_totals(frm) {
	if (frm.doc.is_return) return;
	let total_boxes = 0;
	let total_units = 0;
	(frm.doc.items || []).forEach((row) => {
		total_boxes += flt(row.custom_box);
		total_units += flt(row.qty);
	});
	const pl_list = [...new Set((frm.doc.items || []).map(r => r.against_pick_list).filter(Boolean))];
	if (!pl_list.length) {
		frm.set_value('custom_total_boxes', total_boxes);
		frm.set_value('custom_total_units_dn', total_units);
		frm.set_value('custom_dn_order_gross_weight', 0);
		return;
	}
	Promise.all(pl_list.map((pl) => frappe.db.get_value('Pick List', pl, 'custom_gross_weight'))).then((results) => {
		let gross = 0;
		results.forEach((r) => {
			gross += flt(r.message && r.message.custom_gross_weight);
		});
		frm.set_value('custom_total_boxes', total_boxes);
		frm.set_value('custom_total_units_dn', total_units);
		frm.set_value('custom_dn_order_gross_weight', gross);
	});
}

// --- SKU removal requires a mandatory reason (logged to custom_removed_items) ---
function configure_dn_grid_actions(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return;
	frm.custom_buttons && frm.custom_buttons["Remove Selected Row"] && frm.custom_buttons["Remove Selected Row"].remove();
	// Returns and submitted docs keep native grid behaviour.
	if (frm.doc.is_return || frm.doc.docstatus !== 0) {
		grid.cannot_delete_rows = 0;
		grid.cannot_delete_all_rows = 0;
		grid.refresh();
		return;
	}
	// Disable native row deletion — removal must go through the reason prompt.
	grid.cannot_delete_rows = 1;
	grid.cannot_delete_all_rows = 1;
	frm.add_custom_button("Remove Selected Row", () => prompt_remove_selected_dn_row(frm), "Delivery Note Actions");
	grid.refresh();
}

function get_one_selected_dn_row(frm) {
	const grid = frm.fields_dict.items.grid;
	const selected = grid.get_selected_children ? grid.get_selected_children() : [];
	if (!selected.length) {
		frappe.msgprint(__("Tick the row you want to remove, then press the button again."));
		return null;
	}
	if (selected.length > 1) {
		frappe.msgprint(__("Tick only one row at a time."));
		return null;
	}
	return selected[0];
}

function prompt_remove_selected_dn_row(frm) {
	const row = get_one_selected_dn_row(frm);
	if (!row) return;
	frappe.prompt(
		[{ fieldname: "reason", fieldtype: "Small Text", label: "Reason for Removal", reqd: 1 }],
		(values) => {
			frm.add_child("custom_removed_items", {
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
			frm.doc.items = (frm.doc.items || []).filter((r) => r.name !== row.name);
			frm.refresh_field("items");
			recalc_dn_totals(frm);
		},
		__("Remove Row"),
		__("Confirm")
	);
}
"""


def create_delivery_note_client_script():
	script_name = "Delivery Note - Alpinos Customization"
	existing = frappe.db.exists("Client Script", {"name": script_name})

	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = DELIVERY_NOTE_CLIENT_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Delivery Note",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": DELIVERY_NOTE_CLIENT_SCRIPT,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
