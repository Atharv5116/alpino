frappe.pages['pick_list_entry'] = frappe.pages['pick_list_entry'] || {};

frappe.pages['pick_list_entry'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Pick List Entry',
		single_column: true
	});
	wrapper.page_instance = page;

	page.set_primary_action('Submit', () => {
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
				frappe.set_route('pick_list_list');
			});

			page.main.find('#btn-create-delivery-note').on('click', function() {
				frappe.call({
					method: 'alpinos.pick_list_api.create_delivery_note_from_pick_list',
					args: {
						pick_list_name: page.pick_list_name
					},
					freeze: true,
					freeze_message: __("Creating Delivery Note..."),
					callback: function(r) {
						if (!r.exc && r.message) {
							frappe.show_alert({message: __("Delivery Note {0} created successfully", [r.message]), indicator: "green"});
							frappe.set_route('Form', 'Delivery Note', r.message);
						}
					}
				});
			});
		}
	} catch (e) {
		page.main.html("<h3>Error rendering template: " + e.message + "</h3>");
	}

	page.load_data = function() {
		if (page.pick_list_name === 'New Pick List') {
			let so_name = frappe.route_options ? frappe.route_options.so_name : null;
			if (!so_name) {
				page.main.html('<h3>Missing Sales Order context for New Pick List.</h3>');
				return;
			}
			page.so_name = so_name;
			frappe.call({
				method: 'alpinos.sales_order_api.get_pick_list_mapping_data',
				args: { sales_order: so_name },
				callback: function(r) {
					if (r.message) {
						page.render_data(r.message);
					}
				}
			});
		} else {
			frappe.call({
				method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_pick_list_data',
				args: { name: page.pick_list_name },
				callback: function(r) {
					if (r.message) {
						page.render_data(r.message);
					}
				}
			});
		}
	};
	
	page.render_data = function(data) {
		if (data.docstatus === 1) {
			page.clear_primary_action();
			page.main.find('#btn-create-delivery-note').show();
		} else {
			page.main.find('#btn-create-delivery-note').hide();
		}
		
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
		page.main.find('[data-fieldname="custom_sales_order_id"]').val(data.custom_sales_order_id);

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
			
			let html = `
				<div class="table-section-title">${title}</div>
				<table class="sku-table" data-table-name="${title}">
					<thead>
						<tr>
							<th>SR.</th>
							<th>SKU</th>
							<th>SKU NO</th>
							<th>ORDERED QTY</th>
							<th>PICKED QTY</th>
							<th>BOX</th>
							<th>BATCH CODE</th>
							<th>MFG</th>
							<th>EXP</th>
							<th>REMARK</th>
						</tr>
					</thead>
					<tbody>
			`;
			
			rows.forEach((row, idx) => {
			let src = row.custom_source_table || "Items";
			
			let batch_readonly = data.docstatus === 1 ? 'readonly' : '';
			let input_disabled = data.docstatus === 1 ? 'disabled' : '';
			
			let box_val = "";
			if (title === "Items") {
				box_val = (row.custom_box !== undefined && row.custom_box !== null) ? cint(row.custom_box) : 0;
			} else {
				box_val = (row.custom_box !== undefined && row.custom_box !== null && cint(row.custom_box) !== 0) ? cint(row.custom_box) : "";
			}
			
			let row_html = `
				<tr data-name="${row.name}" data-conversion-factor="${row.custom_conversion_factor || 1}" data-weight-per-box="${row.custom_weight_per_box || 0}">
					<td>${idx + 1}</td>
					<td data-item-code="${row.item_code}">${row.item_code}</td>
					<td>${row.custom_sku_no || '-'}</td>
					<td class="ordered-qty-cell">${row.custom_ordered_qty !== undefined && row.custom_ordered_qty !== null ? row.custom_ordered_qty : (row.qty || 0)}</td>
					<td><input type="number" class="form-control input-sm qty-input" value="${row.qty !== undefined && row.qty !== null ? row.qty : ''}" min="0" ${input_disabled}/></td>
					<td><input type="number" class="form-control input-sm box-input" value="${box_val}" step="1" min="0" ${input_disabled}/></td>
					<td>
						<input type="text" class="form-control input-sm batch-input" list="batch-list" value="${row.custom_batch_code || row.batch_no || ''}" ${batch_readonly}>
					</td>
					<td><input type="date" class="form-control input-sm mfg-input" value="${row.custom_mfg_date || ''}" max="9999-12-31" ${batch_readonly}></td>
					<td><input type="date" class="form-control input-sm exp-input" value="${row.custom_expiry_date || ''}" max="9999-12-31" ${batch_readonly}></td>
					<td><input type="text" class="form-control input-sm remark-input" value="${row.custom_remark || ''}" ${batch_readonly}></td>
				</tr>
			`;
			html += row_html;
		});	
			html += `</tbody></table>`;
			container.append(html);
		};
		
		create_table("Items", groups["Items"]);
		create_table("Marketing Freebies", groups["Marketing Freebies"]);
		create_table("Scheme Table", groups["Scheme Table"]);
		create_table("Additional Units", groups["Additional Units"]);
		
		// Define recalculate_totals function
		page.recalculate_totals = function() {
			let actual_box = 0;
			let sample_box = 0;
			let sample_weight = 0;
			let gross_weight = 0;
			let total_unit = 0;

			page.main.find('.sku-table tbody tr').each(function() {
				let tr = $(this);
				let table_name = tr.closest('table').attr('data-table-name');
				
				let qty = flt(tr.find('.qty-input').val());
				let factor = flt(tr.attr('data-conversion-factor')) || 1;
				let weight_per_box = flt(tr.attr('data-weight-per-box')) || 0;
				let box = cint(tr.find('.box-input').val());
				
				if (table_name === "Items") {
					actual_box += box;
				} else {
					sample_box += box;
					sample_weight += box * weight_per_box;
				}
				
				gross_weight += box * weight_per_box;
				total_unit += qty;
			});

			page.main.find('[data-fieldname="custom_actual_box"]').val(cint(actual_box));
			page.main.find('[data-fieldname="custom_sample_box"]').val(cint(sample_box));
			page.main.find('[data-fieldname="custom_sample_weight"]').val(flt(sample_weight, 2));
			page.main.find('[data-fieldname="custom_total_box"]').val(cint(actual_box + sample_box));
			page.main.find('[data-fieldname="custom_gross_weight"]').val(flt(gross_weight, 2));
			page.main.find('[data-fieldname="custom_total_unit"]').val(flt(total_unit, 2));
		};

		// Validation and auto-calculation logic for Picked Qty
		container.find('.qty-input').on('input change', function() {
			let tr = $(this).closest('tr');
			let ordered = flt(tr.find('.ordered-qty-cell').text());
			let picked = flt($(this).val());
			
			if (picked < 0) {
				picked = 0;
				$(this).val(0);
			}
			if (picked > ordered) {
				frappe.msgprint(__("Picked Qty cannot be greater than Ordered Qty"));
				picked = ordered;
				$(this).val(ordered); // Reset to max allowed
			}
			
			let table_name = tr.closest('table').attr('data-table-name');
			if (table_name === "Items") {
				let factor = flt(tr.attr('data-conversion-factor')) || 1;
				let box = Math.ceil(picked / factor);
				tr.find('.box-input').val(box);
			}
			
			page.recalculate_totals();
		});

		// Box manual input updates totals
		container.find('.box-input').on('input change', function() {
			let val = $(this).val();
			if (val && val.indexOf('.') !== -1) {
				val = Math.round(parseFloat(val));
				$(this).val(val);
			}
			page.recalculate_totals();
		});

		// Enforce maximum 4-digit year for date inputs to avoid invalid dates like year 275760
		container.find('.mfg-input, .exp-input').on('input change', function() {
			let val = $(this).val();
			if (val) {
				let parts = val.split('-');
				if (parts.length === 3 && parts[0].length > 4) {
					parts[0] = parts[0].substring(0, 4);
					let fixed = parts.join('-');
					$(this).val(fixed);
				}
			}
		});

		// Header ACTUAL BOX or SAMPLE BOX changes update TOTAL BOX in real-time
		page.main.find('[data-fieldname="custom_actual_box"], [data-fieldname="custom_sample_box"]').on('input change', function() {
			let val = $(this).val();
			if (val && val.indexOf('.') !== -1) {
				val = Math.round(parseFloat(val));
				$(this).val(val);
			}
			let actual = cint(page.main.find('[data-fieldname="custom_actual_box"]').val());
			let sample = cint(page.main.find('[data-fieldname="custom_sample_box"]').val());
			page.main.find('[data-fieldname="custom_total_box"]').val(actual + sample);
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
					// Set previously saved value or default to current user if new
					let val = data.custom_qc_attended_by || frappe.session.user;
					if (val) {
						qc_select.val(val);
					}
				}
			}
		});
		
		// Run initial recalculation
		page.recalculate_totals();
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
			custom_qc_attended_by: page.main.find('[data-fieldname="custom_qc_attended_by"]').val(),
		};
		
		// Gather item data and validate
		let items = [];
		let validation_error = false;
		page.main.find('.sku-table tbody tr').each(function() {
			let tr = $(this);
			let table_name = tr.closest('table').attr('data-table-name');
			let qty_val = flt(tr.find('.qty-input').val());
			let ordered_qty = flt(tr.find('.ordered-qty-cell').text());
			let item_code = tr.find('[data-item-code]').attr('data-item-code');
			
			if (qty_val > ordered_qty) {
				frappe.msgprint(__("Row for item {0}: Picked Qty ({1}) cannot be greater than Ordered Qty ({2})", [item_code, qty_val, ordered_qty]));
				validation_error = true;
				return false; // Break loop
			}
			
			items.push({
				name: tr.attr('data-name'),
				item_code: item_code,
				qty: qty_val,
				custom_sample_quantity: 0,
				custom_box: tr.find('.box-input').val(),
				custom_batch_code: tr.find('.batch-input').val(),
				batch_no: "", // Leave standard batch_no empty since we are not creating real batches
				custom_mfg_date: tr.find('.mfg-input').val(),
				custom_expiry_date: tr.find('.exp-input').val(),
				custom_source_table: table_name,
				custom_remark: tr.find('.remark-input').val() || ""
			});
		});

		if (validation_error) {
			return;
		}

		if (page.pick_list_name === 'New Pick List') {
			frappe.call({
				method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.create_and_submit_pick_list',
				args: {
					so_name: page.so_name,
					header: header_data,
					items: items
				},
				freeze: true,
				callback: function(r) {
					if(!r.exc && r.message) {
						frappe.show_alert({message: "Pick List Created and Submitted Successfully", indicator: "green"});
						frappe.set_route('pick_list_list');
					}
				}
			});
		} else {
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
						frappe.show_alert({message: "Pick List Submitted Successfully", indicator: "green"});
						frappe.set_route('pick_list_list');
					}
				}
			});
		}
	};
};

frappe.pages['pick_list_entry'].on_page_show = function(wrapper) {
	if (wrapper.page_instance) {
		let current_route_name = frappe.get_route()[1];
		if (!current_route_name) {
			wrapper.page_instance.main.html('<h3>No Pick List specified. Please go to a Sales Order and click "Pick List" -> "Create".</h3>');
			return;
		}
		wrapper.page_instance.pick_list_name = current_route_name;
		wrapper.page_instance.load_data();
	}
};