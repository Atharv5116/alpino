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
	page.main.find('#btn-dn-dispatch-to-add').on('click', function() {
		page.add_dispatch_to_row('');
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
		page.original_item_names = (data.items || []).map(function(i) { return i.name; });

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
		page.populate_assigned_to_select(data.custom_assigned_to || '');

		// Totals
		$main.find('.total-value[data-fieldname="custom_total_boxes"]').text(data.custom_total_boxes || 0);
		$main.find('.total-value[data-fieldname="custom_dn_order_gross_weight"]').text(data.custom_dn_order_gross_weight || 0);
		$main.find('.total-value[data-fieldname="custom_total_units_dn"]').text(data.custom_total_units_dn || 0);

		// Items table
		var draft = data.docstatus === 0;
		var $tbody = $main.find('#dn-items-body').empty();
		(data.items || []).forEach(function(item, idx) {
			var mfg = item.custom_mfg_date || '';
			var exp = item.custom_expiry_date || '';
			if (mfg && mfg.length > 10) mfg = mfg.substring(0, 10);
			if (exp && exp.length > 10) exp = exp.substring(0, 10);
			var qty_cell = draft
				? `<input type="number" min="0" step="any" class="form-control input-xs dn-item-qty" data-row-name="${frappe.utils.escape_html(item.name || '')}" value="${item.qty || 0}" style="text-align:center; padding:2px 4px; height:28px;">`
				: (item.qty || 0);
			var action_cell = draft
				? `<td class="dn-col-action"><button type="button" class="btn btn-xs btn-danger dn-item-remove" data-row-name="${frappe.utils.escape_html(item.name || '')}" title="Remove">&times;</button></td>`
				: '<td class="dn-col-action" style="display:none;"></td>';
			$tbody.append(`
				<tr data-row-name="${frappe.utils.escape_html(item.name || '')}">
					<td>${idx + 1}</td>
					<td>${frappe.utils.escape_html(item.item_code || '')}</td>
					<td style="text-align: left;">${frappe.utils.escape_html(item.item_name || '')}</td>
					<td>${qty_cell}</td>
					<td>${item.custom_box || 0}</td>
					<td>${frappe.utils.escape_html(item.batch_no || '')}</td>
					<td>${mfg}</td>
					<td>${exp}</td>
					${action_cell}
				</tr>
			`);
		});
		if (!data.items || data.items.length === 0) {
			$tbody.append('<tr><td colspan="9" class="text-muted text-center">No items</td></tr>');
		}

		// Show/hide the action column header for draft
		$main.find('th.dn-col-action').toggle(draft);

		// Wire up remove buttons
		$main.find('.dn-item-remove').off('click').on('click', function() {
			var $btn = $(this);
			frappe.confirm(__('Remove this item from the Delivery Note?'), function() {
				$btn.closest('tr').remove();
			});
		});

		// Dispatch To rows
		page.render_dispatch_to(data.custom_dispatch_to || []);

		page.apply_mode();
	};

	page.render_dispatch_to = function(rows) {
		var $wrap = page.main.find('#dn-dispatch-to-rows').empty();
		if (!rows.length) {
			$wrap.append('<div class="text-muted" style="font-size:12px; margin-bottom:8px;">No Dispatch To address yet — click "+ Add row" to add one.</div>');
		}
		rows.forEach(function(r) {
			page.add_dispatch_to_row(r.dispatch_to_address || '');
		});
	};

	page.add_dispatch_to_row = function(text) {
		var draft = page.docstatus === 0;
		var $wrap = page.main.find('#dn-dispatch-to-rows');
		// Drop the empty-state hint if it's there.
		$wrap.find('.text-muted').remove();
		var $row = $(`
			<div class="dn-dispatch-to-row" style="display:flex; gap:6px; margin-bottom:6px; align-items:flex-start;">
				<textarea class="form-control dn-dispatch-to-input" rows="2" style="flex:1; resize:vertical;"></textarea>
				<button type="button" class="btn btn-xs btn-danger dn-dispatch-to-remove" title="Remove" style="display:${draft ? '' : 'none'};">&times;</button>
			</div>
		`);
		$row.find('textarea').val(text || '').prop('readonly', !draft);
		$row.find('.dn-dispatch-to-remove').on('click', function() {
			$row.remove();
			if (!$wrap.find('.dn-dispatch-to-row').length) {
				$wrap.append('<div class="text-muted" style="font-size:12px; margin-bottom:8px;">No Dispatch To address yet — click "+ Add row" to add one.</div>');
			}
		});
		$wrap.append($row);
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
		$main.find('#btn-dn-dispatch-to-add').toggle(draft);
		$main.find('.dn-dispatch-to-input').prop('readonly', !draft);
		$main.find('.dn-dispatch-to-remove').toggle(draft);

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
			custom_lr_gr_no: ($main.find('[data-fieldname="custom_lr_gr_no"]').val() || '').trim() || null,
			custom_dispatch_from: ($main.find('[data-fieldname="custom_dispatch_from"]').val() || '').trim() || null,
			custom_transporter_name: $main.find('[data-fieldname="custom_transporter_name"]').val() || null,
			vehicle_no: ($main.find('[data-fieldname="vehicle_no"]').val() || '').trim() || null,
			custom_assigned_to: $main.find('[data-fieldname="custom_assigned_to"]').val() || null,
		};
	};

	// Assigned To select — populated from active users; auto-saves on change so
	// the value sticks even when the DN is submitted (custom field is
	// allow_on_submit=1).
	page.populate_assigned_to_select = function(current_value) {
		var $select = page.main.find('[data-fieldname="custom_assigned_to"]');
		if ($select.data('alpinos-populated')) {
			$select.val(current_value || '');
			return;
		}
		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_active_users',
			callback: function(r) {
				if (!r.message) return;
				$select.empty().append('<option value=""></option>');
				r.message.forEach(function(u) {
					$select.append('<option value="' + frappe.utils.escape_html(u) + '">' + frappe.utils.escape_html(u) + '</option>');
				});
				$select.val(current_value || '');
				$select.data('alpinos-populated', true);
				$select.off('change.alpinosAssign').on('change.alpinosAssign', function() {
					if (!page.dn_name) return;
					var val = $(this).val() || '';
					frappe.call({
						method: 'alpinos.delivery_note_api.update_delivery_note_assignment',
						args: { delivery_note: page.dn_name, assigned_to: val },
						callback: function() {
							frappe.show_alert({ message: __('Assigned To updated'), indicator: 'green' }, 3);
						}
					});
				});
			}
		});
	};

	page.collect_items = function() {
		var rows = [];
		page.main.find('#dn-items-body tr[data-row-name]').each(function() {
			var $tr = $(this);
			var name = $tr.attr('data-row-name');
			if (!name) return;
			var $qty = $tr.find('.dn-item-qty');
			rows.push({
				name: name,
				qty: $qty.length ? $qty.val() : undefined,
			});
		});
		// Also collect removed rows (compare against original)
		var visible = new Set(rows.map(function(r) { return r.name; }));
		(page.original_item_names || []).forEach(function(n) {
			if (!visible.has(n)) rows.push({ name: n, delete: true });
		});
		return rows;
	};

	page.collect_dispatch_to = function() {
		var rows = [];
		page.main.find('.dn-dispatch-to-input').each(function() {
			var text = ($(this).val() || '').trim();
			if (text) rows.push({ dispatch_to_address: text });
		});
		return rows;
	};

	page.validate_before_submit = function(header, dispatch_to) {
		var missing = [];
		if (!header.custom_dispatch_from) missing.push('Dispatch From');
		if (!header.custom_transporter_name) missing.push('Transporter');
		if (!header.vehicle_no) missing.push('Vehicle No.');
		if (!header.custom_lr_gr_no) missing.push('LR No.');
		if (!dispatch_to || !dispatch_to.length) missing.push('At least one Dispatch To row');
		// Per-row qty
		page.main.find('.dn-item-qty').each(function() {
			var v = parseFloat($(this).val());
			if (!v || v <= 0) {
				missing.push('Quantity in row ' + ($(this).closest('tr').index() + 1));
			}
		});
		return missing;
	};

	page.save_dn = function(do_submit) {
		if (!page.dn_name) return;
		var header = page.collect_header();
		var items = page.collect_items();
		var dispatch_to = page.collect_dispatch_to();
		if (do_submit) {
			var missing = page.validate_before_submit(header, dispatch_to);
			if (missing.length) {
				frappe.msgprint({
					title: __('Required fields missing'),
					message: missing.map(function(m) { return '• ' + m; }).join('<br>'),
					indicator: 'red',
				});
				return;
			}
		}
		var method = do_submit
			? 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.submit_delivery_note'
			: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.save_delivery_note_data';
		frappe.call({
			method: method,
			args: {
				name: page.dn_name,
				header: JSON.stringify(header),
				items: JSON.stringify(items),
				dispatch_to: JSON.stringify(dispatch_to),
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
