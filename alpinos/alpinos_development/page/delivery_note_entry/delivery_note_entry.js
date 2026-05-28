frappe.pages['delivery_note_entry'] = frappe.pages['delivery_note_entry'] || {};

frappe.pages['delivery_note_entry'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Delivery Note Entry',
		single_column: true
	});
	wrapper.page_instance = page;

	page.main.html(frappe.render_template('delivery_note_entry'));

	// Static buttons
	page.main.find('#btn-dn-back').on('click', function() {
		window.history.back();
	});
	page.main.find('#btn-dn-list').on('click', function() {
		frappe.set_route('delivery_note_entry_list');
	});
	page.main.find('#btn-dn-print').on('click', function() {
		if (page.dn_name) {
			frappe.set_route('print', 'Delivery Note', page.dn_name);
		}
	});
	page.main.find('#btn-dn-save').on('click', function() {
		page.save_dn(false);
	});
	page.main.find('#btn-dn-submit').on('click', function() {
		frappe.confirm(__('Submit this Delivery Note? This cannot be undone.'), function() {
			page.save_dn(true);
		});
	});

	page.load_data = function(dn_name) {
		frappe.call({
			method: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.get_delivery_note_data',
			args: { name: dn_name },
			callback: function(r) {
				if (r.message) {
					page.render_data(r.message);
				} else {
					page.main.html('<h3 class="text-muted text-center" style="margin-top: 50px;">Delivery Note not found.</h3>');
				}
			}
		});
	};

	page.render_data = function(data) {
		page.dn_name = data.name;
		page.docstatus = data.docstatus;

		// Header fields
		var $main = page.main;
		$main.find('[data-fieldname="posting_date"]').val(data.posting_date || '');
		$main.find('[data-fieldname="custom_sales_order_id"]').val(data.custom_sales_order_id || '');
		$main.find('[data-fieldname="pick_list_name"]').val(data.pick_list_name || '');
		$main.find('[data-fieldname="custom_lr_gr_no"]').val(data.custom_lr_gr_no || '');
		$main.find('[data-fieldname="custom_dispatch_from"]').val(data.custom_dispatch_from || '');
		$main.find('[data-fieldname="custom_dn_so_customer_name"]').val(data.custom_dn_so_customer_name || '');
		$main.find('[data-fieldname="custom_transporter_name"]').val(data.custom_transporter_name || '');
		$main.find('[data-fieldname="vehicle_no"]').val(data.vehicle_no || '');
		$main.find('[data-fieldname="custom_dispatch_date"]').val(data.custom_dispatch_date || '');

		// Totals
		$main.find('.total-value[data-fieldname="custom_total_boxes"]').text(data.custom_total_boxes || 0);
		$main.find('.total-value[data-fieldname="custom_dn_order_gross_weight"]').text(data.custom_dn_order_gross_weight || 0);
		$main.find('.total-value[data-fieldname="custom_total_units_dn"]').text(data.custom_total_units_dn || 0);

		// Items table
		var $tbody = $main.find('#dn-items-body').empty();
		(data.items || []).forEach(function(item, idx) {
			var mfg = item.custom_mfg_date || '';
			var exp = item.custom_expiry_date || '';
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

		page.apply_mode();
	};

	page.apply_mode = function() {
		var $main = page.main;
		var draft = page.docstatus === 0;
		var submitted = page.docstatus === 1;
		var cancelled = page.docstatus === 2;

		// Editable header fields — only when draft
		var editable_fields = [
			'custom_lr_gr_no',
			'custom_dispatch_from',
			'custom_transporter_name',
			'vehicle_no'
		];
		editable_fields.forEach(function(fn) {
			var $el = $main.find('[data-fieldname="' + fn + '"]');
			if (draft) {
				$el.prop('readonly', false).prop('disabled', false);
			} else {
				$el.prop('readonly', true);
				if ($el.is('select') || $el.is('textarea')) {
					$el.prop('disabled', true);
				}
			}
		});

		// Buttons
		$main.find('#btn-dn-save').toggle(draft);
		$main.find('#btn-dn-submit').toggle(draft);
		$main.find('#btn-dn-print').toggle(submitted);

		// Status banner
		var $banner = $main.find('#dn-status-banner');
		if (submitted) {
			$banner.css({ background: '#e8f5e9', color: '#2e7d32', border: '1px solid #c8e6c9' })
				.text('Submitted — read only').show();
		} else if (cancelled) {
			$banner.css({ background: '#ffebee', color: '#c62828', border: '1px solid #ffcdd2' })
				.text('Cancelled').show();
		} else {
			$banner.hide();
		}
	};

	page.collect_header = function() {
		var $main = page.main;
		return {
			custom_lr_gr_no: $main.find('[data-fieldname="custom_lr_gr_no"]').val() || null,
			custom_dispatch_from: $main.find('[data-fieldname="custom_dispatch_from"]').val() || null,
			custom_transporter_name: $main.find('[data-fieldname="custom_transporter_name"]').val() || null,
			vehicle_no: $main.find('[data-fieldname="vehicle_no"]').val() || null,
		};
	};

	page.save_dn = function(do_submit) {
		if (!page.dn_name) return;
		var header = page.collect_header();
		var method = do_submit
			? 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.submit_delivery_note'
			: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.save_delivery_note_data';
		frappe.call({
			method: method,
			args: {
				name: page.dn_name,
				header: JSON.stringify(header),
			},
			freeze: true,
			freeze_message: do_submit ? __('Submitting...') : __('Saving...'),
			callback: function(r) {
				if (r.exc) return;
				frappe.show_alert({
					message: do_submit ? __('Delivery Note submitted') : __('Saved'),
					indicator: 'green'
				});
				page.load_data(page.dn_name);
			}
		});
	};
};

frappe.pages['delivery_note_entry'].on_page_show = function(wrapper) {
	if (!wrapper.page_instance) return;
	var dn_name = frappe.get_route()[1];
	if (!dn_name) {
		wrapper.page_instance.main.html('<h3 class="text-muted text-center" style="margin-top: 50px;">No Delivery Note specified.</h3>');
		return;
	}
	wrapper.page_instance.set_title('Delivery Note - ' + dn_name);
	wrapper.page_instance.load_data(dn_name);
};
