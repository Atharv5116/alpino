frappe.listview_settings['Pick List'] = {
	onload: function(listview) {
		// Override the row click action
		listview.page.main.on('click', '.list-row, .list-row-col', function(e) {
			// Don't trigger if they clicked on a checkbox or a button
			if ($(e.target).closest('input[type="checkbox"], .btn').length) {
				return;
			}
			
			// Get the document name from the row
			let docname = $(this).closest('.list-row').attr('data-name');
			if (docname) {
				e.preventDefault();
				e.stopPropagation();
				frappe.set_route('app', 'pick-list-entry', { name: docname });
			}
		});
	}
};
