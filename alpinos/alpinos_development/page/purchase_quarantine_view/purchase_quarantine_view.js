/**
 * Quarantine Detail — one Purchase Quarantine document.
 *
 * QC quarantines approved stock while completing a Purchase QC: the GRN receives it into the
 * Quarantine warehouse. This screen shows those items and their one reminder, and lets the
 * Store, QC or Admin team release them into their warehouse
 * (alpinos.purchase.quarantine.release_items): a Material Transfer once the GRN is submitted,
 * or a re-pointed line while the GRN is still a Draft.
 *
 * Older documents (quarantined on the Purchase Inward, before QC) still release the old way,
 * raising a Purchase QC for the released items; ctx.flow tells the two apart.
 */

var ALP_TRIM_MICROSECONDS = function (v) {
	if (typeof v !== 'string') return v;
	var m = v.match(/^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\.\d+$/);
	return m ? m[1] : v;
};

frappe.pages['purchase_quarantine_view'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({ parent: wrapper, title: 'Quarantine Detail', single_column: true });
	page.main.html(frappe.render_template('purchase_quarantine_view'));
	wrapper.pqv = new PurchaseQuarantineView(page);
};

frappe.pages['purchase_quarantine_view'].on_page_show = function (wrapper) {
	// Goods Inward > this list > this record, the same shape as the Production screens.
	alpinos_goods_inward_breadcrumb(__("Quarantine Stock"), "/app/purchase_quarantine_list");
	if (wrapper.pqv) wrapper.pqv.handle_route_entry();
};

