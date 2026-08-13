// Shared "Change Log" viewer for the Pick List and Delivery Note entry pages.
// Loaded globally (app_include_js) so either page can open it on its own —
// defining it inside one page would leave the other with an undefined function.
// Change Log — the Transporter / LR No. / Dispatch Date edits recorded by
// after_submit_sync, shown where the edits happen instead of only in the
// Field Change Log list.
function alpinos_show_change_log(doctype, name) {
	if (!name) {
		frappe.msgprint(__('Open a document first.'));
		return;
	}
	frappe.call({
		method: 'alpinos.after_submit_sync.get_field_change_log',
		args: { reference_doctype: doctype, reference_name: name },
		freeze: true,
		freeze_message: __('Loading change log...'),
		callback: (r) => {
			const rows = ((r.message || {}).rows) || [];
			const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
			let html;
			if (!rows.length) {
				html = `<p class="text-muted">${__('No changes recorded for this document.')}</p>`;
			} else {
				html = '<table class="table table-bordered" style="font-size:12px; margin:0;"><thead><tr>' +
					`<th>${__('Field')}</th><th>${__('Previous')}</th><th>${__('New')}</th>` +
					`<th>${__('Changed By')}</th><th>${__('Changed On')}</th></tr></thead><tbody>`;
				rows.forEach((d) => {
					html += '<tr>' +
						'<td>' + esc(d.field_label) + '</td>' +
						'<td>' + (esc(d.previous_value) || '<span class="text-muted">—</span>') + '</td>' +
						'<td><b>' + esc(d.new_value) + '</b></td>' +
						'<td>' + esc(d.changed_by_name) + '</td>' +
						'<td>' + esc(frappe.datetime.str_to_user(d.changed_on)) + '</td>' +
						'</tr>';
				});
				html += '</tbody></table>';
			}
			new frappe.ui.Dialog({
				title: __('Change Log — {0}', [name]),
				size: 'large',
				fields: [{ fieldtype: 'HTML', fieldname: 'log', options: html }],
			}).show();
		},
	});
}
