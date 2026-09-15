// Purchase Inward GRNs on the standard Purchase Receipt form.
//
// Frappe offers Cancel only on a submitted document, so a Draft GRN opened here had no way
// to be cancelled, and neither had its Debit Note. The GRN screen's own endpoints are reused
// (alpinos.purchase.grn_edit), and what is offered comes from get_grn_context, so this form
// never shows a button the server would refuse.

frappe.ui.form.on('Purchase Receipt', {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.custom_purchase_inward || cint(frm.doc.is_return)) return;

		frm.add_custom_button(__('GRN Detail'), () => frappe.set_route('purchase_grn_view', frm.doc.name));

		frappe.call({
			method: 'alpinos.purchase.grn_edit.get_grn_context',
			args: { purchase_receipt: frm.doc.name },
			callback(r) {
				const ctx = (r && r.message) || {};
				// A submitted GRN keeps Frappe's own Cancel; only the draft needs one.
				if (cint(frm.doc.docstatus) === 0 && cint(ctx.can_cancel)) {
					frm.add_custom_button(__('Cancel GRN'), () =>
						alpinos_grn_prompt_cancel(
							__('Cancel Draft GRN {0}?', [frm.doc.name]),
							__('Cancel GRN'),
							false,
							(reason) =>
								frappe.call({
									method: 'alpinos.purchase.grn_edit.cancel_grn',
									args: { purchase_receipt: frm.doc.name, reason: reason },
									freeze: true,
									callback: (res) => !res.exc && frm.reload_doc(),
								})
						)
					);
				}
				if (cint(ctx.can_cancel_debit_note)) {
					const submitted = cint(ctx.debit_note_docstatus) === 1;
					frm.add_custom_button(
						__('Cancel Debit Note'),
						() =>
							alpinos_grn_prompt_cancel(
								submitted
									? __('Cancel submitted Debit Note {0}? Its accounting entries are reversed.', [ctx.debit_note])
									: __('Cancel Draft Debit Note {0}?', [ctx.debit_note]),
								__('Cancel Debit Note'),
								submitted,
								(reason) =>
									frappe.call({
										method: 'alpinos.purchase.grn_edit.cancel_debit_note',
										args: { purchase_receipt: frm.doc.name, debit_note: ctx.debit_note, reason: reason },
										freeze: true,
										callback: (res) => !res.exc && frm.reload_doc(),
									})
							),
						__('Debit Note')
					);
				}
			},
		});
	},
});

function alpinos_grn_prompt_cancel(title, primary, reason_required, run) {
	frappe.prompt(
		[{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason for cancelling'), reqd: reason_required ? 1 : 0 }],
		(values) => run(values.reason || null),
		title,
		primary
	);
}
