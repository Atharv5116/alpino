// Supplier Catalog: supplier-wise list of the items each supplier supplies.
// A Purchase Order for a supplier offers only the items ticked here (none until it has a catalog).
// Server: alpinos.purchase.supplier_catalog.

frappe.pages['supplier_catalog'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Supplier Catalog'), single_column: true });
	$(frappe.render_template('supplier_catalog', {})).appendTo(page.main);
	wrapper.supplier_catalog = new SupplierCatalogPage(page, $(wrapper));
};

frappe.pages['supplier_catalog'].on_page_show = function (wrapper) {
	const sc = wrapper.supplier_catalog;
	if (!sc) return;
	const opts = frappe.route_options || {};
	const supplier = opts.supplier || frappe.utils.get_query_params().supplier;
	frappe.route_options = null;
	if (supplier) sc.open(supplier);
};

class SupplierCatalogPage {
	constructor(page, $wrapper) {
		this.page = page;
		this.$w = $wrapper.find('.spc');
		this.suppliers = [];
		this.rows = [];
		this.current = null;
		this.can_edit = 0;
		this.dirty = false;
		this.bind();
		this.load_suppliers();
	}

	// ---------------------------------------------------------------- suppliers

	load_suppliers() {
		frappe.call({
			method: 'alpinos.purchase.supplier_catalog.get_suppliers',
			callback: (r) => {
				const d = r.message || {};
				this.suppliers = d.suppliers || [];
				this.can_edit = cint(d.can_edit);
				this.render_suppliers();
			},
		});
	}

	render_suppliers() {
		const q = (this.$w.find('.spc-sup-search').val() || '').toLowerCase().trim();
		const f = this.$w.find('.spc-sup-filter').val();
		const rows = this.suppliers.filter((s) => {
			if (f === 'set' && !s.item_count) return false;
			if (f === 'none' && s.item_count) return false;
			return !q || `${s.name} ${s.supplier_name || ''} ${s.supplier_group || ''}`.toLowerCase().includes(q);
		});
		const esc = frappe.utils.escape_html;
		const $b = this.$w.find('.spc-sup-body').empty();
		if (!rows.length) {
			$b.append(`<tr><td colspan="4" class="spc-empty">${__('No suppliers match.')}</td></tr>`);
		}
		rows.forEach((s) => {
			const count = s.item_count
				? `<span class="spc-pill ok">${s.item_count}</span>`
				: `<span class="spc-pill none">${__('No catalog yet')}</span>`;
			const name = s.supplier_name && s.supplier_name.trim().toLowerCase() !== s.name.trim().toLowerCase()
				? `<div class="spc-code">${esc(s.supplier_name)}</div><div class="spc-muted">${esc(s.name)}</div>`
				: `<div class="spc-code">${esc(s.name)}</div>`;
			$(`<tr data-name="${esc(s.name)}">
				<td>${name}</td>
				<td class="spc-hide-sm">${esc(s.supplier_group || '')}</td>
				<td class="num">${count}</td>
				<td class="spc-hide-sm spc-muted">${s.modified ? esc(frappe.datetime.str_to_user(s.modified)) : ''}</td>
			</tr>`).appendTo($b);
		});
		const set = this.suppliers.filter((s) => s.item_count).length;
		this.$w.find('.spc-sup-count').text(__('{0} of {1} suppliers have a catalog', [set, this.suppliers.length]));
	}

	// ------------------------------------------------------------------ catalog

	open(supplier) {
		frappe.call({
			method: 'alpinos.purchase.supplier_catalog.get_catalog',
			args: { supplier },
			freeze: true,
			callback: (r) => {
				const d = r.message || {};
				this.current = d.supplier;
				this.can_edit = cint(d.can_edit);
				this.rows = (d.items || []).map((i) => Object.assign({}, i, { selected: cint(i.selected) }));
				this.set_dirty(false);
				this.$w.find('.spc-sup-name').text(d.supplier_name || d.supplier);
				this.$w.find('.spc-sup-id').text(d.supplier_name && d.supplier_name.trim().toLowerCase() !== d.supplier.trim().toLowerCase() ? d.supplier : '');
				this.$w.find('.spc-readonly').toggle(!this.can_edit);
				this.$w.find('.spc-all').prop('disabled', !this.can_edit);
				const groups = [...new Set(this.rows.map((x) => x.item_group).filter(Boolean))].sort();
				const $g = this.$w.find('.spc-group').empty().append(`<option value="">${__('All item groups')}</option>`);
				groups.forEach((g) => $g.append($('<option>').val(g).text(g)));
				this.$w.find('.spc-item-search').val('');
				this.$w.find('.spc-show').val('');
				this.$w.find('.spc-list').hide();
				this.$w.find('.spc-detail').show();
				this.page.set_title(__('Supplier Catalog: {0}', [d.supplier_name || d.supplier]));
				if (this.can_edit) this.page.set_primary_action(__('Save'), () => this.save(), 'save');
				else this.page.clear_primary_action();
				this.render_items();
			},
		});
	}

