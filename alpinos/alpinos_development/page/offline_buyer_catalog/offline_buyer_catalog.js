frappe.pages['offline-buyer-catalog'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Offline Buyer Catalog',
		single_column: true
	});

	$(frappe.render_template('offline_buyer_catalog', {})).appendTo(page.main);
	window.obi_page = new OfflineBuyerCatalogPage(page);
};

// ── helpers ────────────────────────────────────────────────────────────────
function flt(val, precision) {
	const n = parseFloat(val) || 0;
	return precision !== undefined ? parseFloat(n.toFixed(precision)) : n;
}

// ── main class ─────────────────────────────────────────────────────────────
class OfflineBuyerCatalogPage {
	constructor(page) {
		this.page = page;

		// list-view state
		this._all_records = [];

		// detail-view state
		this._current_record = null;   // { name, title, buyer }
		this.all_rows    = [];         // full item list
		this.visible_rows = [];
		/** @type {Record<string, string[]>} parent item group name -> all group names in its subtree */
		this._parent_descendants = {};
		this._dirty = false;

		this._bind_events();
		this._load_records(null);
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   LIST VIEW
	══════════════════════════════════════════════════════════════════════════ */

	_load_records(done) {
		frappe.call({
			method: 'alpinos.offline_buyer_api.get_all_records',
			callback: (r) => {
				this._all_records = r.message || [];
				this._render_records_table(this._all_records);
				if (typeof done === 'function') {
					done();
				}
			}
		});
	}

	_render_records_table(records) {
		const tbody = $('.obi-records-tbody').empty();

		if (!records.length) {
			tbody.append('<tr><td colspan="10" class="obi-empty-state">No records found. Click "+ New" to create one.</td></tr>');
			return;
		}

		records.forEach((rec) => {
			let buyer_label = '';
			if (rec.buyer) {
				const nm = (rec.buyer_customer_name || '').trim();
				buyer_label = nm
					? `${frappe.utils.escape_html(nm)} (${frappe.utils.escape_html(rec.buyer)})`
					: frappe.utils.escape_html(rec.buyer);
			}
			const buyer_cell = rec.buyer
				? `<span style="color:#444;">${buyer_label}</span>`
				: `<span style="color:#ccc;">—</span>`;
			const site_cell = rec.site_name
				? `<span>${frappe.utils.escape_html(rec.site_name)}</span>`
				: `<span style="color:#ccc;">—</span>`;
			const ctype_cell = rec.customer_type
				? `<span>${frappe.utils.escape_html(rec.customer_type)}</span>`
				: `<span style="color:#ccc;">—</span>`;
			const pay_term = rec.payment_term
				? frappe.utils.escape_html(rec.payment_term)
				: `<span style="color:#ccc;">—</span>`;
			const pay_days =
				rec.payment_term === 'Credit' || rec.payment_term === 'Partial'
					? (rec.payment_term_days != null && rec.payment_term_days !== ''
						? frappe.utils.escape_html(String(rec.payment_term_days))
						: `<span style="color:#ccc;">—</span>`)
					: `<span style="color:#aaa;">—</span>`;
			const party = rec.party_owner
				? `<span>${frappe.utils.escape_html(rec.party_owner)}</span>`
				: `<span style="color:#ccc;">—</span>`;
			const modified = rec.modified
				? frappe.datetime.prettyDate(rec.modified)
				: '—';
			tbody.append(`
<tr data-record="${frappe.utils.escape_html(rec.name)}">
  <td class="obi-record-name">${frappe.utils.escape_html(rec.name)}</td>
  <td>${frappe.utils.escape_html(rec.title || '')}</td>
  <td>${buyer_cell}</td>
  <td>${site_cell}</td>
  <td>${ctype_cell}</td>
  <td>${pay_term}</td>
  <td style="text-align:center;">${pay_days}</td>
  <td>${party}</td>
  <td style="text-align:center;">
    <span class="obi-badge">${rec.item_count || 0} items</span>
  </td>
  <td style="color:#888;font-size:12px;">${modified}</td>
</tr>`);
		});
	}

	_filter_list(q) {
		q = (q || '').toLowerCase();
		const filtered = !q
			? this._all_records
			: this._all_records.filter(r =>
				(r.name   || '').toLowerCase().includes(q) ||
				(r.title  || '').toLowerCase().includes(q) ||
				(r.buyer  || '').toLowerCase().includes(q) ||
				(r.buyer_customer_name || '').toLowerCase().includes(q) ||
				(r.offline_buyer_master || '').toLowerCase().includes(q) ||
				(r.site_name || '').toLowerCase().includes(q) ||
				(r.customer || '').toLowerCase().includes(q) ||
				(r.customer_business_name || '').toLowerCase().includes(q) ||
				(r.customer_type || '').toLowerCase().includes(q) ||
				(r.payment_term || '').toLowerCase().includes(q) ||
				String(r.payment_term_days ?? '').toLowerCase().includes(q) ||
				(r.party_owner || '').toLowerCase().includes(q)
			);
		this._render_records_table(filtered);
	}

	_show_new_dialog() {
		const d = new frappe.ui.Dialog({
			title: 'New Offline Buyer Items Record',
			fields: [
				{ label: 'Title', fieldname: 'title', fieldtype: 'Data', reqd: 1 },
				{
					label: 'Customer',
					fieldname: 'buyer',
					fieldtype: 'Link',
					options: 'Customer',
					get_query: () => ({
						query: 'alpinos.sales_order_offline_buyer.catalog_customer_query',
					}),
				},
				{ label: 'Description', fieldname: 'description', fieldtype: 'Small Text' },
			],
			primary_action_label: 'Create',
			primary_action: (values) => {
				frappe.call({
					method: 'alpinos.offline_buyer_api.create_record',
					args: {
						title: values.title,
						buyer: values.buyer || '',
						description: values.description || ''
					},
					callback: (r) => {
						d.hide();
						if (!r.exc) {
							frappe.show_alert({ message: `Created: ${r.message}`, indicator: 'green' });
							const newName = r.message;
							this._load_records(() => {
								const full = this._all_records.find((row) => row.name === newName);
								this._open_record(
									full || {
										name: newName,
										title: values.title,
										buyer: values.buyer || '',
									}
								);
							});
						}
					}
				});
			}
		});
		d.show();
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   MODE SWITCHING
	══════════════════════════════════════════════════════════════════════════ */

	_show_list_mode() {
		$('.obi-list-view').show();
		$('.obi-detail-view').hide();
		this._current_record = null;
		this.all_rows = [];
		this.visible_rows = [];
		this._dirty = false;
		this._update_dirty_badge();
	}

	_open_record(rec) {
		if (this._dirty) {
			frappe.confirm(
				'You have unsaved changes. Discard and go back?',
				() => { this._dirty = false; this._open_record(rec); }
			);
			return;
		}
		this._current_record = rec;
		$('.obi-list-view').hide();
		$('.obi-detail-view').show();

		// update breadcrumb
		$('.obi-detail-record-name').text(`${rec.title || rec.name}  (${rec.name})`);
		const buyer_bits = [];
		if (rec.buyer) {
			const nm = (rec.buyer_customer_name || '').trim();
			buyer_bits.push(
				nm ? `Customer: ${nm} (${rec.buyer})` : `Customer: ${rec.buyer}`
			);
		}
		if (rec.offline_buyer_master) {
			buyer_bits.push(`Offline Buyer Master: ${rec.offline_buyer_master}`);
		}
		if (rec.customer_business_name) {
			buyer_bits.push(`Business: ${rec.customer_business_name}`);
		}
		if (rec.site_name) {
			buyer_bits.push(`Site: ${rec.site_name}`);
		}
		if (rec.customer_type) {
			buyer_bits.push(`Customer type: ${rec.customer_type}`);
		}
		if (rec.payment_term) {
			let pay = `Payment: ${rec.payment_term}`;
			if ((rec.payment_term === 'Credit' || rec.payment_term === 'Partial') && rec.payment_term_days != null && rec.payment_term_days !== '') {
				pay += ` (${rec.payment_term_days} days)`;
			}
			buyer_bits.push(pay);
		}
		if (rec.party_owner) {
			buyer_bits.push(`Party owner: ${rec.party_owner}`);
		}
		$('.obi-detail-buyer').html(buyer_bits.length ? buyer_bits.map((b) => frappe.utils.escape_html(b)).join(' · ') : '');

		// reset items state
		this.all_rows = [];
		this.visible_rows = [];
		this._dirty = false;
		this._update_dirty_badge();
		$('.obi-search').val('');
		$('.obi-parent-group-filter').val('');
		this._parent_descendants = {};
		$('.obi-bulk-mrp, .obi-bulk-margin').val('');

		this._load_items();
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   DETAIL VIEW – DATA
	══════════════════════════════════════════════════════════════════════════ */

	_load_items() {
		this._set_status('Loading…');
		frappe.call({
			method: 'alpinos.offline_buyer_api.get_buyer_items',
			args: { record_name: this._current_record.name },
			callback: (r) => {
				this.all_rows = r.message || [];
				this._dirty = false;
				this._update_dirty_badge();
				this._load_parent_group_filter();
				this._set_status('');
			}
		});
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   DETAIL VIEW – FILTER & RENDER
	══════════════════════════════════════════════════════════════════════════ */

	_load_parent_group_filter() {
		const groups = [...new Set(this.all_rows.map(r => r.item_group).filter(Boolean))];
		const sel = $('.obi-parent-group-filter').empty();
		sel.append($('<option>').val('').text('All parent item groups'));

		if (!groups.length) {
			this._parent_descendants = {};
			this._apply_filters();
			return;
		}

		frappe.call({
			method: 'alpinos.offline_buyer_api.get_parent_group_filter_data',
			args: { item_groups: JSON.stringify(groups) },
			callback: (r) => {
				const data = r.message || {};
				this._parent_descendants = data.descendants_map || {};
				const parents = data.parents || [];
				parents.forEach((p) => {
					sel.append($('<option>').val(p).text(p));
				});
				this._apply_filters();
			},
			error: () => {
				this._parent_descendants = {};
				this._apply_filters();
			},
		});
	}

	_apply_filters() {
		const q   = ($('.obi-search').val() || '').toLowerCase();
		const parent = $('.obi-parent-group-filter').val();
		const inSubtree = parent ? (this._parent_descendants[parent] || []) : null;

		this.visible_rows = this.all_rows.filter(r => {
			const matchText = !q || (r.item_code || '').toLowerCase().includes(q)
				|| (r.item_name || '').toLowerCase().includes(q);
			const ig = r.item_group || '';
			const matchParent = !parent || (inSubtree && inSubtree.includes(ig));
			return matchText && matchParent;
		});
		this._render_table();
	}

	_render_table() {
		const tbody = $('.obi-tbody').empty();

		this.visible_rows.forEach((row, idx) => {
			const chk  = row.selected ? 'checked' : '';
			const sel  = row.selected ? 'obi-selected' : '';
			const mrp  = row.mrp          > 0 ? row.mrp          : '';
			const mrgn = row.margin_percent > 0 ? row.margin_percent : '';
			const rate = row.selling_rate  > 0 ? flt(row.selling_rate, 2) : '';

			tbody.append(`
<tr data-code="${row.item_code}" class="${sel}">
  <td class="col-chk"><input type="checkbox" class="obi-row-chk" ${chk} /></td>
  <td class="col-no text-muted">${idx + 1}</td>
  <td class="col-code">${row.item_code}</td>
  <td class="col-name">${row.item_name}</td>
  <td class="col-group">${row.item_group || ''}</td>
  <td class="col-mrp">
    <input type="number" class="form-control obi-mrp"
           value="${mrp}" min="0" step="0.01" placeholder="0.00" />
  </td>
  <td class="col-margin">
    <input type="number" class="form-control obi-margin"
           value="${mrgn}" min="0" max="100" step="0.01" placeholder="0.00" />
  </td>
  <td class="col-rate">
    <input type="number" class="form-control obi-rate"
           value="${rate}" min="0" step="0.01" placeholder="0.00" />
  </td>
</tr>`);
		});

		this._update_counts();
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   EVENT BINDING
	══════════════════════════════════════════════════════════════════════════ */

	_bind_events() {
		// ── LIST VIEW ──────────────────────────────────────────────────────────

		// search list
		$(document).on('input', '.obi-list-search', (e) => {
			this._filter_list($(e.target).val());
		});

		// click on a record row
		$(document).on('click', '.obi-records-tbody tr', (e) => {
			const name = $(e.currentTarget).data('record');
			if (!name) return;
			const rec = this._all_records.find(r => r.name === name);
			if (rec) this._open_record(rec);
		});

		// new record
		$(document).on('click', '.obi-btn-new', () => this._show_new_dialog());

		// ── DETAIL VIEW ────────────────────────────────────────────────────────

		// back to list
		$(document).on('click', '.obi-back-btn', () => {
			if (this._dirty) {
				frappe.confirm(
					'You have unsaved changes. Discard and go back?',
					() => { this._dirty = false; this._show_list_mode(); }
				);
			} else {
				this._show_list_mode();
				this._load_records(); // refresh counts
			}
		});

		// search & group filter
		$(document).on('input',  '.obi-search',      () => this._apply_filters());
		$(document).on('change', '.obi-parent-group-filter', () => this._apply_filters());

		// row checkbox
		$(document).on('change', '.obi-row-chk', (e) => {
			const $tr    = $(e.target).closest('tr');
			const code   = $tr.data('code');
			const checked = e.target.checked;
			$tr.toggleClass('obi-selected', checked);
			this._patch_model(code, { selected: checked });
			this._mark_dirty();
			this._update_counts();
		});

		// header select-all
		$(document).on('change', '.obi-chk-all', (e) => {
			const checked = e.target.checked;
			$('.obi-tbody .obi-row-chk').prop('checked', checked).each((_, el) => {
				$(el).closest('tr').toggleClass('obi-selected', checked);
				this._patch_model($(el).closest('tr').data('code'), { selected: checked });
			});
			this._mark_dirty();
			this._update_counts();
		});

		// MRP → recalc selling rate
		$(document).on('change', '.obi-mrp', (e) => {
			const $tr  = $(e.target).closest('tr');
			const code = $tr.data('code');
			const mrp    = flt($(e.target).val());
			const margin = flt($tr.find('.obi-margin').val());
			const rate   = this._calc_rate(mrp, margin);
			$tr.find('.obi-rate').val(rate > 0 ? rate : '');
			this._patch_model(code, { mrp, selling_rate: rate });
			this._mark_dirty();
		});

		// Margin % → recalc selling rate
		$(document).on('change', '.obi-margin', (e) => {
			const $tr  = $(e.target).closest('tr');
			const code = $tr.data('code');
			const margin = flt($(e.target).val());
			const mrp    = flt($tr.find('.obi-mrp').val());
			const rate   = this._calc_rate(mrp, margin);
			$tr.find('.obi-rate').val(rate > 0 ? rate : '');
			if (margin > 0 && !$tr.find('.obi-row-chk').prop('checked')) {
				$tr.find('.obi-row-chk').prop('checked', true).trigger('change');
			}
			this._patch_model(code, { margin_percent: margin, selling_rate: rate });
			this._mark_dirty();
		});

		// Selling Rate → back-calc margin
		$(document).on('change', '.obi-rate', (e) => {
			const $tr  = $(e.target).closest('tr');
			const code = $tr.data('code');
			const rate   = flt($(e.target).val());
			const mrp    = flt($tr.find('.obi-mrp').val());
			const margin = mrp > 0 ? flt((mrp - rate) / mrp * 100, 4) : 0;
			$tr.find('.obi-margin').val(margin > 0 ? margin : '');
			if (rate > 0 && !$tr.find('.obi-row-chk').prop('checked')) {
				$tr.find('.obi-row-chk').prop('checked', true).trigger('change');
			}
			this._patch_model(code, { margin_percent: margin, selling_rate: rate });
			this._mark_dirty();
		});

		// Select All / Deselect All buttons
		$(document).on('click', '.obi-btn-select-all', () => {
			$('.obi-tbody .obi-row-chk').prop('checked', true).each((_, el) => {
				const $tr = $(el).closest('tr');
				$tr.addClass('obi-selected');
				this._patch_model($tr.data('code'), { selected: true });
			});
			$('.obi-chk-all').prop('checked', true);
			this._mark_dirty();
			this._update_counts();
		});
		$(document).on('click', '.obi-btn-deselect-all', () => {
			$('.obi-tbody .obi-row-chk').prop('checked', false).each((_, el) => {
				const $tr = $(el).closest('tr');
				$tr.removeClass('obi-selected');
				this._patch_model($tr.data('code'), { selected: false });
			});
			$('.obi-chk-all').prop('checked', false);
			this._mark_dirty();
			this._update_counts();
		});

		// Bulk apply
		$(document).on('click', '.obi-btn-apply-bulk', () => {
			const bulk_mrp    = $('.obi-bulk-mrp').val();
			const bulk_margin = $('.obi-bulk-margin').val();
			if (bulk_mrp === '' && bulk_margin === '') {
				frappe.show_alert({ message: 'Enter MRP or Margin % to apply', indicator: 'orange' });
				return;
			}
			let count = 0;
			$('.obi-tbody tr.obi-selected').each((_, tr) => {
				const $tr  = $(tr);
				const code = $tr.data('code');
				let mrp    = flt($tr.find('.obi-mrp').val());
				let margin = flt($tr.find('.obi-margin').val());

				if (bulk_mrp    !== '') { mrp    = flt(bulk_mrp);    $tr.find('.obi-mrp').val(mrp); }
				if (bulk_margin !== '') { margin = flt(bulk_margin);  $tr.find('.obi-margin').val(margin); }

				const rate = this._calc_rate(mrp, margin);
				$tr.find('.obi-rate').val(rate > 0 ? rate : '');
				this._patch_model(code, { mrp, margin_percent: margin, selling_rate: rate });
				count++;
			});
			if (!count) {
				frappe.show_alert({ message: 'No rows selected', indicator: 'orange' });
				return;
			}
			this._mark_dirty();
			frappe.show_alert({ message: `Applied to ${count} rows`, indicator: 'green' });
		});

		// Save
		$(document).on('click', '.obi-btn-save', () => this._save());
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   HELPERS
	══════════════════════════════════════════════════════════════════════════ */

	_calc_rate(mrp, margin) {
		return mrp > 0 ? flt(mrp * (1 - margin / 100), 2) : 0;
	}

	_flush_dom_to_model() {
		$('.obi-tbody tr').each((_, tr) => {
			const $tr  = $(tr);
			const code = $tr.data('code');
			if (!code) return;
			this._patch_model(code, {
				selected:       $tr.find('.obi-row-chk').prop('checked'),
				mrp:            flt($tr.find('.obi-mrp').val()),
				margin_percent: flt($tr.find('.obi-margin').val()),
				selling_rate:   flt($tr.find('.obi-rate').val()),
			});
		});
	}

	_patch_model(item_code, patch) {
		const row = this.all_rows.find(r => r.item_code === item_code);
		if (row) Object.assign(row, patch);
	}

	_update_counts() {
		$('.obi-total-count').text(`${this.visible_rows.length} items`);
		$('.obi-selected-count').text($('.obi-tbody .obi-row-chk:checked').length);
	}

	_set_status(msg) { $('.obi-status').text(msg); }

	_mark_dirty() {
		this._dirty = true;
		this._update_dirty_badge();
	}

	_update_dirty_badge() {
		$('.obi-dirty-badge').toggle(this._dirty);
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   SAVE
	══════════════════════════════════════════════════════════════════════════ */

	_save() {
		if (!this._current_record) return;

		this._flush_dom_to_model();

		const to_save = this.all_rows.filter(r => r.selected);
		if (!to_save.length) {
			frappe.msgprint('No items selected. Please select at least one item and try again.');
			return;
		}

		this._set_status('Saving…');
		frappe.call({
			method: 'alpinos.offline_buyer_api.save_buyer_items',
			args: {
				record_name: this._current_record.name,
				items: JSON.stringify(to_save)
			},
			callback: (r) => {
				this._set_status('');
				if (r.exc) return;
				const saved = r.message && r.message.saved;
				this._dirty = false;
				this._update_dirty_badge();
				// update item count in memory for when user goes back
				const rec = this._all_records.find(r2 => r2.name === this._current_record.name);
				if (rec) rec.item_count = saved;
				frappe.show_alert({
					message: `Saved ${saved} item(s) to "${this._current_record.title}"`,
					indicator: 'green'
				});
			}
		});
	}
}
