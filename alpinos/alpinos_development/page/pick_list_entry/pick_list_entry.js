frappe.pages['pick-list-entry'] = frappe.pages['pick-list-entry'] || {};

frappe.pages['pick-list-entry'].on_page_load = function(wrapper) {
	console.log("pick-list-entry on_page_load triggered");
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Pick List Entry',
		single_column: true
	});

	page.pick_list_name = frappe.get_route()[1];
	console.log("Pick list name from route:", page.pick_list_name);
	
	if (!page.pick_list_name) {
		console.warn("No Pick List specified. The page will render empty. Please click 'Pick List' from a Sales Order.");
		page.main.html('<h3>No Pick List specified. Please go to a Sales Order and click "Pick List" -> "Create".</h3>');
		return;
	}

	console.log("Setting primary action...");
	page.set_primary_action('Save', () => {
		page.save_pick_list();
	});

	console.log("Rendering template pick_list_entry...");
	try {
		let html = frappe.render_template("pick_list_entry", {});
		console.log("Rendered HTML length:", html ? html.length : "null/undefined");
		if (!html) {
			console.error("Template 'pick_list_entry' returned empty html.");
			page.main.html("<h3>Error: Template 'pick_list_entry' could not be rendered.</h3>");
		} else {
			page.main.html(html);
		}
	} catch (e) {
		console.error("Error rendering template:", e);
		page.main.html("<h3>Error rendering template: " + e.message + "</h3>");
	}

	console.log("Setting up load_data...");
	page.load_data = function() {
		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_pick_list_data',
			args: { name: page.pick_list_name },
			callback: function(r) {
				if (r.message) {
					page.render_data(r.message);
				}
			}
		});
	};
	
	page.render_data = function(data) {
		// Set header fields
		page.main.find('[data-fieldname="custom_actual_box"]').val(data.custom_actual_box);
		page.main.find('[data-fieldname="custom_sample_box"]').val(data.custom_sample_box);
		page.main.find('[data-fieldname="custom_sample_weight"]').val(data.custom_sample_weight);
		page.main.find('[data-fieldname="custom_total_box"]').val(data.custom_total_box);
		page.main.find('[data-fieldname="custom_gross_weight"]').val(data.custom_gross_weight);
		page.main.find('[data-fieldname="custom_total_unit"]').val(data.custom_total_unit);
		page.main.find('[data-fieldname="custom_po_no"]').val(data.custom_po_no);
		page.main.find('[data-fieldname="custom_transporter"]').val(data.custom_transporter);
		page.main.find('[data-fieldname="custom_customer_name"]').val(data.custom_customer_name);
		page.main.find('[data-fieldname="custom_party_code"]').val(data.custom_party_code);
		page.main.find('[data-fieldname="custom_order_date"]').val(data.custom_order_date);

		// Render table
		let tbody = page.main.find('.sku-table tbody');
		tbody.empty();
		
		(data.locations || []).forEach((row, i) => {
			let is_sample_only = ["Scheme Table", "Additional Units"].includes(row.custom_source_table);
			
			let tr = $(`
				<tr data-name="${row.name}">
					<td>${i + 1}</td>
					<td data-item-code="${row.item_code}">${row.item_code}</td>
					<td>${row.item_name || ''}</td>
					<td>${row.custom_ordered_qty || 0}</td>
					<td><input type="number" class="form-control input-sm qty-input" value="${row.qty}" ${is_sample_only ? 'disabled' : ''} /></td>
					<td><input type="number" class="form-control input-sm box-input" value="${row.custom_box || 0}" /></td>
					<td><input type="number" class="form-control input-sm sample-qty-input" value="${row.custom_sample_quantity || 0}" ${!is_sample_only ? 'disabled' : ''} /></td>
					<td><input type="text" list="batch-list" class="form-control input-sm batch-input" value="${row.batch_no || ''}" /></td>
					<td><input type="date" class="form-control input-sm mfg-input" value="${row.custom_mfg_date || ''}" /></td>
					<td><input type="date" class="form-control input-sm exp-input" value="${row.custom_expiry_date || ''}" /></td>
				</tr>
			`);
			tbody.append(tr);
		});
		
		// Setup Batch auto-fetch logic
		tbody.find('.batch-input').on('change', function() {
			let val = $(this).val();
			let tr = $(this).closest('tr');
			let item_code = tr.find('[data-item-code]').attr('data-item-code');
			
			if (val) {
				frappe.call({
					method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_batch_details',
					args: { batch_no: val, item_code: item_code },
					callback: function(res) {
						if (res.message) {
							tr.find('.mfg-input').val(res.message.manufacturing_date || '');
							tr.find('.exp-input').val(res.message.expiry_date || '');
						}
					}
				});
			}
		});

		// Fetch available batches for datalist
		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_active_batches',
			callback: function(res) {
				if(res.message) {
					let list = page.main.find('#batch-list');
					list.empty();
					res.message.forEach(b => {
						list.append(`<option value="${b}">`);
					});
				}
			}
		});
	};
	
	page.save_pick_list = function() {
		// Gather header data
		let header_data = {
			custom_actual_box: page.main.find('[data-fieldname="custom_actual_box"]').val(),
			custom_sample_box: page.main.find('[data-fieldname="custom_sample_box"]').val(),
			custom_sample_weight: page.main.find('[data-fieldname="custom_sample_weight"]').val(),
			custom_total_box: page.main.find('[data-fieldname="custom_total_box"]').val(),
			custom_gross_weight: page.main.find('[data-fieldname="custom_gross_weight"]').val(),
			custom_total_unit: page.main.find('[data-fieldname="custom_total_unit"]').val(),
			custom_po_no: page.main.find('[data-fieldname="custom_po_no"]').val(),
			custom_transporter: page.main.find('[data-fieldname="custom_transporter"]').val(),
		};
		
		// Gather item data
		let items = [];
		page.main.find('.sku-table tbody tr').each(function() {
			let tr = $(this);
			let is_sample_only = tr.find('.qty-input').prop('disabled');
			let qty_val = tr.find('.qty-input').val();
			let sample_qty_val = tr.find('.sample-qty-input').val();
			
			items.push({
				name: tr.attr('data-name'),
				item_code: tr.find('[data-item-code]').attr('data-item-code'),
				qty: is_sample_only ? sample_qty_val : qty_val,
				custom_sample_quantity: is_sample_only ? sample_qty_val : 0,
				custom_box: tr.find('.box-input').val(),
				batch_no: tr.find('.batch-input').val(),
				custom_mfg_date: tr.find('.mfg-input').val(),
				custom_expiry_date: tr.find('.exp-input').val(),
			});
		});

		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.save_pick_list_data',
			args: {
				name: page.pick_list_name,
				header: header_data,
				items: items
			},
			freeze: true,
			callback: function(r) {
				if(!r.exc) {
					frappe.show_alert({message: "Pick List Saved", indicator: "green"});
				}
			}
		});
	};

	page.load_data();
}