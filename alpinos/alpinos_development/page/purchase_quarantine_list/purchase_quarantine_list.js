// Quarantine Stock — every Purchase Quarantine document: what each still holds out of QC
// and usable stock, when its reminder is due, and a Release button for the Store / QC /
// Admin teams.
//
// Same shape as the Purchase Inward and Purchase QC lists: filters, sorting and paging are
// server-driven (alpinos.purchase.quarantine_list_api.get_quarantine_list), and the row
// buttons come from that same call.

frappe.pages['purchase_quarantine_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Quarantine Stock'),
		single_column: true,
	});
	frappe.call({
		method: 'alpinos.purchase.quarantine_list_api.get_filter_options',
		callback: (r) => {
			wrapper.__pqrn_list = new PurchaseQuarantineList(page, (r && r.message) || {});
		},
		error: () => {
			wrapper.__pqrn_list = new PurchaseQuarantineList(page, {});
		},
	});
};

frappe.pages['purchase_quarantine_list'].on_page_show = function (wrapper) {
	if (wrapper.__pqrn_list) wrapper.__pqrn_list.render_body();
};

var PQRN_STATUS_COLORS = {
	Quarantined: 'red',
	'Partially Released': 'orange',
	Released: 'green',
};

var PQRN_COLUMNS = [
	{ label: 'Quarantine ID', sort: 'name', width: '9%', render: (d, h) => `<strong>${h.esc(d.name)}</strong>` },
	{
		label: 'Purchase Inward',
		sort: 'purchase_inward',
		width: '9%',
		render: (d, h) => h.link_btn(d.purchase_inward, 'inward'),
	},
	{ label: 'PO No.', width: '9%', render: (d, h) => h.link_btn(d.purchase_order, 'po') },
	{ label: 'Supplier', sort: 'supplier_name', width: '12%', render: (d, h) => h.dash(d.supplier_name || d.supplier) },
	{
		label: 'Items',
		width: '18%',
		render: (d, h) =>
			(d.items || [])
				.map(
					(i) =>
						`<div style="white-space:normal;"><span class="indicator-pill ${
							i.status === 'Released' ? 'green' : 'red'
						}" style="font-size:10px;">${h.esc(__(i.status))}</span> ${h.esc(i.item_code)} <span class="text-muted">— ${h.esc(
							format_number(i.qty, null, 2)
						)} ${h.esc(i.uom || '')}</span></div>`
				)
				.join('') || '—',
	},
	{ label: 'Held Qty', sort: 'held_qty', cls: 'text-right', width: '6%', render: (d, h) => h.num(d.held_qty) },
	{ label: 'Released Qty', cls: 'text-right', width: '6%', render: (d, h) => h.num(d.released_qty) },
	{ label: 'Quarantined On', sort: 'quarantine_date', width: '8%', render: (d, h) => h.datetime(d.quarantine_date) },
	{
		label: 'Next Reminder',
		sort: 'next_reminder_on',
		width: '8%',
		render: (d, h) =>
			d.next_reminder_on
				? `<span class="${d.reminder_due ? 'text-danger' : ''}" title="${h.esc(
						__('Every {0} day(s)', [d.reminder_days || 0])
				  )}">${h.esc(frappe.datetime.str_to_user(d.next_reminder_on))}${d.reminder_due ? ' ' + h.esc(__('(due)')) : ''}</span>`
				: '—',
	},
	{ label: 'Status', sort: 'status', width: '8%', render: (d, h) => h.status(d.status) },
	{ label: 'Actions', width: '8%', render: (d, h) => h.actions(d) },
];

