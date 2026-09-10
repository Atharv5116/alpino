/**
 * GRN List — the goods receipts this module raised.
 *
 * The GRN is ERPNext's Purchase Receipt, so unlike the inward and QC lists this one
 * has to draw a boundary: only receipts carrying a Purchase Inward link, and never a
 * Purchase Return (make_purchase_return copies that link off the receipt it
 * returns). The boundary lives in grn_list_api._module_filters, server-side, so it
 * cannot be argued with from here.
 *
 * Rows open the read-only GRN Detail screen (BRD 5.2), not the raw desk form.
 */

// var, not const: desk pages are re-evaluated on navigation and a re-declared const
// blanks the page.
var GRN_LIST_FILTERS = ['grn_id', 'purchase_inward', 'supplier', 'grn_status', 'from_date', 'to_date'];

frappe.pages['purchase_grn_list'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'GRN List',
		single_column: true,
	});
	wrapper.grn_list = new GRNList(page);
};

frappe.pages['purchase_grn_list'].on_page_show = function (wrapper) {
	if (wrapper.grn_list) wrapper.grn_list.refresh();
};

var GRNList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.filters = {};
		this.start = 0;
		this.page_length = 20;
		this.sort_field = 'modified';
		this.sort_dir = 'desc';
		this.total = 0;
		this.render_shell();
		this.load_options();
		this.refresh();
	}

	render_shell() {
		this.wrapper.html(`
			<div class="purchase-grn-list" style="padding:12px;">
				<p class="text-muted" style="font-size:12px;margin-bottom:12px;">
					BRD 5 — every goods receipt raised from a Purchase QC. Purchase Returns are
					excluded: a return copies the inward link off the receipt it returns.
				</p>
				<div class="eso-card grn-filters">
					<h6 class="eso-card-title">Filters</h6>
					<div class="row">
						<div class="col-md-2 col-sm-6 eso-fld f-grn-id"></div>
						<div class="col-md-2 col-sm-6 eso-fld f-purchase-inward"></div>
						<div class="col-md-2 col-sm-6 eso-fld f-supplier"></div>
						<div class="col-md-2 col-sm-6 eso-fld f-grn-status"></div>
						<div class="col-md-2 col-sm-6 eso-fld f-from-date"></div>
						<div class="col-md-2 col-sm-6 eso-fld f-to-date"></div>
					</div>
					<div class="alp-actions" style="margin-top:6px;">
						<button class="btn btn-sm btn-primary btn-apply">Apply</button>
						<button class="btn btn-sm btn-light btn-clear">Clear</button>
						<span class="text-muted grn-count" style="margin-left:auto;font-size:12px;"></span>
					</div>
				</div>
				<div class="eso-card">
					<h6 class="eso-card-title">Goods Receipts</h6>
					<div class="alp-scroll alp-scroll--xwide"
						data-empty="No GRN matches these filters. A GRN appears here once a Purchase QC is completed.">
						<table class="table table-bordered grn-table">
							<thead><tr>
								<th style="min-width:130px;">GRN</th>
								<th style="width:100px;">Posting Date</th>
								<th style="min-width:170px;">Vendor</th>
								<th style="min-width:130px;">Purchase Inward</th>
								<th style="min-width:130px;">Purchase QC</th>
								<th style="width:120px;">GRN Status</th>
								<th style="width:95px;" class="text-right">Accepted</th>
								<th style="width:95px;" class="text-right">Rejected</th>
								<th style="min-width:130px;">Debit Note</th>
							</tr></thead>
							<tbody></tbody>
						</table>
					</div>
					<div class="alp-actions" style="margin-top:10px;">
						<button class="btn btn-sm btn-light btn-prev">Previous</button>
						<button class="btn btn-sm btn-light btn-next">Next</button>
						<span class="text-muted grn-range" style="margin-left:8px;font-size:12px;"></span>
					</div>
				</div>
			</div>
		`);

		const me = this;
		this._ctl('.f-grn-id', { fieldname: 'grn_id', label: 'GRN', fieldtype: 'Data' });
		this._ctl('.f-purchase-inward', {
			fieldname: 'purchase_inward', label: 'Purchase Inward',
			fieldtype: 'Link', options: 'Purchase Inward',
		});
		this._ctl('.f-supplier', {
			fieldname: 'supplier', label: 'Vendor', fieldtype: 'Link', options: 'Supplier',
		});
		this._ctl('.f-grn-status', {
			fieldname: 'grn_status', label: 'GRN Status', fieldtype: 'Select', options: '',
		});
		this._ctl('.f-from-date', { fieldname: 'from_date', label: 'From', fieldtype: 'Date' });
		this._ctl('.f-to-date', { fieldname: 'to_date', label: 'To', fieldtype: 'Date' });

		this.wrapper.on('click', '.btn-apply', () => { me.start = 0; me.refresh(); });
		this.wrapper.on('click', '.btn-clear', () => {
			GRN_LIST_FILTERS.forEach((f) => { if (me.fields[f]) me.fields[f].set_value(''); });
			me.start = 0;
			me.refresh();
		});
		this.wrapper.on('click', '.btn-prev', () => {
			me.start = Math.max(me.start - me.page_length, 0);
			me.refresh();
		});
		this.wrapper.on('click', '.btn-next', () => {
			if (me.start + me.page_length < me.total) {
				me.start += me.page_length;
				me.refresh();
			}
		});
		this.wrapper.on('click', '.grn-open', function (e) {
			e.preventDefault();
			frappe.set_route('purchase_grn_view', $(this).attr('data-name'));
		});
	}

	_ctl(selector, df) {
		this.fields = this.fields || {};
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data' }, df),
			parent: parent,
			render_input: true,
		});
		c.refresh();
		this.fields[df.fieldname] = c;
		return c;
	}

	load_options() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.grn_list_api.get_filter_options',
			callback(r) {
				const opts = (r.message && r.message.grn_statuses) || [];
				const c = me.fields.grn_status;
				if (c) {
					c.df.options = [''].concat(opts).join('\n');
					c.refresh();
				}
			},
		});
	}

	_filter_values() {
		const out = {};
		GRN_LIST_FILTERS.forEach((f) => {
			const c = this.fields[f];
			const v = c ? c.get_value() : null;
			if (v) out[f] = v;
		});
		return out;
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.grn_list_api.get_grn_list',
			args: Object.assign({
				start: this.start,
				page_length: this.page_length,
				sort_field: this.sort_field,
				sort_dir: this.sort_dir,
			}, this._filter_values()),
			callback(r) {
				if (!r.message) return;
				me.total = cint(r.message.total);
				me.render_rows(r.message.rows || []);
			},
		});
	}

	render_rows(rows) {
		const $body = this.wrapper.find('.grn-table tbody').empty();
		rows.forEach((row) => {
			const rejected = flt(row.rejected_qty);
			$body.append($(`
				<tr>
					<td><a href="#" class="grn-open" data-name="${frappe.utils.escape_html(row.name)}">${frappe.utils.escape_html(row.name)}</a></td>
					<td>${frappe.utils.escape_html(frappe.datetime.str_to_user(row.posting_date) || '')}</td>
					<td>${frappe.utils.escape_html(row.supplier_name || row.supplier || '')}</td>
					<td>${frappe.utils.escape_html(row.custom_purchase_inward || '')}</td>
					<td>${frappe.utils.escape_html(row.custom_purchase_qc || '')}</td>
					<td>${frappe.utils.escape_html(row.custom_grn_status || '')}</td>
					<td class="text-right">${format_number(row.accepted_qty, null, 3)}</td>
					<td class="text-right ${rejected ? 'text-danger' : ''}">${format_number(rejected, null, 3)}</td>
					<td>${frappe.utils.escape_html(row.custom_debit_note || '')}</td>
				</tr>
			`));
		});

		const to = Math.min(this.start + this.page_length, this.total);
		this.wrapper.find('.grn-count').text(__('{0} GRN', [this.total]));
		this.wrapper.find('.grn-range').text(
			this.total ? __('Showing {0} to {1}', [this.start + 1, to]) : ''
		);
	}
};
