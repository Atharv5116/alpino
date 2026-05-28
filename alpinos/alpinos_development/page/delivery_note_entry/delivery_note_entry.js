frappe.pages['delivery_note_entry'] = frappe.pages['delivery_note_entry'] || {};

frappe.pages['delivery_note_entry'].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Delivery Note',
		single_column: true
	});
	wrapper.page_instance = page;

	try {
		const html = frappe.render_template("delivery_note_entry", {});
		page.main.html(html);
	} catch (e) {
		page.main.html("<h3>Error rendering template: " + e.message + "</h3>");
		return;
	}

	page.main.find('#dn-btn-list').on('click', function() {
		frappe.set_route('List', 'Delivery Note');
	});

	page.main.find('#dn-btn-print').on('click', function() {
		if (page.dn_name) {
			frappe.set_route('print', 'Delivery Note', page.dn_name);
		}
	});

	page.main.find('#dn-btn-submit').on('click', function() {
		page.submit_dn();
	});

	page.load_data = function() {
		frappe.call({
			method: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.get_delivery_note_data',
			args: { name: page.dn_name },
			callback: function(r) {
				if (r.message) {
					page.render_data(r.message);
				} else {
					page.main.html('<h3>Delivery Note not found.</h3>');
				}
			}
		});
	};

	page.render_data = function(data) {
		const editable = data.docstatus === 0;
		const $main = page.main;

		// Header fields
		const setVal = (fn, v) => {
			const $el = $main.find(`[data-fieldname="${fn}"]`);
			$el.val(v == null ? '' : v);
			if (!editable && $el.is('input, select, textarea')) {
				$el.attr('readonly', true);
				$el.attr('disabled', $el.is('select') ? true : false);
			}
		};

		setVal('customer', data.customer);
		setVal('posting_date', data.posting_date);
		setVal('sales_order_no', data.sales_order_no);
		setVal('pick_list_no', data.pick_list_no);
		setVal('transporter', data.transporter);
		setVal('lr_no', data.lr_no);
		setVal('lr_date', data.lr_date);
		setVal('vehicle_no', data.vehicle_no);
		setVal('driver_name', data.driver_name);
		setVal('custom_dispatch_date', data.custom_dispatch_date);

		// Items — qty/rate come from the pick list logic; show as read-only.
		const $tbody = $main.find('#dn-items-table tbody').empty();
		(data.items || []).forEach((row, idx) => {
			const qty = flt(row.qty || 0);
			const rate = flt(row.rate || 0);
			$tbody.append(`
				<tr data-name="${row.name}">
					<td>${idx + 1}</td>
					<td>${frappe.utils.escape_html(row.item_code || '')}</td>
					<td style="text-align:left;">${frappe.utils.escape_html(row.description || row.item_name || '')}</td>
					<td>${flt(qty, 2)}</td>
					<td>${frappe.utils.escape_html(row.uom || '')}</td>
					<td>${flt(rate, 2)}</td>
					<td>${flt(qty * rate, 2)}</td>
					<td>${frappe.utils.escape_html(row.warehouse || '')}</td>
					<td>${frappe.utils.escape_html(row.batch_no || '')}</td>
				</tr>
			`);
		});

		// Show/hide actions based on docstatus
		if (editable) {
			$main.find('#dn-btn-submit').show();
			$main.find('#dn-btn-print').hide();
		} else {
			$main.find('#dn-btn-submit').hide();
			$main.find('#dn-btn-print').show();
		}

		page.recalc_totals();
		page.bind_row_inputs();
	};

	page.bind_row_inputs = function() {
		// Items are read-only on this page; nothing to bind on the rows.
	};

	page.recalc_totals = function() {
		// Totals are derived from the DN data directly since items are not editable.
		let total_qty = 0;
		let grand_total = 0;
		page.main.find('#dn-items-table tbody tr').each(function() {
			const $tr = $(this);
			const cells = $tr.find('td');
			total_qty += flt(cells.eq(3).text());
			grand_total += flt(cells.eq(6).text());
		});
		page.main.find('[data-fieldname="total_qty"]').val(flt(total_qty, 2));
		page.main.find('[data-fieldname="grand_total"]').val(flt(grand_total, 2));
	};

	page.collect_payload = function() {
		// Only the logistics fields are user-editable; everything else stays as
		// set by the create_delivery_note_from_pick_list backend logic.
		const header = {
			lr_no: page.main.find('[data-fieldname="lr_no"]').val() || null,
			lr_date: page.main.find('[data-fieldname="lr_date"]').val() || null,
			vehicle_no: page.main.find('[data-fieldname="vehicle_no"]').val() || null,
			driver_name: page.main.find('[data-fieldname="driver_name"]').val() || null,
			transporter: page.main.find('[data-fieldname="transporter"]').val() || null,
		};
		return { header, items: [] };
	};

	page.submit_dn = function() {
		const payload = page.collect_payload();
		frappe.confirm(__('Submit this Delivery Note? This cannot be undone.'), function() {
			frappe.call({
				method: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.submit_delivery_note',
				args: {
					name: page.dn_name,
					header: JSON.stringify(payload.header),
					items: JSON.stringify(payload.items),
				},
				freeze: true,
				freeze_message: __('Submitting Delivery Note...'),
				callback: function(r) {
					if (!r.exc) {
						frappe.show_alert({ message: __('Delivery Note submitted'), indicator: 'green' });
						page.load_data();
					}
				}
			});
		});
	};
};

frappe.pages['delivery_note_entry'].on_page_show = function(wrapper) {
	if (!wrapper.page_instance) return;
	const name = frappe.get_route()[1];
	if (!name) {
		wrapper.page_instance.main.html('<h3>No Delivery Note specified.</h3>');
		return;
	}
	wrapper.page_instance.dn_name = name;
	wrapper.page_instance.load_data();
};
