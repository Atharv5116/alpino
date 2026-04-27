frappe.pages['offline-buyer-catalog'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Offline Buyer Items',
		single_column: true
	});

	$(frappe.render_template('offline_buyer_catalog', {})).appendTo(page.main);
	window.obi_page = new OfflineBuyerItemsPage(page);
};

// ── helpers ────────────────────────────────────────────────────────────────
function flt(val, precision) {
	const n = parseFloat(val) || 0;
	return precision !== undefined ? parseFloat(n.toFixed(precision)) : n;
}

// ── main class ─────────────────────────────────────────────────────────────
class OfflineBuyerItemsPage {
	constructor(page) {
		this.page = page;
		this.all_rows = [];      // master list (full, unfiltered)
		this.visible_rows = [];  // currently displayed after filters
		this._dirty = false;

		this._bind_events();
		this._load_items();
	}

	/* ── data loading ──────────────────────────────────────────────────── */

	_load_items() {
		this._set_status('Loading…');
		frappe.call({
			method: 'alpinos.offline_buyer_api.get_buyer_items',
			callback: (r) => {
				this.all_rows = r.message || [];
				this._dirty = false;
				this._update_dirty_badge();
				this._build_group_filter();
				this._apply_filters();
				this._set_status('');
			}
		});
	}

	/* ── filter & render ───────────────────────────────────────────────── */

	_build_group_filter() {
		const groups = [...new Set(this.all_rows.map(r => r.item_group).filter(Boolean))].sort();
		const sel = $('.obi-group-filter').empty().append('<option value="">All Item Groups</option>');
		groups.forEach(g => sel.append(`<option value="${g}">${g}</option>`));
	}

	_apply_filters() {
		const q   = ($('.obi-search').val() || '').toLowerCase();
		const grp = $('.obi-group-filter').val();

		this.visible_rows = this.all_rows.filter(r => {
			const matchText  = !q   || (r.item_code || '').toLowerCase().includes(q)
			                        || (r.item_name  || '').toLowerCase().includes(q);
			const matchGroup = !grp || r.item_group === grp;
			return matchText && matchGroup;
		});
		this._render_table();
	}

	_render_table() {
		const tbody = $('.obi-tbody').empty();

		this.visible_rows.forEach((row, idx) => {
			const chk  = row.selected ? 'checked' : '';
			const sel  = row.selected ? 'obi-selected' : '';
			const mrp  = row.mrp     > 0 ? row.mrp     : '';
			const mrgn = row.margin_percent > 0 ? row.margin_percent : '';
			const rate = row.selling_rate > 0 ? flt(row.selling_rate, 2) : '';

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

	/* ── events ────────────────────────────────────────────────────────── */

	_bind_events() {
		// search & group filter
		$(document).on('input',  '.obi-search',       () => this._apply_filters());
		$(document).on('change', '.obi-group-filter',  () => this._apply_filters());

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

		// header select-all checkbox
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
			// auto-select row when margin is entered
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
			const rate = flt($(e.target).val());
			const mrp  = flt($tr.find('.obi-mrp').val());
			const margin = mrp > 0 ? flt((mrp - rate) / mrp * 100, 4) : 0;
			$tr.find('.obi-margin').val(margin > 0 ? margin : '');
			// auto-select row when selling rate is entered
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

		// Bulk apply (MRP + Margin %) to selected rows
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

	/* ── helpers ───────────────────────────────────────────────────────── */

	_calc_rate(mrp, margin) {
		return mrp > 0 ? flt(mrp * (1 - margin / 100), 2) : 0;
	}

	/** Sync DOM values to model before saving */
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

	/* ── save ──────────────────────────────────────────────────────────── */

	_save() {
		this._flush_dom_to_model();

		const to_save = this.all_rows.filter(r => r.selected);
		if (!to_save.length) {
			frappe.msgprint('No items selected. Please select at least one item and try again.');
			return;
		}

		this._set_status('Saving…');
		frappe.call({
			method: 'alpinos.offline_buyer_api.save_buyer_items',
			args: { items: JSON.stringify(to_save) },
			callback: (r) => {
				this._set_status('');
				if (r.exc) return;
				const saved = r.message && r.message.saved;
				this._dirty = false;
				this._update_dirty_badge();
				frappe.show_alert({ message: `Saved ${saved} item(s) to Offline Buyer Items`, indicator: 'green' });
			}
		});
	}
}
