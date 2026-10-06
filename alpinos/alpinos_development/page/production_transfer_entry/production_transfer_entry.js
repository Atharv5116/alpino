/**
 * Stock Transfer (FRD 10.2) -- one Production Transfer.
 *
 * The Batch picker lists only batches that exist at the Source Location; the Transfer Qty
 * cannot exceed that batch's stock there (checked again on the server: "Insufficient stock
 * in source location."). FG-Hold / QC-Rejected batches may be moved; their status does not
 * change and they stay blocked from dispatch.
 */

frappe.pages['production_transfer_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Stock Transfer'), single_column: true });
	wrapper.entry = new ProductionTransferEntry(page);
};

frappe.pages['production_transfer_entry'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	const name = (frappe.get_route() || [])[1] || 'new';
	wrapper.entry.load(name === 'new' ? null : name);
};

class ProductionTransferEntry {
	constructor(page) {
		this.page = page;
		this.$w = $(page.main);
	}

	load(name) {
		frappe.call({ method: 'alpinos.production.inventory_api.get_transfer_context', args: { name } })
			.then((r) => { this.ctx = r.message; this.render(); });
	}

	render() {
		const ctx = this.ctx, doc = ctx.doc || {};
		const editable = !!ctx.can_write && (!ctx.doc || cint(doc.docstatus) === 0);
		this.page.set_title(doc.name || __('New Stock Transfer'));
		this.page.clear_actions();
		this.page.clear_inner_toolbar();
		this.page.clear_menu();
		this.page.set_indicator(doc.status || __('Not Saved'),
			{ Draft: 'red', Submitted: 'blue', Cancelled: 'gray' }[doc.status] || 'orange');
		this.page.add_inner_button(__('Back to List'), () => frappe.set_route('production_transfer_list'));
		this.$w.html(`<div class="ptr">
			<style>.ptr .grid-wrap td, .ptr .grid-wrap th { vertical-align: middle; }
				.ptr .grid-wrap .frappe-control { margin-bottom: 0; }
				.ptr .grid-wrap .control-label { display:none; }</style>
			<div class="ptr-head"></div><h5>${__('Items')}</h5><div class="grid-wrap"></div>
			<div class="ptr-foot text-muted small"></div></div>`);
		this.fg = new frappe.ui.FieldGroup({
			parent: this.$w.find('.ptr-head'),
			fields: [
				{ fieldname: 'posting_date', label: __('Transfer Date'), fieldtype: 'Date', reqd: 1, default: frappe.datetime.get_today() },
				{ fieldname: 'transfer_type', label: __('Transfer Type'), fieldtype: 'Select', reqd: 1,
					options: [''].concat(ctx.types), change: () => this.suggest() },
				{ fieldname: 'transfer_reason', label: __('Transfer Reason'), fieldtype: 'Select', reqd: 1, options: [''].concat(ctx.reasons) },
				{ fieldtype: 'Column Break' },
				{ fieldname: 'source_warehouse', label: __('Source Location'), fieldtype: 'Link', options: 'Warehouse', reqd: 1,
					get_query: () => ({ filters: { is_group: 0, disabled: 0 } }), change: () => this.grid && this.grid.refresh_stock() },
				{ fieldname: 'target_warehouse', label: __('Target Location'), fieldtype: 'Link', options: 'Warehouse', reqd: 1,
					get_query: () => ({ filters: { is_group: 0, disabled: 0 } }) },
				{ fieldtype: 'Section Break' },
				{ fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text',
					description: __('Required when the reason is Other.') },
			],
		});
		this.fg.make();
		if (ctx.doc) this.fg.set_values(doc);
		this.grid = new AlpInvGrid(this.$w.find('.grid-wrap'), {
			editable,
			warehouse: () => this.fg.get_value('source_warehouse'),
			any_batch: () => false,
			stock_label: __('Available At Source'),
			show_status: true,
			rows: doc.items || [],
		});
		if (!editable) this.fg.fields_list.forEach((f) => { f.df.read_only = 1; f.refresh(); });
		if (doc.stock_entry) {
			this.$w.find('.ptr-foot').html(__('Posted by Stock Entry {0}',
				[`<a href="/app/stock-entry/${encodeURIComponent(doc.stock_entry)}">${frappe.utils.escape_html(doc.stock_entry)}</a>`]));
		}
		if (editable) {
			this.page.set_primary_action(__('Submit'), () => this.save(1));
			this.page.set_secondary_action(__('Save Draft'), () => this.save(0));
			if (doc.name) this.page.add_menu_item(__('Delete Draft'), () => this.del());
		}
		if (ctx.can_cancel) this.page.add_menu_item(__('Cancel Transfer'), () => this.cancel());
	}

