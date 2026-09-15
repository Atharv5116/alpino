// A GRN's Debit Note on the standard Purchase Invoice form.
//
// grn.make_debit_note raises the Debit Note as a Draft, and Frappe offers Cancel only on a
// submitted document, so a wrong draft could only be deleted. A submitted one keeps Frappe's
// own Cancel (purchase_invoice.on_cancel lets it past the GRN / QC / inward links).

frappe.ui.form.on('Purchase Invoice', {
	refresh(frm) {
		if (frm.is_new() || !cint(frm.doc.is_return) || cint(frm.doc.docstatus) !== 0) return;
		const grn = (frm.doc.items || []).map((row) => row.purchase_receipt).find(Boolean);
		if (!grn) return;

		frappe.db.get_value('Purchase Receipt', grn, 'custom_purchase_inward').then((r) => {
			// Only a Debit Note raised from a Purchase Inward GRN; an ordinary return is ERPNext's.
			if (!(r && r.message && r.message.custom_purchase_inward)) return;
			frm.add_custom_button(__('GRN Detail'), () => frappe.set_route('purchase_grn_view', grn));
			frm.add_custom_button(__('Cancel Debit Note'), () =>
				frappe.prompt(
					[{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason for cancelling') }],
					(values) =>
						frappe.call({
							method: 'alpinos.purchase.grn_edit.cancel_debit_note',
							args: { debit_note: frm.doc.name, reason: values.reason || null },
							freeze: true,
							freeze_message: __('Cancelling the Debit Note...'),
							callback: (res) => !res.exc && frm.reload_doc(),
						}),
					__('Cancel Draft Debit Note {0}?', [frm.doc.name]),
					__('Cancel Debit Note')
				)
			);
		});
	},
});