var PurchaseQuarantineView = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.docname = null;
		this.doc = null;
		this.ctx = {};
		this.selected = new Set();
		this.bind();
		this.apply_state();
	}

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data', hide_timezone: 1 }, df),
			parent: parent,
			render_input: true,
		});
		c.refresh();
		c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value));
		this.fields[df.fieldname] = c;
		return c;
	}

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const name = route[1];
		const opts = frappe.route_options || {};
		if (cint(opts.release)) this._focus_release = true;
		if (frappe.route_options) delete frappe.route_options.release;
		if (name) {
			// Reload even when it is the document already on screen: the GRN, the QC or a
			// release may have moved on in another screen since (a GRN submitted meanwhile
			// still read "Draft" here), and this page holds nothing unsaved worth keeping.
			this.wrapper.find('.purchase-quarantine-view').removeClass('pqv-blank');
			this.load(name);
		} else if (!name && this.docname) {
			this.docname = null;
			this.doc = null;
			this.page.set_title(__('Quarantine Detail'));
			this.apply_state();
		}
	}

	load(name) {
		const me = this;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Quarantine', name: name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = r.message;
				frappe.call({
					method: 'alpinos.purchase.quarantine.get_quarantine_context',
					args: { purchase_quarantine: doc.name },
					callback(c) {
						me.doc = doc;
						me.ctx = (c && c.message) || {};
						me.docname = doc.name;
						me.selected = new Set();
						me.render();
						me.apply_state();
						me.page.set_title(doc.name);
						if (me._focus_release) {
							me._focus_release = false;
							frappe.show_alert({ message: __('Select the items to release, then click Release Selected.'), indicator: 'blue' });
						}
					},
				});
			},
		});
	}

	render() {
		const doc = this.doc || {};
		const ctx = this.ctx || {};
		const ro = (sel, fieldname, label, fieldtype, options, value) =>
			this._ctl(sel, { fieldname, label, fieldtype: fieldtype || 'Data', options, read_only: 1 },
				value === undefined ? doc[fieldname] : value);

		ro('.field-name', 'name', 'Quarantine ID');
		ro('.field-purchase-inward', 'purchase_inward', 'Purchase Inward', 'Link', 'Purchase Inward');
		ro('.field-purchase-order', 'purchase_order', 'Purchase Order', 'Link', 'Purchase Order');
		ro('.field-purchase-qc', 'purchase_qc', 'Purchase QC', 'Link', 'Purchase QC', ctx.purchase_qc || doc.purchase_qc);
		ro('.field-purchase-receipt', 'purchase_receipt', 'GRN', 'Link', 'Purchase Receipt', ctx.purchase_receipt);
		ro('.field-supplier', 'supplier_name', 'Supplier', 'Data', null, doc.supplier_name || doc.supplier);
		ro('.field-quarantine-date', 'quarantine_date', 'Quarantined On', 'Datetime');
		ro('.field-quarantined-by', 'quarantined_by', 'Quarantined By', 'Link', 'User');
		ro('.field-entire-inward', 'entire_inward', 'All Items', 'Data', null, cint(doc.entire_inward) ? __('Yes') : __('No'));
		ro('.field-inward-status', 'inward_status', 'Inward Status', 'Data', null, ctx.inward_status);
		ro('.field-reason', 'reason', 'Reason', 'Small Text');

		this._ctl('.field-reminder-days', {
			fieldname: 'reminder_days', label: 'Remind After (Days)', fieldtype: 'Int',
			read_only: cint(ctx.can_edit_reminder) ? 0 : 1,
		}, doc.reminder_days);
		ro('.field-next-reminder', 'next_reminder_on', 'Next Reminder On', 'Date');
		ro('.field-last-reminder', 'last_reminder_on', 'Last Reminder On', 'Datetime');
		const $rem = this.wrapper.find('.pqv-reminder-actions').empty();
		if (cint(ctx.can_edit_reminder)) {
			$(`<button class="btn btn-sm btn-default">${__('Update Reminder')}</button>`)
				.on('click', () => this.update_reminder())
				.appendTo($rem);
		}

		this._ctl('.field-release-remarks', {
			fieldname: 'release_remarks', label: 'Release Remarks', fieldtype: 'Small Text',
			read_only: cint(ctx.can_release) ? 0 : 1,
			description: cint(ctx.can_release) ? 'Optional. Saved on every item released in this action.' : '',
		});
		ro('.field-total-qty', 'total_qty', 'Total Quarantined', 'Float');
		ro('.field-held-qty', 'held_qty', 'Still Held', 'Float');
		ro('.field-released-qty', 'released_qty', 'Released', 'Float');

		this.render_items();
	}

	render_items() {
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const can_release = !!cint(this.ctx.can_release);
		const qc_flow = this.ctx.flow === 'qc';
		this.wrapper.find('.pqv-last-col').text(qc_flow ? __('Moved By') : __('QC'));
		const qcs = {};
		(this.ctx.purchase_qcs || []).forEach((q) => { qcs[q.name] = q; });
		const $body = this.wrapper.find('.items-table tbody').empty();
		(this.doc.items || []).forEach((row, i) => {
			const held = row.status === 'Quarantined';
			const qc = row.purchase_qc ? qcs[row.purchase_qc] : null;
			$body.append(`<tr>
				<td class="text-center">${held && can_release
					? `<input type="checkbox" class="pqv-pick" data-row="${esc(row.name)}" ${this.selected.has(row.name) ? 'checked' : ''}>`
					: ''}</td>
				<td class="text-muted">${i + 1}</td>
				<td>${esc(row.item_code)}<div class="text-muted" style="font-size:11px;">${esc(row.item_name)}</div></td>
				<td class="pqv-num">${esc(format_number(flt(row.qty), null, 3))}</td>
				<td>${esc(row.uom)}</td>
				<td>${esc(row.batch_no)}</td>
				<td>${esc(row.target_warehouse)}</td>
				<td><span class="indicator-pill ${held ? 'red' : 'green'}">${esc(__(row.status))}</span></td>
				<td>${row.released_on
					? `${esc(frappe.datetime.str_to_user(ALP_TRIM_MICROSECONDS(row.released_on)))}<div class="text-muted" style="font-size:11px;">${esc(row.released_by)}${row.release_remarks ? ' — ' + esc(row.release_remarks) : ''}</div>`
					: '—'}</td>
				<td>${qc_flow
					? (row.release_stock_entry
						? `<a href="/app/stock-entry/${encodeURIComponent(row.release_stock_entry)}">${esc(row.release_stock_entry)}</a>`
						: (row.status === 'Released' ? `<span class="text-muted">${esc(__('Received on the GRN'))}</span>` : '—'))
					: (row.purchase_qc
						? `<a href="#" class="pqv-open-qc" data-qc="${esc(row.purchase_qc)}">${esc(row.purchase_qc)}</a><div class="text-muted" style="font-size:11px;">${esc(qc ? qc.qc_status || '' : '')}</div>`
						: '—')}</td>
			</tr>`);
		});
		this.wrapper.find('.pqv-select-all').prop('disabled', !can_release).prop('checked', false);
	}

	bind() {
		const me = this;
		this.wrapper.on('change', '.pqv-pick', function () {
			const row = String($(this).data('row'));
			if ($(this).prop('checked')) me.selected.add(row);
			else me.selected.delete(row);
			me.make_actions();
		});
		this.wrapper.on('change', '.pqv-select-all', function () {
			const on = $(this).prop('checked');
			me.wrapper.find('.pqv-pick').each(function () {
				$(this).prop('checked', on);
				const row = String($(this).data('row'));
				if (on) me.selected.add(row);
				else me.selected.delete(row);
			});
			me.make_actions();
		});
		this.wrapper.on('click', '.pqv-open-qc', function (e) {
			e.preventDefault();
			frappe.set_route('purchase_qc_entry', String($(this).data('qc')));
		});
	}

	apply_state() {
		const doc = this.doc || {};
		this.wrapper.find('.purchase-quarantine-view').toggleClass('pqv-blank', !this.docname);
		const status = this.docname ? doc.status || '' : '';
		this.wrapper.find('.field-stage-badge')
			.text(status ? __(status) : '')
			.removeClass('pqv-held pqv-partial pqv-released')
			.addClass(status === 'Released' ? 'pqv-released' : status === 'Partially Released' ? 'pqv-partial' : 'pqv-held');
		let note = '';
		if (this.docname) {
			const qc_flow = this.ctx.flow === 'qc';
			if (qc_flow) {
				if (status === 'Released') note = __('Every item has been released into its warehouse.');
				else if (cint(this.ctx.can_release)) note = __('QC approved these items and quarantined them: the GRN holds them in the Quarantine warehouse, out of use. Select items and click Release Selected to move them into their warehouse.');
				else note = __('QC approved these items and quarantined them. They stay in the Quarantine warehouse until the Store, QC or Admin team releases them.');
			} else if (status === 'Released') note = __('Every item has been released. Each went to its own Purchase QC, then GRN and Purchase Invoice.');
			else if (cint(this.ctx.can_release)) note = __('These items are held out of QC and usable stock. Select items and click Release Selected to send them to QC.');
			else note = __('These items are held out of QC and usable stock until the Store, QC or Admin team releases them.');
		}
		this.wrapper.find('.field-note').text(note);
		this.make_actions();
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.pqv-actionbar').empty();
		if (!this.docname) return;
		const doc = this.doc || {};
		const btn = (label, cls, handler, disabled) =>
			$(`<button class="btn btn-sm ${cls}" style="margin-left:8px;" ${disabled ? 'disabled' : ''}>${frappe.utils.escape_html(label)}</button>`)
				.on('click', handler)
				.appendTo($bar);
		if (cint(this.ctx.can_release)) {
			btn(
				this.selected.size ? __('Release Selected ({0})', [this.selected.size]) : __('Release Selected'),
				'btn-primary',
				() => me.release(),
				!this.selected.size
			);
		}
		btn(__('Go to QC'), 'btn-default', () => me.go_to_qc());
		if (this.ctx.purchase_receipt) {
			btn(__('Open GRN'), 'btn-default', () => frappe.set_route('purchase_grn_view', me.ctx.purchase_receipt));
		}
		btn(__('Open Inward'), 'btn-default', () => frappe.set_route('purchase_inward_entry', doc.purchase_inward));
		btn(__('Quarantine Stock'), 'btn-light', () => frappe.set_route('purchase_quarantine_list'));
		btn(__('Open Full Record'), 'btn-light', () => frappe.set_route('Form', 'Purchase Quarantine', me.docname));
	}

	release() {
		const me = this;
		const rows = Array.from(this.selected);
		if (!rows.length) {
			frappe.msgprint(__('Select the items to release.'));
			return;
		}
		// Ask the server first: what happens on release depends on whether the GRN is still a
		// Draft right now, not when this page was drawn.
		frappe.call({
			method: 'alpinos.purchase.quarantine.get_quarantine_context',
			args: { purchase_quarantine: me.docname },
			callback(c) {
				if (c.exc || !c.message) return;
				me.ctx = c.message;
				me.confirm_release(rows);
			},
		});
	}

	confirm_release(rows) {
		const me = this;
		const qc_flow = this.ctx.flow === 'qc';
		const draft_grn = cint(this.ctx.receipt_docstatus) === 0;
		frappe.confirm(
			qc_flow
				? (draft_grn
					? __('Release {0} item(s)? GRN {1} is still a Draft, so it will receive them straight into their warehouse when it is submitted.', [rows.length, me.ctx.purchase_receipt])
					: __('Release {0} item(s)? Their stock moves from the Quarantine warehouse into their warehouse.', [rows.length]))
				: __('Release {0} item(s)? A Purchase QC is raised for them and they follow the normal QC → GRN → Invoice path.', [rows.length]),
			() =>
				frappe.call({
					method: 'alpinos.purchase.quarantine.release_items',
					args: {
						purchase_quarantine: me.docname,
						rows: JSON.stringify(rows),
						remarks: (me.fields.release_remarks && me.fields.release_remarks.get_value()) || null,
					},
					freeze: true,
					freeze_message: __('Releasing...'),
					callback(r) {
						if (r.exc || !r.message) return;
						const moved = r.message.stock_entries || [];
						frappe.show_alert({
							message: r.message.purchase_qc
								? __('Released — Purchase QC {0} raised', [r.message.purchase_qc])
								: moved.length
									? __('Released — moved into the warehouse by {0}', [moved.join(', ')])
									: __('Released — the GRN will receive them into their warehouse'),
							indicator: 'green',
						}, 6);
						me.load(me.docname);
					},
				})
		);
	}

	// Every QC these goods touch (get_quarantine_context): one opens straight away, several
	// are offered to pick from, none says what raises one.
	go_to_qc() {
		const qcs = this.ctx.purchase_qcs || [];
		if (!qcs.length) {
			frappe.msgprint({
				title: __('No Purchase QC Yet'),
				indicator: 'orange',
				message: __('Nothing from this inward has reached QC yet. Select held items and click Release Selected to raise a Purchase QC for them.'),
			});
			return;
		}
		if (qcs.length === 1) {
			frappe.set_route('purchase_qc_entry', qcs[0].name);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const dialog = new frappe.ui.Dialog({
			title: __('Go to QC'),
			fields: [{
				fieldname: 'list', fieldtype: 'HTML',
				options: qcs.map((q) => `
					<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--border-color);">
						<div>
							<strong>${esc(q.name)}</strong>
							<div class="text-muted" style="font-size:12px;">${esc(q.source === 'inward' ? __('Items that were not quarantined') : q.source === 'quarantined' ? __('Quarantined these items') : __('Released from quarantine'))}${q.qc_status ? ' · ' + esc(__(q.qc_status)) : ''}</div>
						</div>
						<button class="btn btn-sm btn-primary pqv-go-qc" data-qc="${esc(q.name)}">${__('Open')}</button>
					</div>`).join(''),
			}],
		});
		dialog.$wrapper.on('click', '.pqv-go-qc', function () {
			dialog.hide();
			frappe.set_route('purchase_qc_entry', String($(this).data('qc')));
		});
		dialog.show();
	}

	update_reminder() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.quarantine.update_reminder',
			args: { purchase_quarantine: me.docname, reminder_days: cint(me.fields.reminder_days.get_value()) },
			freeze: true,
			callback(r) {
				if (r.exc) return;
				frappe.show_alert({ message: __('Reminder updated'), indicator: 'green' });
				me.load(me.docname);
			},
		});
	}
};