function pqrn_body_html() {
	return `
<style>
	.pqrn-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px 14px; }
	.pqrn-grid > * { min-width: 0; }
	.pqrn-table-wrapper { padding: 0; overflow-x: auto; }
	.pqrn-table { width: 100%; min-width: 1400px; margin-bottom: 0; font-size: 13px; border-collapse: collapse; }
	.pqrn-table th, .pqrn-table td {
		padding: 9px 12px; border-bottom: 1px solid var(--border-color, #e2e2e2); vertical-align: top;
	}
	.pqrn-table thead th {
		position: sticky; top: 0; z-index: 2; background: var(--card-bg, #fff); font-size: 11px;
		font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase; color: var(--text-muted, #6c7680);
		white-space: nowrap;
	}
	.pqrn-table tbody tr.pqrn-row { cursor: pointer; }
	.pqrn-table tbody tr.pqrn-row:hover { background: var(--bg-light-gray, #f6f7f9); }
	.pqrn-table .btn { margin: 0 4px 4px 0; }
	.pqrn-pager { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 12px; }
</style>
<div class="pqrn-list">
	<div class="alp-card">
		<div class="alp-section-title">${__('Filters')}</div>
		<div class="pqrn-grid">
			<div class="fld-quarantine-id"></div>
			<div class="fld-purchase-inward"></div>
			<div class="fld-supplier"></div>
			<div class="fld-item-code"></div>
			<div class="fld-status"></div>
			<div class="fld-from-date"></div>
			<div class="fld-to-date"></div>
			<div class="fld-reminder-due"></div>
		</div>
		<div class="alp-actions" style="margin-top: 14px;">
			<button class="btn btn-primary btn-sm btn-pqrn-apply">${__('Apply')}</button>
			<button class="btn btn-default btn-sm btn-pqrn-clear">${__('Clear')}</button>
			<span class="pqrn-total text-muted" style="margin-left: auto; font-size: 12px;"></span>
		</div>
	</div>
	<div class="pqrn-table-wrapper alp-card">
		<table class="pqrn-table"><thead><tr></tr></thead><tbody></tbody></table>
	</div>
	<div class="pqrn-pager">
		<div class="pqrn-count text-muted"></div>
		<div>
			<button class="btn btn-default btn-sm btn-pqrn-prev">${__('Previous')}</button>
			<button class="btn btn-default btn-sm btn-pqrn-next">${__('Next')}</button>
		</div>
	</div>
</div>`;
}

