/**
 * Inventory Adjustment (FRD 10.3) -- stock audit corrections.
 *
 * Add Stock posts a Material Receipt, Deduct Stock a Material Issue. A deduction above the
 * approval threshold (Production Settings, default 500 KG) goes to Pending Approval and
 * nothing is deducted until the Plant Head approves (10.4.3 / 13.2); a rejection leaves the
 * stock unchanged and is audit logged.
 */

frappe.pages['inventory_adjustment_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Inventory Adjustment'), single_column: true });
	wrapper.entry = new InventoryAdjustmentEntry(page);
};

frappe.pages['inventory_adjustment_entry'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	const name = (frappe.get_route() || [])[1] || 'new';
	wrapper.entry.load(name === 'new' ? null : name);
};

class InventoryAdjustmentEntry {
	constructor(page) {
		this.page = page;
		this.$w = $(page.main);
	}

	load(name) {
		frappe.call({ method: 'alpinos.production.inventory_api.get_adjustment_context', args: { name } })
			.then((r) => { this.ctx = r.message; this.render(); });
	}

	render() {
		const ctx = this.ctx, doc = ctx.doc || {};
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const editable = !!ctx.can_write && (!ctx.doc || cint(doc.docstatus) === 0);
		const status = doc.approval_status || __('Not Saved');
		this.page.set_title(doc.name || __('New Inventory Adjustment'));
		this.page.clear_actions();
		this.page.clear_inner_toolbar();
		this.page.clear_menu();
		this.page.set_indicator(status, { Draft: 'red', 'Pending Approval': 'orange', Posted: 'green',
			Rejected: 'red', Cancelled: 'gray' }[status] || 'orange');
		this.page.add_inner_button(__('Back to List'), () => frappe.set_route('inventory_adjustment_list'));
		this.$w.html(`<div class="iadj">
			<style>.iadj .grid-wrap .frappe-control { margin-bottom: 0; }
				.iadj .grid-wrap .control-label { display:none; }
				.iadj .note { border-left:3px solid var(--orange-500, #f59e0b); padding:6px 10px; margin:8px 0; }</style>
			<div class="note small">${__('Deductions above {0} KG need Plant Head approval before any stock is deducted.', [ctx.threshold_kg])}</div>
			<div class="iadj-head"></div><h5>${__('Item & Batch')}</h5><div class="grid-wrap"></div>
			<div class="iadj-foot small"></div></div>`);
		this.fg = new frappe.ui.FieldGroup({
			parent: this.$w.find('.iadj-head'),
			fields: [
				{ fieldname: 'posting_date', label: __('Adjustment Date'), fieldtype: 'Date', reqd: 1, default: frappe.datetime.get_today() },
				{ fieldname: 'adjustment_type', label: __('Adjustment Type'), fieldtype: 'Select', reqd: 1,
					options: [''].concat(ctx.types), description: __('Add Stock (found extra) or Deduct Stock (lost / damaged).'),
					change: () => this.grid && this.grid.refresh_stock() },
				{ fieldname: 'reason_code', label: __('Reason Code'), fieldtype: 'Select', reqd: 1, options: [''].concat(ctx.reasons) },
				{ fieldtype: 'Column Break' },
				{ fieldname: 'warehouse', label: __('Warehouse'), fieldtype: 'Link', options: 'Warehouse', reqd: 1,
					get_query: () => ({ filters: { is_group: 0, disabled: 0 } }), change: () => this.grid && this.grid.refresh_stock() },
				{ fieldname: 'admin_remarks', label: __('Admin Remarks'), fieldtype: 'Small Text', reqd: 1,
					description: __('Mandatory explanation.') },
			],
		});
		this.fg.make();
		if (ctx.doc) this.fg.set_values(doc);
		this.grid = new AlpInvGrid(this.$w.find('.grid-wrap'), {
			editable,
			warehouse: () => this.fg.get_value('warehouse'),
			any_batch: () => this.fg.get_value('adjustment_type') === 'Add Stock',
			stock_label: __('Current Qty'),
			show_kg: true,
			rows: doc.items || [],
		});
		if (!editable) this.fg.fields_list.forEach((f) => { f.df.read_only = 1; f.refresh(); });
		const foot = [];
		if (ctx.doc) foot.push(__('Total: {0} KG', [format_number(flt(doc.total_kg), null, 3)]));
		if (doc.approved_by) foot.push(__('Approved by {0} on {1}', [esc(doc.approved_by), frappe.datetime.str_to_user(doc.approved_on)]));
		if (doc.rejected_by) foot.push(__('Rejected by {0} on {1}: {2}', [esc(doc.rejected_by),
			frappe.datetime.str_to_user(doc.rejected_on), esc(doc.rejection_reason)]));
		if (doc.stock_entry) foot.push(__('Stock Entry {0}', [`<a href="/app/stock-entry/${encodeURIComponent(doc.stock_entry)}">${esc(doc.stock_entry)}</a>`]));
		this.$w.find('.iadj-foot').html(foot.join(' &middot; '));

		if (editable) {
			this.page.set_primary_action(__('Submit'), () => this.save(1));
			this.page.set_secondary_action(__('Save Draft'), () => this.save(0));
			if (doc.name) this.page.add_menu_item(__('Delete Draft'), () => this.del());
		}
		if (ctx.can_approve) {
			this.page.set_primary_action(__('Approve'), () => this.approve());
			this.page.set_secondary_action(__('Reject'), () => this.reject());
		}
		if (ctx.can_cancel) this.page.add_menu_item(__('Cancel Adjustment'), () => this.cancel());
	}

	call(method, args, msg) {
		return frappe.call({ method: 'alpinos.production.inventory_api.' + method, args, freeze: true })
			.then((r) => { if (msg) frappe.show_alert({ message: msg, indicator: 'green' }); return r.message; });
	}

	save(submit) {
		const v = this.fg.get_values();
		if (!v) return;
		const go = () => this.call('save_adjustment',
			{ payload: Object.assign({ name: (this.ctx.doc || {}).name, items: this.grid.values() }, v), submit },
			submit ? __('Submitted') : __('Saved'))
			.then((m) => { frappe.set_route('inventory_adjustment_entry', m.name); this.load(m.name); });
		if (submit) frappe.confirm(__('Submit this adjustment?'), go); else go();
	}

	approve() {
		frappe.confirm(__('Approve this adjustment? The stock ledger will be updated now.'),
			() => this.call('approve_adjustment', { name: this.ctx.doc.name }, __('Approved')).then(() => this.load(this.ctx.doc.name)));
	}

	reject() {
		frappe.prompt({ fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason for rejection'), reqd: 1 },
			(v) => this.call('reject_adjustment', { name: this.ctx.doc.name, reason: v.reason }, __('Rejected'))
				.then(() => this.load(this.ctx.doc.name)), __('Reject Adjustment'), __('Reject'));
	}

	del() {
		frappe.confirm(__('Delete this draft?'), () => this.call('delete_adjustment', { name: this.ctx.doc.name })
			.then(() => frappe.set_route('inventory_adjustment_list')));
	}

	cancel() {
		frappe.confirm(__('Cancel this adjustment? Any posted stock movement will be reversed.'),
			() => this.call('cancel_adjustment', { name: this.ctx.doc.name }, __('Cancelled')).then(() => this.load(this.ctx.doc.name)));
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