	suggest() {
		const t = this.fg.get_value('transfer_type'), c = this.ctx;
		const set = (f, v) => { if (v && !this.fg.get_value(f)) this.fg.set_value(f, v); };
		if (t === 'Floor to Warehouse') { set('source_warehouse', c.wip_warehouse); set('target_warehouse', c.fg_warehouse); }
		if (t === 'Quarantine to Floor') set('target_warehouse', c.wip_warehouse);
	}

	save(submit) {
		const v = this.fg.get_values();
		if (!v) return;
		const go = () => frappe.call({
			method: 'alpinos.production.inventory_api.save_transfer',
			args: { payload: Object.assign({ name: (this.ctx.doc || {}).name, items: this.grid.values() }, v), submit },
			freeze: true,
		}).then((r) => {
			frappe.show_alert({ message: submit ? __('Transfer submitted') : __('Saved'), indicator: 'green' });
			frappe.set_route('production_transfer_entry', r.message.name);
			this.load(r.message.name);
		});
		if (submit) frappe.confirm(__('Submit this transfer? Stock will move immediately.'), go); else go();
	}

	del() {
		frappe.confirm(__('Delete this draft?'), () => frappe.call({
			method: 'alpinos.production.inventory_api.delete_transfer', args: { name: this.ctx.doc.name },
		}).then(() => frappe.set_route('production_transfer_list')));
	}

	cancel() {
		frappe.confirm(__('Cancel this transfer? The stock movement will be reversed.'), () => frappe.call({
			method: 'alpinos.production.inventory_api.cancel_transfer', args: { name: this.ctx.doc.name }, freeze: true,
		}).then(() => this.load(this.ctx.doc.name)));
	}
}

