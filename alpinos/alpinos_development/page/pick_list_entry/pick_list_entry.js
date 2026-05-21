frappe.pages['pick_list_entry'] = frappe.pages['pick_list_entry'] || {};

frappe.pages['pick_list_entry'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Pick List Entry',
		single_column: true
	});

	page.pick_list_name = frappe.get_route()[1];
	
	if (!page.pick_list_name) {
		page.main.html('<h3>No Pick List specified. Please go to a Sales Order and click "Pick List" -> "Create".</h3>');
		return;
	}

	page.set_primary_action('Save', () => {
		page.save_pick_list();
	});

	try {
		let html = frappe.render_template("pick_list_entry", {});
		if (!html) {
			page.main.html("<h3>Error: Template 'pick_list_entry' could not be rendered.</h3>");
		} else {
			page.main.html(html);
			
			// Setup static listeners
			page.main.find('#btn-go-to-list').on('click', function() {
				frappe.set_route('List', 'Pick List');
			});
		}
	} catch (e) {
		page.main.html("<h3>Error rendering template: " + e.message + "</h3>");
	}

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

		let container = page.main.find('#tables-container');
		container.empty();
		
		let groups = {
			"Items": [],
			"Scheme Table": [],
			"Marketing Freebies": [],
			"Additional Units": []
		};
		
		(data.locations || []).forEach(row => {
			let src = row.custom_source_table || "Items";
			if (!groups[src]) groups[src] = [];
			groups[src].push(row);
		});
		
		const create_table = (title, rows) => {
			if (!rows || rows.length === 0) return;
			
			let is_sample_only = ["Scheme Table", "Additional Units"].includes(title);
			
			let html = `
				<div class="table-section-title">${title}</div>
				<table class="sku-table" data-table-name="${title}">
					<thead>
						<tr>
							<th>SR.</th>
							<th>SKU</th>
							<th>SKU NO</th>
							<th>ORDERED QTY</th>
							${!is_sample_only ? '<th>PICKED QTY</th>' : ''}
							<th>BOX</th>
							<th>SAMPLE QTY</th>
							<th>BATCH CODE</th>
							<th>MFG</th>
							<th>EXP</th>
						</tr>
					</thead>
					<tbody>
			`;
			
			rows.forEach((row, i) => {
				html += `
					<tr data-name="${row.name}">
						<td>${i + 1}</td>
						<td data-item-code="${row.item_code}">${row.item_code}</td>
						<td>${row.item_name || ''}</td>
						<td class="ordered-qty-cell">${row.custom_ordered_qty || 0}</td>
						${!is_sample_only ? `<td><input type="number" class="form-control input-sm qty-input" value="${row.picked_qty || ''}" /></td>` : ''}
						<td><input type="number" class="form-control input-sm box-input" value="${row.custom_box || 0}" /></td>
						<td><input type="number" class="form-control input-sm sample-qty-input" value="${row.custom_sample_quantity || 0}" /></td>
						<td><input type="text" list="batch-list" class="form-control input-sm batch-input" value="${row.custom_batch_code || row.batch_no || ''}" /></td>
						<td><input type="date" class="form-control input-sm mfg-input" value="${row.custom_mfg_date || ''}" /></td>
						<td><input type="date" class="form-control input-sm exp-input" value="${row.custom_expiry_date || ''}" /></td>
					</tr>
				`;
			});
			
			html += `</tbody></table>`;
			container.append(html);
		};
		
		create_table("Items", groups["Items"]);
		create_table("Marketing Freebies", groups["Marketing Freebies"]);
		create_table("Scheme Table", groups["Scheme Table"]);
		create_table("Additional Units", groups["Additional Units"]);
		
		// Validation logic for Picked Qty
		container.find('.qty-input').on('change', function() {
			let tr = $(this).closest('tr');
			let ordered = flt(tr.find('.ordered-qty-cell').text());
			let picked = flt($(this).val());
			
			if (picked > ordered) {
				frappe.msgprint(__("Picked Qty cannot be greater than Ordered Qty"));
				$(this).val(ordered); // Reset to max allowed
			}
		});
		
		// Setup Batch auto-fetch logic
		container.find('.batch-input').on('change', function() {
			let val = $(this).val();
			let tr = $(this).closest('tr');
			let item_code = tr.find('[data-item-code]').attr('data-item-code');
			
			if (val) {
				frappe.call({
					method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_batch_details',
					args: { batch_no: val, item_code: item_code },
					callback: function(res) {
						if (res.message) {
							// Ensure format is YYYY-MM-DD for date inputs
							let mfg = res.message.manufacturing_date ? frappe.datetime.str_to_obj(res.message.manufacturing_date) : null;
							let exp = res.message.expiry_date ? frappe.datetime.str_to_obj(res.message.expiry_date) : null;
							
							tr.find('.mfg-input').val(mfg ? frappe.datetime.obj_to_str(mfg) : '');
							tr.find('.exp-input').val(exp ? frappe.datetime.obj_to_str(exp) : '');
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

		// Fetch users for QC dropdown
		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_active_users',
			callback: function(res) {
				if(res.message) {
					let qc_select = page.main.find('[data-fieldname="custom_qc_attended_by"]');
					qc_select.empty();
					qc_select.append(`<option value=""></option>`);
					res.message.forEach(u => {
						qc_select.append(`<option value="${u}">${u}</option>`);
					});
					// Set previously saved value if any
					if (data.custom_qc_attended_by) {
						qc_select.val(data.custom_qc_attended_by);
					}
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
			let table_name = tr.closest('table').attr('data-table-name');
			let is_sample_only = ["Scheme Table", "Additional Units"].includes(table_name);
			let qty_val = is_sample_only ? 0 : tr.find('.qty-input').val();
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