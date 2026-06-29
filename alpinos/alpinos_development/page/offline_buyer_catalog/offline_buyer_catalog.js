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
			let master_cell = '<span style="color:#ccc;">—</span>';
			const biz = (rec.customer_business_name || '').trim();
			const obm = (rec.offline_buyer_master || '').trim();
			if (biz || obm) {
				const lines = [];
				if (biz) {
					lines.push(`<span style="font-weight:600;color:#333;">${frappe.utils.escape_html(biz)}</span>`);
				}
				if (obm) {
					lines.push(`<span style="font-size:11px;color:#666;">${frappe.utils.escape_html(obm)}</span>`);
				}
				master_cell = `<div style="line-height:1.35;">${lines.join('<br>')}</div>`;
			}
			const site_cell = rec.site_name
				? `<span>${frappe.utils.escape_html(rec.site_name)}</span>`
				: `<span style="color:#ccc;">—</span>`;
			const ctype_cell = rec.customer_type
				? `<span>${frappe.utils.escape_html(rec.customer_type)}</span>`
				: `<span style="color:#ccc;">—</span>`;
			const level_cell = rec.level
				? `<span>${frappe.utils.escape_html(rec.level)}</span>`
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
  <td>${master_cell}</td>
  <td>${site_cell}</td>
  <td>${ctype_cell}</td>
  <td>${level_cell}</td>
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
				(r.level || '').toLowerCase().includes(q) ||
				(r.payment_term || '').toLowerCase().includes(q) ||
				String(r.payment_term_days ?? '').toLowerCase().includes(q) ||
				(r.party_owner || '').toLowerCase().includes(q)
			);
		this._render_records_table(filtered);
	}

	_show_new_dialog() {
		const me = this;

		// ── helper: do the actual catalog creation (duplicate-check then insert) ──
		const do_create_catalog = (d, obm, title, description) => {
			// create_record handles customer resolution and duplicate checking server-side
			frappe.call({
				method: 'alpinos.offline_buyer_api.create_record',
				args: { title, offline_buyer_master: obm, description: description || '' },
				freeze: true,
				freeze_message: __('Creating catalog…'),
				callback: (rc) => {
					d.hide();
					if (!rc.exc) {
						frappe.show_alert({ message: `Created: ${rc.message}`, indicator: 'green' });
						const newName = rc.message;
						me._load_records(() => {
							const full = me._all_records.find((row) => row.name === newName);
							me._open_record(full || { name: newName, title, offline_buyer_master: obm });
						});
					}
				},
			});
		};

		// ── quick-create buyer sub-dialog ─────────────────────────────────────
		const show_create_buyer_dialog = (catalog_title, catalog_desc) => {
			const bd = new frappe.ui.Dialog({
				title: 'Create New Offline Buyer',
				fields: [
					{ label: 'Business Name', fieldname: 'business_name', fieldtype: 'Data', reqd: 1 },
					{ label: 'Parent Buyer', fieldname: 'parent_buyer', fieldtype: 'Link', options: 'Offline Buyer Master' },
					{
						label: 'Customer Type', fieldname: 'customer_type', fieldtype: 'Link',
						options: 'Alpino Customer Type',
						reqd: 1,
					},
					{
						label: 'Level', fieldname: 'level', fieldtype: 'Select',
						options: '\nSuperstockist\nDistributor',
						reqd: 1,
					},
					{
						label: 'GST Type', fieldname: 'gst_type', fieldtype: 'Select',
						options: '\nOverseas\nRegistered Business\nUnregistered Business',
						reqd: 1,
					},
					{
						label: 'GST No', fieldname: 'gst_no', fieldtype: 'Data',
						depends_on: 'eval:doc.gst_type=="Registered Business"',
						mandatory_depends_on: 'eval:doc.gst_type=="Registered Business"',
					},
					{
						label: 'PAN No', fieldname: 'pan_no', fieldtype: 'Data',
						depends_on: 'eval:doc.gst_type=="Unregistered Business"',
						mandatory_depends_on: 'eval:doc.gst_type=="Unregistered Business"',
					},
					{
						label: 'Payment Term', fieldname: 'payment_term', fieldtype: 'Select',
						options: '\nAdvance\nCredit\nPartial\nNA', default: 'Advance', reqd: 1,
					},
					{ fieldtype: 'Section Break', label: 'Contact' },
					{ label: 'Email', fieldname: 'email', fieldtype: 'Data', options: 'Email', reqd: 1 },
					{ label: 'Contact No', fieldname: 'contact_no', fieldtype: 'Data', options: 'Phone', reqd: 1 },
					{ label: 'Contact Person', fieldname: 'contact_person', fieldtype: 'Data', reqd: 1 },
					{ fieldtype: 'Section Break', label: 'Primary Address' },
					{ label: 'Site Name / Trade Name', fieldname: 'site_name', fieldtype: 'Data' },
					{ label: 'Address Line', fieldname: 'address_line', fieldtype: 'Data', reqd: 1 },
					{ label: 'Country', fieldname: 'country', fieldtype: 'Link', options: 'Country', reqd: 1, default: 'India' },
					{ label: 'State', fieldname: 'state', fieldtype: 'Link', options: 'State', reqd: 1 },
					{ label: 'City', fieldname: 'city', fieldtype: 'Link', options: 'City', reqd: 1 },
					{ label: 'Area', fieldname: 'area', fieldtype: 'Data' },
					{ label: 'Pincode', fieldname: 'pincode', fieldtype: 'Data', reqd: 1 },
				],
				primary_action_label: 'Create Buyer & Catalog',
				primary_action: (v) => {
					bd.hide();
					frappe.call({
						method: 'alpinos.offline_buyer_api.quick_create_offline_buyer',
						args: {
							business_name: v.business_name,
							site_name: v.site_name || '',
							customer_type: v.customer_type,
							level: v.level,
							gst_type: v.gst_type,
							gst_no: v.gst_no || '',
							pan_no: v.pan_no || '',
							payment_term: v.payment_term,
							email: v.email,
							contact_no: v.contact_no,
							contact_person: v.contact_person,
							address_line: v.address_line,
							pincode: v.pincode,
							country: v.country,
							state: v.state,
							city: v.city,
							area: v.area,
							is_parent: 0,
							parent_buyer: v.parent_buyer,
						},
						freeze: true,
						freeze_message: __('Creating offline buyer...'),
						callback: (r) => {
							if (r.exc || !r.message) return;
							const obm_name = r.message;
							frappe.show_alert({ message: __('Buyer created: {0}', [v.business_name]), indicator: 'green' });

							// Now create the catalog for the newly created buyer
							do_create_catalog(
								{ hide: () => {} },  // already hidden
								obm_name,
								catalog_title || v.business_name,
								catalog_desc || ''
							);
						},
					});
				},
			});

			// State → City dependency
			bd.fields_dict.state && bd.fields_dict.state.$input.on('change awesomplete-selectcomplete', function () {
				const st = bd.get_value('state');
				if (bd.fields_dict.city) {
					bd.fields_dict.city.df.get_query = () => ({ filters: { state: st || '' } });
					bd.set_value('city', '');
				}
			});

			// Parent Buyer filter & auto-fetch
			bd.fields_dict.parent_buyer && (bd.fields_dict.parent_buyer.df.get_query = () => ({
				filters: { is_parent: 1 }
			}));
			bd.fields_dict.parent_buyer && bd.fields_dict.parent_buyer.$input.on('change awesomplete-selectcomplete', function () {
				const pb = bd.get_value('parent_buyer');
				if (pb) {
					frappe.db.get_value('Offline Buyer Master', pb, 'customer_business_name', (r) => {
						if (r && r.customer_business_name && !bd.get_value('business_name')) {
							bd.set_value('business_name', r.customer_business_name);
						}
					});
				}
			});

			bd.show();
		};

		// ── main catalog creation dialog ──────────────────────────────────────
		const d = new frappe.ui.Dialog({
			title: 'New Catalog',
			fields: [
				{ label: 'Catalog Title', fieldname: 'title', fieldtype: 'Data', reqd: 1 },
				{ fieldtype: 'Section Break', label: 'Buyer' },
				{
					label: 'Select Existing Buyer',
					fieldname: 'offline_buyer_master',
					fieldtype: 'Link',
					options: 'Offline Buyer Master',
					description: 'Search by business name to pick an existing offline buyer.',
				},
				{
					fieldtype: 'HTML',
					fieldname: 'or_divider',
					options: '<div style="text-align:center;color:var(--text-muted);margin:6px 0;font-size:12px;">— or —</div>',
				},
				{
					fieldtype: 'Button',
					fieldname: 'btn_new_buyer',
					label: 'Create New Buyer',
				},
				{ fieldtype: 'Section Break', label: '' },
				{ label: 'Description', fieldname: 'description', fieldtype: 'Small Text' },
			],
			primary_action_label: 'Create Catalog',
			primary_action: (values) => {
				const obm = values.offline_buyer_master || '';
				if (!obm) {
					frappe.msgprint(__('Please select an existing buyer or click "Create New Buyer".'));
					return;
				}
				do_create_catalog(d, obm, values.title, values.description);
			},
		});

		// Wire up the "Create New Buyer" button inside the dialog
		d.fields_dict.btn_new_buyer && d.fields_dict.btn_new_buyer.$input.on('click', () => {
			const catalog_title = d.get_value('title');
			const catalog_desc = d.get_value('description');
			d.hide();
			show_create_buyer_dialog(catalog_title, catalog_desc);
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
		if (rec.customer_business_name) {
			buyer_bits.push(`Business: ${rec.customer_business_name}`);
		}
		if (rec.offline_buyer_master) {
			buyer_bits.push(`Offline Buyer Master: ${rec.offline_buyer_master}`);
		}
		if (rec.buyer) {
			const nm = (rec.buyer_customer_name || '').trim();
			buyer_bits.push(
				nm ? `Linked customer: ${nm} (${rec.buyer})` : `Linked customer: ${rec.buyer}`
			);
		}
		if (rec.site_name) {
			buyer_bits.push(`Site: ${rec.site_name}`);
		}
		if (rec.customer_type) {
			buyer_bits.push(`Customer type: ${rec.customer_type}`);
		}
		if (rec.level) {
			buyer_bits.push(`Level: ${rec.level}`);
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

		// Edit Buyer Info
		$(document).on('click', '.obi-btn-edit-buyer', () => {
			if (this._current_record) this._show_edit_buyer_dialog(this._current_record);
		});
	}

	/* ═══════════════════════════════════════════════════════════════════════
	   EDIT BUYER DIALOG
	══════════════════════════════════════════════════════════════════════════ */

	_show_edit_buyer_dialog(rec) {
		const me = this;
		const obm_name = rec.offline_buyer_master;
		if (!obm_name) {
			frappe.msgprint(__('No Offline Buyer Master linked to this catalog.'));
			return;
		}

		frappe.call({
			method: 'alpinos.offline_buyer_api.get_offline_buyer_master_details',
			args: { obm_name },
			freeze: true,
			freeze_message: __('Loading buyer details…'),
			callback(r) {
				if (!r.message) return;
				me._render_edit_buyer_dialog(rec, obm_name, r.message);
			},
		});
	}

	_render_edit_buyer_dialog(rec, obm_name, obm) {
		const me = this;

		// ── address row tracker ────────────────────────────────────────────────
		// Each entry: { address_label, address_line, pincode, country, state, city,
		//               area, sub_area, is_primary, is_shipping, $el }
		const addr_rows = [];

		// State → City lookup cache
		let _all_states = [];      // ['Gujarat', 'Maharashtra', ...]
		let _cities_by_state = {}; // { Gujarat: ['Ahmedabad', 'Surat', ...], ... }

		const _load_states_cities = (cb) => {
			if (_all_states.length) { cb && cb(); return; }
			frappe.call({
				method: 'frappe.client.get_list',
				args: { doctype: 'State', fields: ['name'], limit_page_length: 1000, order_by: 'name asc' },
				callback(rs) {
					_all_states = (rs.message || []).map(r => r.name);
					frappe.call({
						method: 'frappe.client.get_list',
						args: { doctype: 'City', fields: ['name', 'state'], limit_page_length: 5000, order_by: 'name asc' },
						callback(rc) {
							_cities_by_state = {};
							(rc.message || []).forEach(c => {
								if (!_cities_by_state[c.state]) _cities_by_state[c.state] = [];
								_cities_by_state[c.state].push(c.name);
							});
							cb && cb();
						},
					});
				},
			});
		};

		const _state_options_html = (selected) =>
			'<option value=""></option>' +
			_all_states.map(s => `<option value="${frappe.utils.escape_html(s)}"${s === selected ? ' selected' : ''}>${frappe.utils.escape_html(s)}</option>`).join('');

		const _city_options_html = (state, selected) => {
			const cities = _cities_by_state[state] || (selected ? [selected] : []);
			return '<option value=""></option>' +
				cities.map(c => `<option value="${frappe.utils.escape_html(c)}"${c === selected ? ' selected' : ''}>${frappe.utils.escape_html(c)}</option>`).join('');
		};

		const _refresh_city_select = ($tr, state, selected) => {
			$tr.find('.addr-city').html(_city_options_html(state, selected));
		};

		const render_addr_table = ($host) => {
			$host.html(`
				<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
					<strong style="font-size:13px;">Addresses</strong>
					<button class="btn btn-xs btn-default obi-add-addr-row">+ Add Address</button>
				</div>
				<table class="obi-addr-table">
					<thead>
						<tr>
							<th style="width:110px;">Site Name</th>
							<th style="width:90px;">Label</th>
							<th style="min-width:160px;">Address Line *</th>
							<th style="width:75px;">Pincode</th>
							<th style="width:100px;">Country *</th>
							<th style="width:100px;">State *</th>
							<th style="width:100px;">City *</th>
							<th style="width:80px;">Area</th>
							<th style="width:70px;">Sub Area</th>
							<th style="width:50px;text-align:center;">Primary</th>
							<th style="width:55px;text-align:center;">Shipping</th>
							<th style="width:30px;"></th>
						</tr>
					</thead>
					<tbody class="obi-addr-tbody"></tbody>
				</table>
			`);

			$host.on('click', '.obi-add-addr-row', () => {
				add_addr_row({});
			});

			// Primary radio behaviour: only one primary at a time
			$host.on('change', '.obi-chk-primary', function () {
				if ($(this).is(':checked')) {
					$host.find('.obi-chk-primary').not(this).prop('checked', false);
				}
			});
		};

		const add_addr_row = (data) => {
			const idx = addr_rows.length;
			const row = {
				site_name: data.site_name || '',
				address_label: data.address_label || '',
				address_line: data.address_line || '',
				pincode: data.pincode || '',
				country: data.country || 'India',
				state: data.state || '',
				city: data.city || '',
				area: data.area || '',
				sub_area: data.sub_area || '',
				is_primary: data.is_primary ? 1 : 0,
				is_shipping: data.is_shipping ? 1 : 0,
			};
			addr_rows.push(row);

			const $tr = $(`
				<tr data-addr-idx="${idx}">
					<td><input type="text" class="addr-site" value="${frappe.utils.escape_html(row.site_name)}" placeholder="e.g. Mumbai DC" /></td>
						<td><input type="text" class="addr-label" value="${frappe.utils.escape_html(row.address_label)}" placeholder="e.g. Warehouse" /></td>
					<td><input type="text" class="addr-line" value="${frappe.utils.escape_html(row.address_line)}" placeholder="Street / Building" /></td>
					<td><input type="text" class="addr-pincode" value="${frappe.utils.escape_html(row.pincode)}" placeholder="400001" style="width:70px;" /></td>
					<td><input type="text" class="addr-country" value="${frappe.utils.escape_html(row.country)}" placeholder="India" /></td>
					<td><select class="addr-state" style="width:100%;">${_state_options_html(row.state)}</select></td>
					<td><select class="addr-city" style="width:100%;">${_city_options_html(row.state, row.city)}</select></td>
					<td><input type="text" class="addr-area" value="${frappe.utils.escape_html(row.area)}" placeholder="Shivaji Nagar" /></td>
					<td><input type="text" class="addr-sub-area" value="${frappe.utils.escape_html(row.sub_area)}" placeholder="" /></td>
					<td style="text-align:center;"><input type="checkbox" class="obi-chk-primary" ${row.is_primary ? 'checked' : ''} /></td>
					<td style="text-align:center;"><input type="checkbox" class="obi-chk-shipping" ${row.is_shipping ? 'checked' : ''} /></td>
					<td style="text-align:center;"><button class="obi-addr-row-del" title="Remove row">✕</button></td>
				</tr>
			`);

			// State → filter City dropdown
			$tr.on('change', '.addr-state', function () {
				_refresh_city_select($tr, $(this).val(), '');
			});

			$tr.on('click', '.obi-addr-row-del', () => {
				addr_rows.splice(idx, 1);
				$tr.remove();
				$('.obi-addr-tbody tr').each((i, el) => $(el).data('addr-idx', i));
			});

			$('.obi-addr-tbody').append($tr);
		};

		const collect_addresses = () => {
			const result = [];
			$('.obi-addr-tbody tr').each((_, tr) => {
				const $tr = $(tr);
				result.push({
					site_name: $tr.find('.addr-site').val().trim(),
					address_label: $tr.find('.addr-label').val().trim(),
					address_line: $tr.find('.addr-line').val().trim(),
					pincode: $tr.find('.addr-pincode').val().trim(),
					country: $tr.find('.addr-country').val().trim(),
					state: $tr.find('.addr-state').val().trim(),
					city: $tr.find('.addr-city').val().trim(),
					area: $tr.find('.addr-area').val().trim(),
					sub_area: $tr.find('.addr-sub-area').val().trim(),
					is_primary: $tr.find('.obi-chk-primary').is(':checked') ? 1 : 0,
					is_shipping: $tr.find('.obi-chk-shipping').is(':checked') ? 1 : 0,
				});
			});
			return result;
		};

		// ── dialog ────────────────────────────────────────────────────────────
		const d = new frappe.ui.Dialog({
			title: `Edit Buyer — ${obm.customer_business_name || obm_name}`,
			size: 'extra-large',
			fields: [
				// Business info
				{ fieldtype: 'Section Break', label: 'Business Information' },
				{ label: 'Business Name', fieldname: 'customer_business_name', fieldtype: 'Data', reqd: 1, default: obm.customer_business_name },
				{ label: 'Is Parent', fieldname: 'is_parent', fieldtype: 'Check', default: obm.is_parent },
				{ label: 'Parent Buyer', fieldname: 'parent_buyer', fieldtype: 'Link', options: 'Offline Buyer Master', default: obm.parent_buyer },
				{ fieldtype: 'Column Break' },
				{
					label: 'Customer Type', fieldname: 'customer_type', fieldtype: 'Link',
					options: 'Alpino Customer Type',
					reqd: 1, default: obm.customer_type,
				},
				{
					label: 'Level', fieldname: 'level', fieldtype: 'Select',
					options: '\nSuperstockist\nDistributor\nN/A',
					reqd: 1, default: obm.level,
				},
				{
					label: 'GST Type', fieldname: 'gst_type', fieldtype: 'Select',
					options: '\nOverseas\nRegistered Business\nUnregistered Business',
					reqd: 1, default: obm.gst_type,
				},
				{ label: 'GST No', fieldname: 'gst_no', fieldtype: 'Data', default: obm.gst_no,
				  depends_on: 'eval:doc.gst_type=="Registered Business"' },
				{ label: 'PAN No', fieldname: 'pan_no', fieldtype: 'Data', default: obm.pan_no,
				  depends_on: 'eval:doc.gst_type=="Unregistered Business"' },
				// Payment
				{ fieldtype: 'Section Break', label: 'Payment Terms' },
				{
					label: 'Payment Term', fieldname: 'payment_term', fieldtype: 'Select',
					options: '\nAdvance\nCredit\nPartial\nNA', reqd: 1, default: obm.payment_term,
				},
				{ fieldtype: 'Column Break' },
				{ label: 'Days', fieldname: 'payment_term_days', fieldtype: 'Data',
				  default: obm.payment_term_days,
				  depends_on: 'eval:doc.payment_term=="Credit"||doc.payment_term=="Partial"' },
				// Contact
				{ fieldtype: 'Section Break', label: 'Contact' },
				{ label: 'Email', fieldname: 'email', fieldtype: 'Data', options: 'Email', reqd: 1, default: obm.email },
				{ label: 'Contact No', fieldname: 'contact_no', fieldtype: 'Data', options: 'Phone', reqd: 1, default: obm.contact_no },
				{ fieldtype: 'Column Break' },
				{ label: 'Alternate No', fieldname: 'alternate_no', fieldtype: 'Data', options: 'Phone', default: obm.alternate_no },
				{ label: 'Contact Person', fieldname: 'contact_person', fieldtype: 'Data', reqd: 1, default: obm.contact_person },
				// Addresses (custom HTML section)
				{ fieldtype: 'Section Break', label: 'Addresses' },
				{ fieldtype: 'HTML', fieldname: 'addresses_html', options: '<div class="obi-addr-host"></div>' },
			],
			primary_action_label: 'Save',
			primary_action(values) {
				const addresses = collect_addresses();
				if (!addresses.length) {
					frappe.msgprint(__('Add at least one address.'));
					return;
				}
				const primary_count = addresses.filter(a => a.is_primary).length;
				if (primary_count === 0) {
					frappe.msgprint(__('Mark exactly one address as Primary.'));
					return;
				}
				if (primary_count > 1) {
					frappe.msgprint(__('Only one address can be Primary.'));
					return;
				}

				const updates = {
					customer_business_name: values.customer_business_name,
					customer_type: values.customer_type,
					level: values.level || '',
					gst_type: values.gst_type,
					gst_no: values.gst_no || '',
					pan_no: values.pan_no || '',
					payment_term: values.payment_term,
					payment_term_days: values.payment_term_days || null,
					email: values.email,
					contact_no: values.contact_no,
					alternate_no: values.alternate_no || '',
					contact_person: values.contact_person,
					is_parent: values.is_parent,
					parent_buyer: values.parent_buyer,
				};

				frappe.call({
					method: 'alpinos.offline_buyer_api.update_offline_buyer_master',
					args: { obm_name, updates: JSON.stringify(updates), addresses: JSON.stringify(addresses) },
					freeze: true,
					freeze_message: __('Saving…'),
					callback(r) {
						if (r.exc) return;
						d.hide();
						frappe.show_alert({ message: __('Buyer info updated'), indicator: 'green' });
						// Refresh the list so the header reflects new values
						me._load_records(() => {
							const updated = me._all_records.find(row => row.name === rec.name);
							if (updated) {
								me._current_record = updated;
								// Update breadcrumb text inline
								$('.obi-detail-buyer').html(
									[
										updated.customer_business_name ? `Business: ${updated.customer_business_name}` : '',
										updated.parent_buyer ? `Parent: ${updated.parent_buyer}` : '',
										`Customer type: ${updated.customer_type || ''}`,
										`Payment: ${updated.payment_term || ''}`,
									].filter(Boolean).map(b => frappe.utils.escape_html(b)).join(' · ')
								);
							}
						});
					},
				});
			},
		});

		d.set_values(obm);
		d.show();

		// Render the address host after dialog is shown — load states/cities first
		setTimeout(() => {
			const $host = d.$wrapper.find('.obi-addr-host');
			render_addr_table($host);
			_load_states_cities(() => {
				(obm.addresses && obm.addresses.length ? obm.addresses : [{}]).forEach(a => add_addr_row(a));
			});
		}, 80);
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
