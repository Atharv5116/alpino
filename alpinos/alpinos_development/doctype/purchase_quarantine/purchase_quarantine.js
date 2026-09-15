// Copyright (c) 2026, Alpinos and contributors
// For license information, please see license.txt

// The standard form is the record; releasing and the reminder live on the Quarantine Detail
// screen. "Go to QC" offers the same QCs that screen does (quarantine.get_quarantine_context).

frappe.ui.form.on('Purchase Quarantine', {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__('Quarantine Detail'), () => frappe.set_route('purchase_quarantine_view', frm.doc.name));
		frm.add_custom_button(__('Go to QC'), () => {
			frappe.call({
				method: 'alpinos.purchase.quarantine.get_quarantine_context',
				args: { purchase_quarantine: frm.doc.name },
				callback(r) {
					const qcs = ((r && r.message) || {}).purchase_qcs || [];
					if (!qcs.length) {
						frappe.msgprint(__('Nothing from this inward has reached QC yet. Release held items from the Quarantine Detail screen to raise a Purchase QC.'));
					} else if (qcs.length === 1) {
						frappe.set_route('purchase_qc_entry', qcs[0].name);
					} else {
						// Several: the detail screen lists them with where each came from.
						frappe.set_route('purchase_quarantine_view', frm.doc.name);
						frappe.show_alert({ message: __('Several Purchase QCs; use Go to QC to pick one.'), indicator: 'blue' });
					}
				},
			});
		});
	},
});