/** Item / batch / qty grid shared by the Stock Transfer and Inventory Adjustment screens. */
if (!window.AlpInvGrid) {
	window.AlpInvGrid = class {
		constructor($parent, opts) {
			this.$p = $parent;
			this.opts = opts;
			this.rows = [];
			this.$p.html(`<table class="table table-bordered table-condensed"><thead><tr>
				<th style="width:40px;">#</th><th>${__('Item / SKU')}</th><th>${__('Batch Code')}</th>
				${opts.show_status ? `<th>${__('FG Status')}</th>` : ''}
				<th style="text-align:right;">${opts.stock_label}</th><th style="width:130px;">${__('Qty')}</th>
				<th>${__('UOM')}</th>${opts.show_kg ? `<th style="text-align:right;">${__('KG')}</th>` : ''}
				${opts.editable ? '<th style="width:40px;"></th>' : ''}</tr></thead><tbody></tbody></table>
				${opts.editable ? `<button class="btn btn-xs btn-default add-row">${__('+ Add Row')}</button>` : ''}`);
			this.$p.find('.add-row').on('click', () => this.add({}));
			(opts.rows || []).forEach((r) => this.add(r));
			if (opts.editable && !this.rows.length) this.add({});
		}

		add(data) {
			const row = { data: Object.assign({}, data) };
			const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
			const $tr = $(`<tr><td class="idx"></td><td class="c-item"></td><td class="c-batch"></td>
				${this.opts.show_status ? '<td class="c-status"></td>' : ''}
				<td class="c-stock" style="text-align:right;"></td><td class="c-qty"></td><td class="c-uom"></td>
				${this.opts.show_kg ? '<td class="c-kg" style="text-align:right;"></td>' : ''}
				${this.opts.editable ? '<td><button class="btn btn-xs btn-danger rm">&times;</button></td>' : ''}</tr>`);
			this.$p.find('tbody').append($tr);
			row.$tr = $tr;
			if (this.opts.editable) {
				row.item = frappe.ui.form.make_control({
					parent: $tr.find('.c-item'), render_input: true,
					df: { fieldtype: 'Link', options: 'Item', fieldname: 'item_code', placeholder: __('Item'),
						get_query: () => (this.opts.any_batch()
							? { filters: { is_stock_item: 1, disabled: 0 } }
							: { query: 'alpinos.production.inventory_api.items_at_warehouse',
								filters: { warehouse: this.opts.warehouse() || '' } }),
						change: () => {
							const v = row.item.get_value();
							if (v !== row.data.item_code) {
								row.data.item_code = v;
								row.data.batch_no = '';
								row.batch.set_value('');
							}
							this.stock(row);
						} },
				});
				row.batch = frappe.ui.form.make_control({
					parent: $tr.find('.c-batch'), render_input: true,
					df: { fieldtype: 'Link', options: 'Batch', fieldname: 'batch_no', placeholder: __('Batch'),
						get_query: () => ({ query: 'alpinos.production.inventory_api.batch_query',
							filters: { item_code: row.data.item_code || '', warehouse: this.opts.warehouse() || '',
								any_batch: this.opts.any_batch() ? 1 : 0 } }),
						change: () => { row.data.batch_no = row.batch.get_value(); this.stock(row); } },
				});
				row.qty = frappe.ui.form.make_control({
					parent: $tr.find('.c-qty'), render_input: true,
					df: { fieldtype: 'Float', fieldname: 'qty', change: () => { row.data.qty = row.qty.get_value(); } },
				});
				[row.item, row.batch, row.qty].forEach((c) => c.refresh());
				if (data.item_code) row.item.set_value(data.item_code);
				if (data.batch_no) row.batch.set_value(data.batch_no);
				if (data.qty) row.qty.set_value(data.qty);
				$tr.find('.rm').on('click', () => { $tr.remove(); this.rows = this.rows.filter((x) => x !== row); this.renumber(); });
			} else {
				$tr.find('.c-item').html(`<b>${esc(data.item_code)}</b><div class="small text-muted">${esc(data.item_name)}</div>`);
				$tr.find('.c-batch').text(data.batch_no || '');
				$tr.find('.c-qty').text(format_number(flt(data.qty), null, 3));
			}
			this.rows.push(row);
			this.paint(row, data);
			this.renumber();
		}

		paint(row, d) {
			const stock = d.available_qty != null ? d.available_qty : d.current_qty;
			row.$tr.find('.c-stock').text(stock == null ? '' : format_number(flt(stock), null, 3));
			row.$tr.find('.c-uom').text(d.uom || '');
			row.$tr.find('.c-status').text(d.fg_status || '');
			row.$tr.find('.c-kg').text(d.qty_kg == null ? '' : format_number(flt(d.qty_kg), null, 3));
		}

		stock(row) {
			const wh = this.opts.warehouse();
			if (!row.data.item_code || !wh) { this.paint(row, {}); return; }
			frappe.call({ method: 'alpinos.production.inventory_api.item_stock',
				args: { item_code: row.data.item_code, warehouse: wh, batch_no: row.data.batch_no || '' } })
				.then((r) => {
					const m = r.message || {};
					this.paint(row, { available_qty: m.qty, uom: m.uom, fg_status: m.fg_status });
				});
		}

		refresh_stock() { this.rows.forEach((r) => this.stock(r)); }

		renumber() { this.rows.forEach((r, i) => r.$tr.find('.idx').text(i + 1)); }

		values() {
			return this.rows.filter((r) => r.data.item_code).map((r) => ({
				item_code: r.data.item_code, batch_no: r.data.batch_no || '', qty: flt(r.data.qty) }));
		}
	};
}
