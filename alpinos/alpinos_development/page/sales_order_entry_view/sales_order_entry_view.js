frappe.pages['sales-order-entry-view'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Sales Order View'),
		single_column: true,
	});
	page.main.html(frappe.render_template('sales_order_entry_view'));
	new SalesOrderEntryView(page);
};

class SalesOrderEntryView {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this._so_name = '';
		this.setup_toolbar();
		this.setup();
	}

	setup_toolbar() {
		this.page.add_inner_button(__('Back to Sales Order List'), () => {
			frappe.set_route('page', 'sales-order-entry-list');
		});
		this.page.add_inner_button(__('Open in ERPNext'), () => {
			if (this._so_name) {
				frappe.set_route('Form', 'Sales Order', this._so_name);
			}
		});
		this.page.add_inner_button(__('Print'), () => this.open_default_print_preview());
		this.page.add_inner_button(__('Download PDF'), () => this.download_default_print_pdf());
	}

	_ensure_loaded_name() {
		if (!this._so_name) {
			frappe.msgprint(__('Open a Sales Order first.'));
			return false;
		}
		if (!frappe.model.can_print('Sales Order')) {
			frappe.msgprint(__('You do not have permission to print Sales Orders.'));
			return false;
		}
		return true;
	}

	/** Desk print preview: uses DocType default print format (same as Form → Print). */
	open_default_print_preview() {
		if (!this._ensure_loaded_name()) return;
		frappe.set_route('print', 'Sales Order', this._so_name);
	}

	/** PDF download using the default print format for Sales Order. */
	download_default_print_pdf() {
		if (!this._ensure_loaded_name()) return;

		frappe.model.with_doctype('Sales Order', () => {
			const meta = frappe.get_meta('Sales Order');
			const format_name = (meta.default_print_format || '').trim() || 'Standard';

			const open_wk = () => {
				const url =
					'/api/method/frappe.utils.print_format.download_pdf?' +
					'doctype=' +
					encodeURIComponent('Sales Order') +
					'&name=' +
					encodeURIComponent(this._so_name) +
					'&format=' +
					encodeURIComponent(format_name) +
					'&no_letterhead=0';
				const w = window.open(frappe.urllib.get_full_url(url));
				if (!w) frappe.msgprint(__('Please allow pop-ups to download the PDF.'));
			};

			frappe.db.get_value('Print Format', format_name, 'print_format_builder_beta').then((r) => {
				const beta = r.message && r.message.print_format_builder_beta;
				if (cint(beta)) {
					const params = new URLSearchParams({
						doctype: 'Sales Order',
						name: this._so_name,
						print_format: format_name,
						letterhead: '',
					});
					const w = window.open(
						frappe.urllib.get_full_url(
							'/api/method/frappe.utils.weasyprint.download_pdf?' + params.toString()
						)
					);
					if (!w) frappe.msgprint(__('Please allow pop-ups to download the PDF.'));
				} else {
					open_wk();
				}
			});
		});
	}

	setup() {
		const ro = frappe.route_options || {};
		let so_name = ro.sales_order || ro.name || '';
		if (!so_name && frappe.urllib && frappe.urllib.get_arg) {
			so_name = frappe.urllib.get_arg('sales_order') || '';
		}
		if (!so_name) {
			this._ask_for_order();
			return;
		}
		this.load_order(so_name);
	}

	_ask_for_order() {
		frappe.prompt(
			[
				{
					fieldname: 'sales_order',
					label: __('Sales Order'),
					fieldtype: 'Link',
					options: 'Sales Order',
					reqd: 1,
				},
			],
			(v) => this.load_order(v.sales_order),
			__('Open Sales Order View'),
			__('Open')
		);
	}

	load_order(name) {
		this._so_name = name;
		frappe.call({
			method: 'alpinos.sales_order_api.get_sales_order_entry_view_payload',
			args: { sales_order: name },
			freeze: true,
			freeze_message: __('Loading Sales Order...'),
			callback: (r) => {
				if (!r.message) return;
				this.page.set_title(__('Sales Order View — {0}', [name]));
				this.render(r.message);
			},
		});
	}

	_has(parent, key) {
		return parent && Object.prototype.hasOwnProperty.call(parent, key);
	}

	_esc(s) {
		return frappe.utils.escape_html(s == null ? '' : String(s));
	}

	_fmt_date(parent, key) {
		if (!this._has(parent, key)) return '—';
		const v = parent[key];
		if (!v) return '—';
		try {
			return frappe.datetime.str_to_user(v);
		} catch (e) {
			return this._esc(v);
		}
	}

	_fmt_num(parent, key, as_currency) {
		if (!this._has(parent, key)) return '—';
		const v = parent[key];
		if (v === '' || v === null || v === undefined) return '—';
		const n = flt(v);
		if (as_currency) return format_currency(n);
		return String(n);
	}

	_set_kv_row(parent, key, $td) {
		if (!this._has(parent, key)) {
			$td.closest('tr').hide();
			return;
		}
		$td.closest('tr').show();
	}

	render(payload) {
		const p = payload.parent || {};
		const w = this.wrapper;

		// Customer block — order matches template
		w.find('.v-customer-name').text(this._has(p, 'customer_name') ? this._esc(p.customer_name) : '—');
		w.find('.v-order-type').text(this._has(p, 'order_type') ? this._esc(p.order_type) : '—');
		w.find('.v-billing').html(this._has(p, 'address_display') ? frappe.utils.escape_html(p.address_display) : '—');
		w.find('.v-shipping').html(this._has(p, 'shipping_address') ? frappe.utils.escape_html(p.shipping_address) : '—');
		w.find('.v-date').text(this._fmt_date(p, 'transaction_date'));
		w.find('.v-po-no').text(this._has(p, 'po_no') ? this._esc(p.po_no) : '—');
		w.find('.v-tax-id').text(this._has(p, 'tax_id') ? this._esc(p.tax_id) : '—');
		w.find('.v-delivery-date').text(this._fmt_date(p, 'delivery_date'));

		// Hide customer rows where field not permitted
		[
			['customer_name', '.v-customer-name'],
			['order_type', '.v-order-type'],
			['address_display', '.v-billing'],
			['shipping_address', '.v-shipping'],
			['transaction_date', '.v-date'],
			['po_no', '.v-po-no'],
			['tax_id', '.v-tax-id'],
			['delivery_date', '.v-delivery-date'],
		].forEach(([key, sel]) => {
			const $tr = w.find(sel).closest('tr');
			if (!this._has(p, key)) {
				$tr.hide();
			} else {
				$tr.show();
			}
		});

		// Items
		const items = payload.items;
		if (items != null) {
			w.find('.sec-order-items').show();
			const tb = w.find('.v-items tbody').empty();
			items.forEach((it, i) => {
				const img = it.custom_product_image_url || it.custom_product_image || '';
				const imgTag = img
					? `<img src="${this._esc(img)}" alt="" style="max-height:40px;max-width:64px;" />`
					: '—';
				const sku = this._has(it, 'item_code') ? this._esc(it.item_code) : '—';
				const nm = this._has(it, 'item_name') ? this._esc(it.item_name) : '—';
				const qty = this._has(it, 'qty') ? flt(it.qty) : null;
				const box = this._has(it, 'custom_box') ? flt(it.custom_box) : null;
				const mrp = this._has(it, 'custom_customer_mrp') ? format_currency(flt(it.custom_customer_mrp)) : '—';
				const fd = this._has(it, 'custom_flat_discount') ? flt(it.custom_flat_discount) : null;
				const of = this._has(it, 'custom_offer') ? flt(it.custom_offer) : null;
				const ad = this._has(it, 'custom_additional_discount') ? flt(it.custom_additional_discount) : null;
				const amt = this._has(it, 'amount') ? format_currency(flt(it.amount)) : '—';
				tb.append(`<tr>
					<td>${i + 1}</td>
					<td class="text-center">${imgTag}</td>
					<td>${sku}</td>
					<td>${nm}</td>
					<td class="text-right">${qty != null ? qty : '—'}</td>
					<td class="text-right">${box != null ? box : '—'}</td>
					<td class="text-right">${mrp}</td>
					<td class="text-right">${fd != null ? fd : '—'}</td>
					<td class="text-right">${of != null ? of : '—'}</td>
					<td class="text-right">${ad != null ? ad : '—'}</td>
					<td class="text-right">${amt}</td>
				</tr>`);
			});
		} else {
			w.find('.sec-order-items').hide();
		}

		// Freebies
		const freebies = payload.freebies;
		if (freebies != null) {
			w.find('.sec-marketing-freebies').show();
			const fb = w.find('.v-freebies tbody').empty();
			if (!freebies.length) {
				fb.append('<tr><td colspan="4" class="text-muted text-center">—</td></tr>');
			} else {
				freebies.forEach((row) => {
					fb.append(`<tr>
						<td>${this._has(row, 'item_code') ? this._esc(row.item_code) : '—'}</td>
						<td>${this._has(row, 'item_name') ? this._esc(row.item_name) : '—'}</td>
						<td class="text-right">${this._has(row, 'qty') ? flt(row.qty) : '—'}</td>
						<td>${this._has(row, 'remarks') ? this._esc(row.remarks) : '—'}</td>
					</tr>`);
				});
			}
		} else {
			w.find('.sec-marketing-freebies').hide();
		}

		const damage = !!payload.additional_units_damage;
		const schemeRows = payload.scheme_rows;

		if (schemeRows != null) {
			w.find('.sec-scheme').show();
			if (damage) {
				w.find('.v-scheme-title').text(__('Additional Units – Damage'));
				w.find('.v-scheme-head-normal').hide();
				w.find('.v-scheme-head-damage').show();
			} else {
				w.find('.v-scheme-title').text(__('Scheme Item'));
				w.find('.v-scheme-head-normal').show();
				w.find('.v-scheme-head-damage').hide();
			}
			const sb = w.find('.v-scheme tbody').empty();
			if (!schemeRows.length) {
				sb.append(`<tr><td colspan="${damage ? 5 : 4}" class="text-muted text-center">—</td></tr>`);
			} else if (damage) {
				schemeRows.forEach((row) => {
					sb.append(`<tr>
						<td>${this._has(row, 'item_code') ? this._esc(row.item_code) : '—'}</td>
						<td>${this._has(row, 'item_name') ? this._esc(row.item_name) : '—'}</td>
						<td class="text-right">${this._has(row, 'qty') ? flt(row.qty) : '—'}</td>
						<td>${this._has(row, 'previous_order_id') ? this._esc(row.previous_order_id) : '—'}</td>
						<td>${this._has(row, 'remarks') ? this._esc(row.remarks) : '—'}</td>
					</tr>`);
				});
			} else {
				schemeRows.forEach((row) => {
					sb.append(`<tr>
						<td>${this._has(row, 'item_code') ? this._esc(row.item_code) : '—'}</td>
						<td>${this._has(row, 'item_name') ? this._esc(row.item_name) : '—'}</td>
						<td class="text-right">${this._has(row, 'qty') ? flt(row.qty) : '—'}</td>
						<td>${this._has(row, 'scheme') ? this._esc(row.scheme) : '—'}</td>
					</tr>`);
				});
			}
		} else {
			w.find('.sec-scheme').hide();
		}

		if (this._has(p, 'custom_additional_units_damage')) {
			w.find('.sec-damage-flag').show();
			w.find('.v-damage-flag')
				.toggleClass('label-success', damage)
				.toggleClass('label-default', !damage)
				.text(damage ? __('Yes') : __('No'));
		} else {
			w.find('.sec-damage-flag').hide();
		}

		if (this._has(p, 'custom_cash_discount')) {
			w.find('.sec-cash-disc').show();
			w.find('.v-cash-disc-pct').text(`${flt(p.custom_cash_discount)}%`);
		} else {
			w.find('.sec-cash-disc').hide();
		}

		const showMoneyBlock = (keys) => keys.some((k) => this._has(p, k));
		if (showMoneyBlock(['total_qty', 'total', 'custom_cash_discount', 'grand_total'])) {
			w.find('.sec-grand').show();
			w.find('.v-total-qty').text(this._has(p, 'total_qty') ? String(flt(p.total_qty)) : '—');
			w.find('.v-total-amount').text(this._fmt_num(p, 'total', true));
			w.find('.v-grand-cash-pct').text(this._has(p, 'custom_cash_discount') ? `${flt(p.custom_cash_discount)}%` : '—');
			w.find('.v-grand-total').html(`<strong>${this._fmt_num(p, 'grand_total', true)}</strong>`);
		} else {
			w.find('.sec-grand').hide();
		}

		if (this._has(p, 'total_taxes_and_charges')) {
			w.find('.sec-taxes').show();
			w.find('.v-total-gst').text(this._fmt_num(p, 'total_taxes_and_charges', true));
		} else {
			w.find('.sec-taxes').hide();
		}

		if (showMoneyBlock(['net_total', 'total_taxes_and_charges', 'rounding_adjustment', 'rounded_total'])) {
			w.find('.sec-net').show();
			w.find('.v-net-total-excl').text(this._fmt_num(p, 'net_total', true));
			w.find('.v-net-total-gst').text(this._fmt_num(p, 'total_taxes_and_charges', true));
			w.find('.v-rounding').text(this._fmt_num(p, 'rounding_adjustment', true));
			w.find('.v-rounded-total').html(`<strong>${this._fmt_num(p, 'rounded_total', true)}</strong>`);
		} else {
			w.find('.sec-net').hide();
		}

		const anyOrderDetails =
			items != null ||
			freebies != null ||
			schemeRows != null ||
			this._has(p, 'custom_additional_units_damage');
		w.find('.so-view-order-details-wrap').toggle(!!anyOrderDetails);
	}
}
