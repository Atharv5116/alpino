frappe.pages['delivery_note_entry'] = frappe.pages['delivery_note_entry'] || {};

frappe.pages['delivery_note_entry'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Delivery Note Entry',
		single_column: true
	});
	wrapper.page_instance = page;

	page.main.html(frappe.render_template('delivery_note_entry'));

	page.main.find('#btn-dn-back').on('click', function() {
		window.history.back();
	});

	page.load_data = function(dn_name) {
		frappe.call({
			method: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.get_delivery_note_data',
			args: { name: dn_name },
			callback: function(r) {
				if (r.message) {
					page.render_data(r.message);
				}
			}
		});
	};

	page.render_data = function(data) {
		// Header fields
		page.main.find('[data-fieldname="posting_date"]').val(data.posting_date || '');
		page.main.find('[data-fieldname="custom_sales_order_id"]').val(data.custom_sales_order_id || '');
		page.main.find('[data-fieldname="pick_list_name"]').val(data.pick_list_name || '');
		page.main.find('[data-fieldname="custom_lr_gr_no"]').val(data.custom_lr_gr_no || '');
		page.main.find('[data-fieldname="custom_dn_so_customer_name"]').val(data.custom_dn_so_customer_name || '');
		page.main.find('[data-fieldname="custom_transporter_name"]').val(data.custom_transporter_name || '');
		page.main.find('[data-fieldname="vehicle_no"]').val(data.vehicle_no || '');
		page.main.find('[data-fieldname="custom_dispatch_date"]').val(data.custom_dispatch_date || '');

		// Totals
		page.main.find('.total-value[data-fieldname="custom_total_boxes"]').text(data.custom_total_boxes || 0);
		page.main.find('.total-value[data-fieldname="custom_dn_order_gross_weight"]').text(data.custom_dn_order_gross_weight || 0);
		page.main.find('.total-value[data-fieldname="custom_total_units_dn"]').text(data.custom_total_units_dn || 0);

		// Items table
		var $tbody = page.main.find('#dn-items-body');
		$tbody.empty();

		(data.items || []).forEach(function(item, idx) {
			var mfg = item.custom_mfg_date || '';
			var exp = item.custom_expiry_date || '';
			// Format datetime to date-only for display
			if (mfg && mfg.length > 10) mfg = mfg.substring(0, 10);
			if (exp && exp.length > 10) exp = exp.substring(0, 10);

			$tbody.append(`
				<tr>
					<td>${idx + 1}</td>
					<td>${frappe.utils.escape_html(item.item_code || '')}</td>
					<td style="text-align: left;">${frappe.utils.escape_html(item.item_name || '')}</td>
					<td>${item.qty || 0}</td>
					<td>${item.custom_box || 0}</td>
					<td>${frappe.utils.escape_html(item.batch_no || '')}</td>
					<td>${mfg}</td>
					<td>${exp}</td>
				</tr>
			`);
		});

		if (!data.items || data.items.length === 0) {
			$tbody.append('<tr><td colspan="8" class="text-muted text-center">No items</td></tr>');
		}

		// Save editable fields on change
		page.main.find('[data-fieldname="custom_lr_gr_no"]').off('change').on('change', function() {
			page._save_field(data.name, 'custom_lr_gr_no', $(this).val());
		});
		page.main.find('[data-fieldname="vehicle_no"]').off('change').on('change', function() {
			page._save_field(data.name, 'vehicle_no', $(this).val());
		});
	};

	page._save_field = function(dn_name, fieldname, value) {
		frappe.call({
			method: 'frappe.client.set_value',
			args: {
				doctype: 'Delivery Note',
				name: dn_name,
				fieldname: fieldname,
				value: value
			},
			callback: function() {
				frappe.show_alert({ message: __('{0} updated', [fieldname]), indicator: 'green' }, 2);
			}
		});
	};
};

frappe.pages['delivery_note_entry'].on_page_show = function(wrapper) {
	if (wrapper.page_instance) {
		var dn_name = frappe.get_route()[1];
		if (!dn_name) {
			wrapper.page_instance.main.html('<h3 class="text-muted text-center" style="margin-top: 50px;">No Delivery Note specified.</h3>');
			return;
		}
		wrapper.page_instance.set_title('Delivery Note - ' + dn_name);
		wrapper.page_instance.load_data(dn_name);
	}
};
