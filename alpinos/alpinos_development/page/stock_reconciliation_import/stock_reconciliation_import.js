frappe.pages['stock-reconciliation-import'].on_page_load = function(wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Alpino Stock Reconciliation Import'),
		single_column: true
	});
};

// Every visit: get (or create) a Data Import pre-filled with Stock Reconciliation and jump
// straight to the native Data Import form — the upload step. Column mapping,
// preview, status and error logs are all standard Data Import.
frappe.pages['stock-reconciliation-import'].on_page_show = function() {
	frappe.call({
		method: 'alpinos.data_import_shortcuts.get_or_create_data_import',
		args: { reference_doctype: 'Stock Reconciliation' },
		freeze: true,
		freeze_message: __('Preparing Stock Reconciliation import...'),
		callback: function(r) {
			if (r.message) frappe.set_route('Form', 'Data Import', r.message);
		}
	});
};