	visible_rows() {
		const q = (this.$w.find('.spc-item-search').val() || '').toLowerCase().trim();
		const g = this.$w.find('.spc-group').val();
		const show = this.$w.find('.spc-show').val();
		return this.rows.filter((x) => {
			if (g && x.item_group !== g) return false;
			if (show === 'in' && !x.selected) return false;
			if (show === 'out' && x.selected) return false;
			return !q || `${x.item_code} ${x.item_name || ''}`.toLowerCase().includes(q);
		});
	}

	render_items() {
		const esc = frappe.utils.escape_html;
		const rows = this.visible_rows();
		const ro = !this.can_edit;
		const $b = this.$w.find('.spc-item-body').empty();
		if (!rows.length) {
			$b.append(`<tr><td colspan="6" class="spc-empty">${__('No items match.')}</td></tr>`);
		}
		const html = rows.map((x) => {
			const i = this.rows.indexOf(x);
			const note = x.unavailable ? ` <span class="spc-muted">(${__('disabled item')})</span>` : '';
			return `<tr data-i="${i}" class="${x.selected ? 'on' : ''} ${x.unavailable ? 'off-list' : ''}">
				<td class="chk"><input type="checkbox" class="spc-pick" ${x.selected ? 'checked' : ''} ${ro ? 'disabled' : ''}></td>
				<td class="spc-code">${esc(x.item_code)}${note}</td>
				<td>${esc(x.item_name || '')}</td>
				<td class="spc-hide-sm spc-muted">${esc(x.item_group || '')}</td>
				<td class="spc-hide-sm spc-muted">${esc(x.stock_uom || '')}</td>
				<td><input type="text" class="form-control spc-info" value="${esc(x.additional_info || '')}"
					placeholder="${ro ? '' : __('Optional')}" ${ro || !x.selected ? 'disabled' : ''}></td>
			</tr>`;
		});
		$b.append(html.join(''));
		const ticked = this.rows.filter((x) => x.selected).length;
		this.$w.find('.spc-item-count').text(__('{0} in catalog, {1} shown of {2} items', [ticked, rows.length, this.rows.length]));
		this.$w.find('.spc-all').prop('checked', rows.length > 0 && rows.every((x) => x.selected));
	}

	set_dirty(on) {
		this.dirty = !!on;
		this.$w.find('.spc-dirty').toggle(this.dirty);
	}

	save() {
		if (!this.current || !this.can_edit) return;
		const items = this.rows.filter((x) => x.selected).map((x) => ({
			item_code: x.item_code, additional_info: x.additional_info || '',
		}));
		frappe.call({
			method: 'alpinos.purchase.supplier_catalog.save_catalog',
			args: { supplier: this.current, items },
			freeze: true,
			freeze_message: __('Saving catalog...'),
			callback: (r) => {
				const d = r.message || {};
				this.set_dirty(false);
				frappe.show_alert({ message: __('Catalog saved: {0} items.', [cint(d.count)]), indicator: 'green' });
				const s = this.suppliers.find((x) => x.name === this.current);
				if (s) {
					s.item_count = cint(d.count);
					s.modified = d.modified;
				}
			},
		});
	}

	back() {
		const go = () => {
			this.set_dirty(false);
			this.current = null;
			this.page.clear_primary_action();
			this.page.set_title(__('Supplier Catalog'));
			this.$w.find('.spc-detail').hide();
			this.$w.find('.spc-list').show();
			this.render_suppliers();
		};
		if (this.dirty) frappe.confirm(__('Leave without saving the changes to this catalog?'), go);
		else go();
	}

	// ------------------------------------------------------------------- events

	bind() {
		const me = this;
		this.$w.on('input', '.spc-sup-search', () => this.render_suppliers());
		this.$w.on('change', '.spc-sup-filter', () => this.render_suppliers());
		this.$w.on('click', '.spc-sup-body tr[data-name]', function () {
			me.open($(this).attr('data-name'));
		});
		this.$w.on('click', '.spc-back', () => this.back());
		this.$w.on('input', '.spc-item-search', frappe.utils.debounce(() => this.render_items(), 150));
		this.$w.on('change', '.spc-group, .spc-show', () => this.render_items());
		this.$w.on('change', '.spc-pick', function () {
			const $tr = $(this).closest('tr');
			const x = me.rows[cint($tr.attr('data-i'))];
			x.selected = this.checked ? 1 : 0;
			$tr.toggleClass('on', !!x.selected);
			$tr.find('.spc-info').prop('disabled', !x.selected);
			me.set_dirty(true);
			me.render_count();
		});
		this.$w.on('input', '.spc-info', function () {
			const x = me.rows[cint($(this).closest('tr').attr('data-i'))];
			x.additional_info = $(this).val();
			me.set_dirty(true);
		});
		this.$w.on('change', '.spc-all', function () {
			const on = this.checked ? 1 : 0;
			me.visible_rows().forEach((x) => (x.selected = on));
			me.set_dirty(true);
			me.render_items();
		});
	}

	render_count() {
		const rows = this.visible_rows();
		const ticked = this.rows.filter((x) => x.selected).length;
		this.$w.find('.spc-item-count').text(__('{0} in catalog, {1} shown of {2} items', [ticked, rows.length, this.rows.length]));
		this.$w.find('.spc-all').prop('checked', rows.length > 0 && rows.every((x) => x.selected));
	}
}