var PurchaseQuarantineList = class {
	constructor(page, options) {
		this.page = page;
		this.options = options || {};
		this.page_length = 20;
		this.start = 0;
		this.meta = { has_more: 0, total: 0 };
		this.sort = { field: '', dir: 'desc' };
		this.fields = {};
		this.rows = {};
		this.page.add_inner_button(__('Refresh'), () => this.load());
		this.page.add_inner_button(__('Reminders Due'), () => {
			this._suspend = true;
			this.fields.reminder_due && this.fields.reminder_due.set_input(1);
			this._suspend = false;
			this.start = 0;
			this.load();
		});
		this.render_body();
	}

	render_body() {
		this.page.main.html(pqrn_body_html());
		this.wrapper = $(this.page.main);
		const mk = (key, df, sel) => {
			this.fields[key] = frappe.ui.form.make_control({
				df: Object.assign({ fieldname: key }, df),
				parent: this.wrapper.find(sel),
				render_input: true,
			});
		};
		mk('quarantine_id', { fieldtype: 'Data', label: __('Quarantine ID') }, '.fld-quarantine-id');
		mk('purchase_inward', { fieldtype: 'Data', label: __('Purchase Inward') }, '.fld-purchase-inward');
		mk('supplier', { fieldtype: 'Link', options: 'Supplier', label: __('Supplier') }, '.fld-supplier');
		mk('item_code', { fieldtype: 'Link', options: 'Item', label: __('Item') }, '.fld-item-code');
		mk(
			'status',
			{
				fieldtype: 'Select',
				label: __('Status'),
				options: this.options.statuses || '\nQuarantined\nPartially Released\nReleased',
			},
			'.fld-status'
		);
		mk('from_date', { fieldtype: 'Date', label: __('Quarantined From') }, '.fld-from-date');
		mk('to_date', { fieldtype: 'Date', label: __('Quarantined To') }, '.fld-to-date');
		mk('reminder_due', { fieldtype: 'Check', label: __('Reminder due') }, '.fld-reminder-due');

		this.render_header();
		this.bind();
		this.load();
	}

	bind() {
		const w = this.wrapper;
		w.off('.pqrn');
		w.find('.btn-pqrn-apply').on('click', () => {
			this.start = 0;
			this.load();
		});
		w.find('.btn-pqrn-clear').on('click', () => {
			this._suspend = true;
			Object.values(this.fields).forEach((f) => f.set_value(''));
			this._suspend = false;
			this.start = 0;
			this.load();
		});
		w.find('.btn-pqrn-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load();
		});
		w.find('.btn-pqrn-next').on('click', () => {
			if (this.meta.has_more) {
				this.start += this.page_length;
				this.load();
			}
		});
		w.on('click.pqrn', '.pqrn-row', (e) => {
			if ($(e.target).closest('a,button,input').length) return;
			const name = $(e.currentTarget).data('name');
			if (name) frappe.set_route('purchase_quarantine_view', String(name));
		});
		w.on('click.pqrn', '.pqrn-link', (e) => {
			e.stopPropagation();
			const $b = $(e.currentTarget);
			const value = String($b.data('value') || '');
			if (!value) return;
			if ($b.data('target') === 'po') frappe.set_route('Form', 'Purchase Order', value);
			else frappe.set_route('purchase_inward_entry', value);
		});
		w.on('click.pqrn', '.pqrn-act', (e) => {
			e.stopPropagation();
			const $b = $(e.currentTarget);
			const name = String($b.data('name'));
			if ($b.data('action') === 'release') frappe.route_options = { release: 1 };
			frappe.set_route('purchase_quarantine_view', name);
		});
		w.on('click.pqrn', '.pqrn-sort', (e) => {
			const field = $(e.currentTarget).data('sort');
			this.sort = { field: field, dir: this.sort.field === field && this.sort.dir === 'asc' ? 'desc' : 'asc' };
			this.start = 0;
			this.render_header();
			this.load();
		});
		const auto = frappe.utils.debounce(() => {
			if (this._suspend) return;
			this.start = 0;
			this.load();
		}, 350);
		Object.values(this.fields).forEach((f) => f.$input && f.$input.on('input change awesomplete-selectcomplete', auto));
	}

	render_header() {
		const tr = this.wrapper.find('.pqrn-table thead tr').empty();
		PQRN_COLUMNS.forEach((c) => {
			const cls = c.cls || '';
			if (!c.sort) {
				tr.append(`<th class="${cls}" style="width:${c.width}">${__(c.label)}</th>`);
				return;
			}
			const active = this.sort.field === c.sort;
			const arrow = active ? (this.sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';
			tr.append(
				`<th class="${cls} pqrn-sort" data-sort="${c.sort}" style="width:${c.width};cursor:pointer;">${__(c.label)}<span class="text-muted" style="font-size:10px;opacity:${active ? 1 : 0.4}">${arrow}</span></th>`
			);
		});
	}

	load() {
		const val = (k) => (this.fields[k] && this.fields[k].get_value()) || '';
		frappe.call({
			method: 'alpinos.purchase.quarantine_list_api.get_quarantine_list',
			args: {
				start: this.start,
				page_length: this.page_length,
				quarantine_id: val('quarantine_id'),
				purchase_inward: val('purchase_inward'),
				supplier: val('supplier'),
				item_code: val('item_code'),
				status: val('status'),
				from_date: val('from_date'),
				to_date: val('to_date'),
				reminder_due: cint(val('reminder_due')),
				sort_field: this.sort.field,
				sort_dir: this.sort.dir,
			},
			freeze: true,
			callback: (r) => {
				if (r.exc) return;
				const msg = r.message || {};
				this.meta = { has_more: cint(msg.has_more), total: cint(msg.total), start: cint(msg.start) };
				this.render_rows(msg.data || []);
			},
		});
	}

	render_rows(rows) {
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const h = {
			esc,
			dash: (v) => (v ? esc(v) : '—'),
			num: (v) => esc(format_number(flt(v), null, 2)),
			datetime: (v) => (v ? esc(frappe.datetime.str_to_user(String(v).split('.')[0])) : '—'),
			link_btn: (v, target) =>
				v
					? `<button type="button" class="btn btn-xs btn-default pqrn-link" data-target="${target}" data-value="${esc(v)}">${esc(v)}</button>`
					: '—',
			status: (s) => (s ? `<span class="indicator-pill ${PQRN_STATUS_COLORS[s] || 'gray'}">${esc(__(s))}</span>` : '—'),
			actions: (d) =>
				(d.actions || [])
					.map(
						(a) =>
							`<button type="button" class="btn btn-xs ${a.kind === 'transition' ? 'btn-primary' : 'btn-default'} pqrn-act" data-name="${esc(
								d.name
							)}" data-action="${esc(a.action)}">${esc(a.label)}</button>`
					)
					.join(''),
		};
		const tb = this.wrapper.find('.pqrn-table tbody').empty();
		this.rows = {};
		if (!rows.length) {
			tb.append(`<tr><td colspan="${PQRN_COLUMNS.length}" class="text-muted text-center">${__('No quarantined stock found')}</td></tr>`);
		}
		rows.forEach((d) => {
			this.rows[d.name] = d;
			tb.append(
				`<tr class="pqrn-row" data-name="${esc(d.name)}">${PQRN_COLUMNS.map(
					(c) => `<td class="${c.cls || ''}">${c.render(d, h)}</td>`
				).join('')}</tr>`
			);
		});
		const n = rows.length;
		this.wrapper.find('.pqrn-count').text(
			n ? __('Showing {0}–{1} of {2}', [this.meta.start + 1, this.meta.start + n, this.meta.total]) : __('No rows on this page')
		);
		this.wrapper.find('.pqrn-total').text(__('{0} Quarantine document(s)', [this.meta.total]));
		this.wrapper.find('.btn-pqrn-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-pqrn-next').prop('disabled', !this.meta.has_more);
	}
};
