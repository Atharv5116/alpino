frappe.pages['sales-order-entry-view'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Sales Order Entry View',
		single_column: true
	});
	page.main.html(frappe.render_template('sales_order_entry_view'));
	new SalesOrderEntryView(page);
};

class SalesOrderEntryView {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.setup();
	}

	setup() {
		const ro = frappe.route_options || {};
		const so_name = ro.sales_order || ro.name || '';
		if (!so_name) {
			this._ask_for_order();
			return;
		}
		this.load_order(so_name);
	}

	_ask_for_order() {
		frappe.prompt(
			[{ fieldname: 'sales_order', label: 'Sales Order', fieldtype: 'Link', options: 'Sales Order', reqd: 1 }],
			(v) => this.load_order(v.sales_order),
			'Open Sales Order Entry View',
			'Open'
		);
	}

	load_order(name) {
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Sales Order', name: name },
			freeze: true,
			freeze_message: __('Loading Sales Order...'),
			callback: (r) => {
				if (!r.message) return;
				this.render(r.message);
			},
		});
	}

	render(doc) {
		const w = this.wrapper;
		w.find('.v-so-name').text(doc.name || '-');
		w.find('.v-customer').text(doc.customer_name || doc.customer || '-');
		w.find('.v-order-type').text(doc.order_type || '-');
		w.find('.v-delivery-date').text(doc.delivery_date || '-');
		w.find('.v-billing').text(doc.customer_address || '-');
		w.find('.v-shipping').text(doc.shipping_address_name || '-');
		w.find('.v-tax-category').text(doc.tax_category || '-');
		w.find('.v-tax-template').text(doc.taxes_and_charges || '-');

		const tb = w.find('.v-items tbody').empty();
		(doc.items || []).forEach((it, i) => {
			tb.append(`
				<tr>
					<td>${i + 1}</td>
					<td>${frappe.utils.escape_html(it.item_code || '')}</td>
					<td>${frappe.utils.escape_html(it.item_name || '')}</td>
					<td class="text-right">${flt(it.qty)}</td>
					<td class="text-right">${flt(it.custom_box)}</td>
					<td class="text-right">${format_currency(it.custom_customer_mrp || 0)}</td>
					<td class="text-right">${flt(it.custom_gst_percent)}</td>
					<td class="text-right">${flt(it.custom_flat_discount)}</td>
					<td class="text-right">${flt(it.custom_offer)}</td>
					<td class="text-right">${flt(it.custom_additional_discount)}</td>
					<td class="text-right">${format_currency(it.rate || 0)}</td>
					<td class="text-right">${format_currency(it.amount || 0)}</td>
				</tr>
			`);
		});

		w.find('.v-total').text(format_currency(doc.total || 0));
		w.find('.v-total-taxes').text(format_currency(doc.total_taxes_and_charges || 0));
		w.find('.v-cash-discount').text(format_currency(doc.custom_cash_discount_amount || 0));
		w.find('.v-grand-total').text(format_currency(doc.grand_total || 0));
	}
}
