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

			page.main.find('#btn-save-draft').on('click', function() {
				page.save_pick_list_as_draft();
			});

			page.main.find('#btn-save-draft-update').on('click', function() {
				page.save_pick_list_keep_draft();
			});

			page.main.find('#btn-generate-sticker').on('click', function() {
				if (!page.pick_list_name || page.pick_list_name === 'New Pick List') {
					frappe.msgprint(__('Save the Pick List first, then generate stickers.'));
					return;
				}
				let url = '/api/method/alpinos.pick_list_api.generate_pick_list_stickers'
					+ '?pick_list=' + encodeURIComponent(page.pick_list_name);
				window.open(url, '_blank');
			});

			page.main.find('#btn-create-delivery-note').on('click', function() {
				// If a DN already exists for this pick list, just open it.
				if (page.existing_delivery_note) {
					frappe.set_route('delivery_note_entry', page.existing_delivery_note);
					return;
				}
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
							frappe.set_route('delivery_note_entry', r.message);
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
			// route_options is wiped on reload — fall back to a sessionStorage cache
			// keyed by the page route so a refresh keeps the SO context.
			let so_name = (frappe.route_options && frappe.route_options.so_name) || null;
			const cache_key = 'alpinos_pick_list_entry_so_name';
			if (so_name) {
				try { sessionStorage.setItem(cache_key, so_name); } catch (e) {}
			} else {
				try { so_name = sessionStorage.getItem(cache_key); } catch (e) {}
			}
			if (!so_name) {
				page.main.html('<h3>Missing Sales Order context for New Pick List.</h3><p>Open a Sales Order and click the "Create Pick List" button to start a new Pick List Entry.</p>');
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
		page.existing_delivery_note = data.existing_delivery_note || null;
		const $dnBtn = page.main.find('#btn-create-delivery-note');
		const $draftBtn = page.main.find('#btn-save-draft');
		const $saveDraftUpdate = page.main.find('#btn-save-draft-update');
		const $stickerBtn = page.main.find('#btn-generate-sticker');
		// Sticker generation needs a persisted PL — show on saved drafts + submitted, hide on new.
		if (page.pick_list_name && page.pick_list_name !== 'New Pick List') {
			$stickerBtn.show();
		} else {
			$stickerBtn.hide();
		}
		if (data.docstatus === 1) {
			page.clear_primary_action();
			$draftBtn.hide();
			$saveDraftUpdate.hide();
			if (page.existing_delivery_note) {
				$dnBtn.text('View Delivery Note').show();
			} else {
				$dnBtn.text('Create Delivery Note').show();
			}
		} else {
			$dnBtn.hide();
			// New PL → "Save as Draft" (creates the doc).
			// Saved draft → "Save" (updates without submitting).
			if (page.pick_list_name === 'New Pick List') {
				$draftBtn.show();
				$saveDraftUpdate.hide();
			} else {
				$draftBtn.hide();
				$saveDraftUpdate.show();
			}
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
		page.main.find('[data-fieldname="custom_assigned_to"]').val(data.custom_assigned_to || '');
		let dispatch_date_val = data.custom_dispatch_date || '';
		if (dispatch_date_val) {
			page.main.find('[data-fieldname="custom_dispatch_date"]').val(dispatch_date_val);
		} else {
			frappe.call({
				method: 'alpinos.dispatch_date_utils.get_default_dispatch_date',
				callback: function(r) {
					if (r.message) {
						page.main.find('[data-fieldname="custom_dispatch_date"]').val(r.message.date);
					}
				}
			});
		}

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
				<div class="sku-table-wrapper">
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
							<th>GATE</th>
							<th>REMARK</th>
							<th>ACTIONS</th>
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
			let box_readonly = title === "Items" ? '' : 'readonly tabindex="-1"';
			
			let row_html = `
				<tr data-name="${row.name}" data-conversion-factor="${row.custom_conversion_factor || 1}" data-weight-per-box="${row.custom_weight_per_box || 0}" data-shelf-life="${row.shelf_life_in_days || 0}">
					<td>${idx + 1}</td>
					<td data-item-code="${row.item_code}">${row.item_code}</td>
					<td>${row.custom_sku_no || '-'}</td>
					<td class="ordered-qty-cell">${row.custom_ordered_qty !== undefined && row.custom_ordered_qty !== null ? row.custom_ordered_qty : (row.qty || 0)}</td>
					<td><input type="number" class="form-control input-sm qty-input" value="${row.qty !== undefined && row.qty !== null ? row.qty : ''}" min="0" ${input_disabled}/></td>
					<td><input type="number" class="form-control input-sm box-input" value="${box_val}" step="1" min="0" ${input_disabled} ${box_readonly}/></td>
					<td>
						<input type="text" class="form-control input-sm batch-input" list="batch-list" value="${row.custom_batch_code || row.batch_no || ''}" ${batch_readonly}>
					</td>
					<td><input type="date" class="form-control input-sm mfg-input" value="${row.custom_mfg_date || ''}" max="9999-12-31" ${batch_readonly}></td>
					<td><input type="date" class="form-control input-sm exp-input" value="${row.custom_expiry_date || ''}" max="9999-12-31" ${batch_readonly}></td>
					<td><input type="text" class="form-control input-sm gate-input" value="${row.custom_gate || ''}" ${batch_readonly} maxlength="20" placeholder="e.g. A1"></td>
					<td><input type="text" class="form-control input-sm remark-input" value="${row.custom_remark || ''}" ${batch_readonly}></td>
					<td class="row-actions-cell">
						${data.docstatus !== 1 ? `
							<button type="button" class="alpinos-row-icon-btn row-split-btn" aria-label="Split row" title="Split this row across multiple batches">
								<i class="fa fa-code-fork"></i>
							</button>
							<button type="button" class="alpinos-row-icon-btn alpinos-row-icon-danger row-remove-btn" aria-label="Remove row" title="Remove this row (audit reason required)">
								<i class="fa fa-trash"></i>
							</button>
						` : ''}
					</td>
				</tr>
			`;
			html += row_html;
		});	
			html += `</tbody></table></div>`;
			container.append(html);
		};
		
		create_table("Items", groups["Items"]);
		create_table("Marketing Freebies", groups["Marketing Freebies"]);
		create_table("Scheme Table", groups["Scheme Table"]);
		create_table("Additional Units", groups["Additional Units"]);

		// Removed Items audit table — server-persisted rows for saved PLs,
		// plus any pending client-side removals on a new (unsaved) PL.
		page.render_removed_items = function() {
			let removed = (data.custom_removed_items || []).slice();
			(page._pending_removals || []).forEach(r => removed.push({
				item_code: r.item_code,
				item_name: r.item_name,
				removed_qty: r.removed_qty,
				removed_box: r.removed_box,
				batch_no: r.batch_no,
				reason: r.reason,
				removed_by: frappe.session.user,
				removed_on: 'Pending save',
				is_pending: true,
			}));
			let $existing = container.find('#removed-items-section');
			if (!removed.length) {
				$existing.remove();
				return;
			}
			let rows_html = removed.map((r, idx) => `
				<tr ${r.is_pending ? 'style="background:#fffbeb;"' : ''}>
					<td>${idx + 1}</td>
					<td>${frappe.utils.escape_html(r.item_code || '')}</td>
					<td>${frappe.utils.escape_html(r.item_name || '')}</td>
					<td>${flt(r.removed_qty || 0)}</td>
					<td>${cint(r.removed_box || 0)}</td>
					<td>${frappe.utils.escape_html(r.batch_no || '')}</td>
					<td style="text-align:left;">${frappe.utils.escape_html(r.reason || '')}</td>
					<td>${frappe.utils.escape_html(r.removed_by || '')}</td>
					<td>${frappe.utils.escape_html(String(r.removed_on || ''))}</td>
				</tr>
			`).join('');
			let html = `
				<div id="removed-items-section">
					<div class="table-section-title">Removed Items</div>
					<div class="sku-table-wrapper">
					<table class="sku-table">
						<thead>
							<tr>
								<th>SR.</th>
								<th>SKU</th>
								<th>ITEM NAME</th>
								<th>QTY</th>
								<th>BOX</th>
								<th>BATCH</th>
								<th>REASON</th>
								<th>REMOVED BY</th>
								<th>REMOVED ON</th>
							</tr>
						</thead>
						<tbody>${rows_html}</tbody>
					</table>
					</div>
				</div>
			`;
			if ($existing.length) {
				$existing.replaceWith(html);
			} else {
				container.append(html);
			}
		};
		page.render_removed_items();

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
					gross_weight += box * weight_per_box;
				} else {
					sample_box += box;
					sample_weight += box * weight_per_box;
				}

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

		// EXP must be >= MFG; clear exp if user enters an earlier date than mfg.
		container.find('.exp-input').on('change', function() {
			let tr = $(this).closest('tr');
			let mfg = tr.find('.mfg-input').val();
			let exp = $(this).val();
			if (mfg && exp && exp < mfg) {
				frappe.msgprint(__('Expiry Date cannot be earlier than Manufacturing Date.'));
				$(this).val('');
			}
		});
		container.find('.mfg-input').on('change', function() {
			let tr = $(this).closest('tr');
			let mfg = $(this).val();
			let exp_input = tr.find('.exp-input');
			let exp = exp_input.val();
			if (mfg && exp && exp < mfg) {
				frappe.msgprint(__('Expiry Date cannot be earlier than Manufacturing Date. Clearing expiry; re-enter it.'));
				exp_input.val('');
			}
		});

		// MFG -> Expiry auto-fill from Item.shelf_life_in_days when expiry is blank.
		container.find('.mfg-input').on('change', function() {
			let tr = $(this).closest('tr');
			let mfg = $(this).val();
			let exp_input = tr.find('.exp-input');
			let shelf = cint(tr.attr('data-shelf-life')) || 0;
			if (!mfg || !shelf || exp_input.val()) return;
			let d = frappe.datetime.str_to_obj(mfg);
			if (!d) return;
			d.setDate(d.getDate() + shelf);
			exp_input.val(frappe.datetime.obj_to_str(d).split(' ')[0]);
		});

		// Header ACTUAL BOX or SAMPLE BOX changes update TOTAL BOX in real-time
		page.main.find('[data-fieldname="custom_actual_box"], [data-fieldname="custom_sample_box"]').off('input change').on('input change', function() {
			let val = $(this).val();
			if (val && String(val).indexOf('.') !== -1) {
				val = Math.round(parseFloat(val));
				$(this).val(val);
			}
			let actual = cint(page.main.find('[data-fieldname="custom_actual_box"]').val() || 0);
			let sample = cint(page.main.find('[data-fieldname="custom_sample_box"]').val() || 0);
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

							// Customer-type expiry warning (Task 7) — soft alert only.
							let sales_order = page.main.find('[data-fieldname="custom_sales_order_id"]').val()
								|| (data && data.custom_sales_order_id);
							let dispatch_date = page.main.find('[data-fieldname="custom_dispatch_date"]').val()
								|| (data && data.custom_dispatch_date);
							if (res.message.expiry_date && sales_order) {
								frappe.call({
									method: 'alpinos.expiry_validation.check_row_expiry_warning',
									args: {
										expiry_date: res.message.expiry_date,
										sales_order: sales_order,
										dispatch_date: dispatch_date || null,
									},
								}).then((r2) => {
									let m = r2.message || {};
									if (!m.ok && m.message) {
										let label = tr.find('[data-item-code]').text() || item_code;
										frappe.show_alert({ message: `${label}: ${m.message}`, indicator: 'orange' }, 7);
									}
								});
							}
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

		// Fetch users for QC + Assigned To dropdowns (same enabled System Users list).
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
					let qc_val = data.custom_qc_attended_by || data.custom_assigned_to || frappe.session.user;
					if (qc_val) {
						qc_select.val(qc_val);
					}

					let assigned_select = page.main.find('[data-fieldname="custom_assigned_to"]');
					assigned_select.empty();
					assigned_select.append(`<option value=""></option>`);
					res.message.forEach(u => {
						assigned_select.append(`<option value="${u}">${u}</option>`);
					});
					if (data.custom_assigned_to) {
						assigned_select.val(data.custom_assigned_to);
					}

					// When Assigned To changes:
					//   - sync QC Attended By if QC is blank (Task 5 auto-fetch).
					//   - persist immediately via update_pick_list_assignment so the
					//     change sticks at any docstatus (custom field is allow_on_submit=1).
					assigned_select.off('change.alpinosAssign').on('change.alpinosAssign', function() {
						let assigned = $(this).val();
						let qc_current = qc_select.val();
						if (assigned && !qc_current) {
							qc_select.val(assigned);
						}
						if (page.pick_list_name && page.pick_list_name !== 'New Pick List') {
							frappe.call({
								method: 'alpinos.pick_list_api.update_pick_list_assignment',
								args: { pick_list: page.pick_list_name, assigned_to: assigned || '' },
								callback: function() {
									frappe.show_alert({ message: __('Assigned To updated'), indicator: 'green' }, 3);
								}
							});
						}
					});
				}
			}
		});
		
		// Per-row Remove (Task 9) and Split (Task 10) action buttons.
		// On an unsaved "New Pick List" we mutate the in-memory grid directly
		// — both extra rows and removed rows ride along to the server on the
		// final Submit / Save as Draft. On an existing draft we hit the dedicated
		// server endpoints and reload the page.
		const is_unsaved_new_pl = () => !data.name || data.name === 'New Pick List' || page.pick_list_name === 'New Pick List';

		container.off('click.alpinosRowActions').on('click.alpinosRowActions', '.row-remove-btn', function() {
			let tr = $(this).closest('tr');
			let row_name = tr.attr('data-name');
			let item_code = tr.find('[data-item-code]').attr('data-item-code');
			let item_name_cell = tr.find('td').eq(2).text();
			frappe.prompt(
				[{ fieldname: 'reason', fieldtype: 'Small Text', label: 'Reason for Removal', reqd: 1 }],
				(values) => {
					if (is_unsaved_new_pl()) {
						// Client-side: record audit + drop row from DOM.
						page._pending_removals = page._pending_removals || [];
						page._pending_removals.push({
							row_name: row_name,
							item_code: item_code,
							item_name: item_name_cell,
							removed_qty: flt(tr.find('.qty-input').val()),
							removed_box: cint(tr.find('.box-input').val()),
							batch_no: tr.find('.batch-input').val() || null,
							reason: values.reason,
						});
						tr.remove();
						page.recalculate_totals();
						if (page.render_removed_items) page.render_removed_items();
						frappe.show_alert({ message: `Row removed (${item_code}).`, indicator: 'orange' }, 4);
						return;
					}
					frappe.call({
						method: 'alpinos.pick_list_api.remove_pick_list_row_with_reason',
						args: { pick_list: data.name, row_name: row_name, reason: values.reason },
						freeze: true,
						freeze_message: 'Removing row...',
					}).then((r) => {
						if (r.message) {
							frappe.show_alert({ message: `Row removed (${item_code}).`, indicator: 'orange' }, 4);
							page.load_data();
						}
					});
				},
				`Remove Row ${item_code}`,
				'Confirm'
			);
		});

		container.on('click.alpinosRowActions', '.row-split-btn', function() {
			let tr = $(this).closest('tr');
			let row_name = tr.attr('data-name');
			let item_code = tr.find('[data-item-code]').attr('data-item-code');
			let current_box = cint(tr.find('.box-input').val());
			if (current_box <= 1) {
				frappe.msgprint(__('Row must have at least 2 boxes to split.'));
				return;
			}
			frappe.prompt(
				[{ fieldname: 'split_box', fieldtype: 'Int', label: `Boxes to split (current: ${current_box})`, reqd: 1 }],
				(values) => {
					let split_box = cint(values.split_box);
					if (split_box <= 0 || split_box >= current_box) {
						frappe.msgprint(__(`Split box must be between 1 and ${current_box - 1}.`));
						return;
					}
					if (is_unsaved_new_pl()) {
						// Client-side split: clone the source row, decrement original,
						// new row gets a client-generated name so save flow knows it's extra.
						let factor = flt(tr.attr('data-conversion-factor')) || 1;
						let new_qty = flt(split_box * factor, 2);
						let remaining_box = current_box - split_box;
						let remaining_qty = flt(remaining_box * factor, 2);
						let weight_per_box = tr.attr('data-weight-per-box') || 0;
						let shelf_life = tr.attr('data-shelf-life') || 0;
						let source_idx = tr.index() + 2; // SR. column is 1-based; new clone gets +1
						let clone_name = 'client-split-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
						let item_name_text = tr.find('td').eq(2).text();
						let sku_no_text = tr.find('td').eq(2).text();
						let ordered_qty_text = tr.find('.ordered-qty-cell').text();
						let table_name = tr.closest('table').attr('data-table-name');
						let new_row_html = `
							<tr data-name="${clone_name}" data-conversion-factor="${factor}" data-weight-per-box="${weight_per_box}" data-shelf-life="${shelf_life}" data-client-extra="1" data-source-row="${row_name}">
								<td>${source_idx}</td>
								<td data-item-code="${item_code}">${item_code}</td>
								<td>${sku_no_text}</td>
								<td class="ordered-qty-cell">${ordered_qty_text}</td>
								<td><input type="number" class="form-control input-sm qty-input" value="${new_qty}" min="0"/></td>
								<td><input type="number" class="form-control input-sm box-input" value="${split_box}" step="1" min="0" ${table_name === 'Items' ? '' : 'readonly tabindex="-1"'}/></td>
								<td><input type="text" class="form-control input-sm batch-input" list="batch-list" value=""></td>
								<td><input type="date" class="form-control input-sm mfg-input" value="" max="9999-12-31"></td>
								<td><input type="date" class="form-control input-sm exp-input" value="" max="9999-12-31"></td>
								<td><input type="text" class="form-control input-sm gate-input" value="${tr.find('.gate-input').val() || ''}" maxlength="20" placeholder="e.g. A1"></td>
								<td><input type="text" class="form-control input-sm remark-input" value="[split]"></td>
								<td class="row-actions-cell">
									<button type="button" class="alpinos-row-icon-btn row-split-btn" aria-label="Split row" title="Split this row across multiple batches"><i class="fa fa-code-fork"></i></button>
									<button type="button" class="alpinos-row-icon-btn alpinos-row-icon-danger row-remove-btn" aria-label="Remove row" title="Remove this row (audit reason required)"><i class="fa fa-trash"></i></button>
								</td>
							</tr>
						`;
						tr.after(new_row_html);
						// Decrement source row.
						tr.find('.box-input').val(remaining_box);
						tr.find('.qty-input').val(remaining_qty);
						page.recalculate_totals();
						frappe.show_alert({ message: `Row split (${item_code}): ${split_box} boxes moved.`, indicator: 'green' }, 4);
						return;
					}
					frappe.call({
						method: 'alpinos.pick_list_api.split_pick_list_row',
						args: { pick_list: data.name, row_name: row_name, split_box: split_box },
						freeze: true,
						freeze_message: 'Splitting row...',
					}).then((r) => {
						if (r.message) {
							frappe.show_alert({ message: `Row split (${item_code}): ${split_box} boxes moved.`, indicator: 'green' }, 4);
							page.load_data();
						}
					});
				},
				`Split Row ${item_code}`,
				'Split'
			);
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
			custom_assigned_to: page.main.find('[data-fieldname="custom_assigned_to"]').val() || null,
			custom_dispatch_date: page.main.find('[data-fieldname="custom_dispatch_date"]').val() || null,
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
				custom_remark: tr.find('.remark-input').val() || "",
				custom_gate: tr.find('.gate-input').val() || "",
				is_client_extra: tr.attr('data-client-extra') === '1' ? 1 : 0,
				source_row: tr.attr('data-source-row') || null
			});
		});

		if (validation_error) {
			return;
		}

		let removed_rows = page._pending_removals || [];

		if (page.pick_list_name === 'New Pick List') {
			frappe.call({
				method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.create_and_submit_pick_list',
				args: {
					so_name: page.so_name,
					header: header_data,
					items: items,
					removed_rows: removed_rows
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

	// Save edits on an existing draft without submitting it. Reuses the same
	// header/items collection as Submit, but calls a server method that
	// updates fields in place and skips doc.submit().
	page.save_pick_list_keep_draft = function() {
		if (!page.pick_list_name || page.pick_list_name === 'New Pick List') {
			frappe.msgprint(__('No draft to save yet — use "Save as Draft" instead.'));
			return;
		}
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
			custom_assigned_to: page.main.find('[data-fieldname="custom_assigned_to"]').val() || null,
			custom_dispatch_date: page.main.find('[data-fieldname="custom_dispatch_date"]').val() || null,
		};
		let items = [];
		page.main.find('.sku-table tbody tr').each(function() {
			let tr = $(this);
			items.push({
				name: tr.attr('data-name'),
				item_code: tr.find('[data-item-code]').attr('data-item-code'),
				qty: flt(tr.find('.qty-input').val()),
				custom_box: tr.find('.box-input').val(),
				custom_batch_code: tr.find('.batch-input').val(),
				batch_no: "",
				custom_mfg_date: tr.find('.mfg-input').val(),
				custom_expiry_date: tr.find('.exp-input').val(),
				custom_remark: tr.find('.remark-input').val() || "",
				custom_gate: tr.find('.gate-input').val() || "",
			});
		});
		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.save_pick_list_keep_draft',
			args: { name: page.pick_list_name, header: header_data, items: items },
			freeze: true,
			freeze_message: __('Saving...'),
			callback: function(r) {
				if (!r.exc) {
					frappe.show_alert({ message: __('Saved'), indicator: 'green' }, 3);
					page.load_data();
				}
			}
		});
	};

	// Persist a new Pick List as draft (docstatus=0) so the user can split/remove
	// rows before final submit. After save we navigate to the new draft URL so
	// per-row action buttons become available.
	page.save_pick_list_as_draft = function() {
		if (page.pick_list_name !== 'New Pick List') {
			frappe.show_alert({ message: __('Already saved.'), indicator: 'orange' });
			return;
		}
		if (!page.so_name) {
			frappe.msgprint(__('Sales Order context is missing — open this page from a Sales Order.'));
			return;
		}
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
			custom_assigned_to: page.main.find('[data-fieldname="custom_assigned_to"]').val() || null,
			custom_dispatch_date: page.main.find('[data-fieldname="custom_dispatch_date"]').val() || null,
		};
		let items = [];
		page.main.find('.sku-table tbody tr').each(function() {
			let tr = $(this);
			let table_name = tr.closest('table').attr('data-table-name');
			items.push({
				name: tr.attr('data-name'),
				item_code: tr.find('[data-item-code]').attr('data-item-code'),
				qty: flt(tr.find('.qty-input').val()),
				custom_sample_quantity: 0,
				custom_box: tr.find('.box-input').val(),
				custom_batch_code: tr.find('.batch-input').val(),
				batch_no: "",
				custom_mfg_date: tr.find('.mfg-input').val(),
				custom_expiry_date: tr.find('.exp-input').val(),
				custom_source_table: table_name,
				custom_remark: tr.find('.remark-input').val() || "",
				custom_gate: tr.find('.gate-input').val() || "",
				is_client_extra: tr.attr('data-client-extra') === '1' ? 1 : 0,
				source_row: tr.attr('data-source-row') || null
			});
		});
		let removed_rows = page._pending_removals || [];
		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.create_pick_list_as_draft',
			args: { so_name: page.so_name, header: header_data, items: items, removed_rows: removed_rows },
			freeze: true,
			freeze_message: __('Saving as draft...'),
			callback: function(r) {
				if (!r.exc && r.message) {
					frappe.show_alert({ message: __('Saved as draft.'), indicator: 'green' });
					frappe.set_route('pick_list_entry', r.message);
				}
			}
		});
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