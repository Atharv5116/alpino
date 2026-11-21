// Changes(HP) #51: an order dispatched in parts can carry one invoice per part (SOR-.../2, /3).
// The SI button on the Sales Order lists opens this list when there is more than one, each
// invoice with its own Download, instead of downloading only the order's first PDF.
frappe.provide('alpinos');

alpinos.download_order_invoice = function (sales_order, invoice_no) {
	let url = '/api/method/alpinos.sales_order_api.download_single_invoice?name=' + encodeURIComponent(sales_order);
	if (invoice_no) url += '&invoice_no=' + encodeURIComponent(invoice_no);
	const w = window.open(url, '_blank');
	if (!w) frappe.msgprint(__('Please allow pop-ups to download the invoice.'));
};

alpinos.show_order_invoices = function (sales_order) {
	if (!sales_order) return;
	frappe.call({
		method: 'alpinos.sales_order_invoices.get_sales_order_invoices',
		args: { sales_order },
		callback(r) {
			const rows = (r.message || {}).invoices || [];
			const esc = frappe.utils.escape_html;
			if (!rows.length) {
				frappe.msgprint(__('No invoice is linked to {0} yet.', [sales_order]));
				return;
			}
			const body = rows
				.map((i) => {
					const part = i.part_label ? `<span class="text-muted"> (${esc(i.part_label)})</span>` : '';
					const date = i.invoice_date ? frappe.datetime.str_to_user(i.invoice_date) : '—';
					const amt = i.invoice_amount ? format_currency(i.invoice_amount) : '—';
					const dl = i.invoice_pdf
						? `<button type="button" class="btn btn-xs btn-default oi-download" data-inv="${esc(i.invoice_no)}">${__('Download')}</button>`
						: `<span class="text-muted">${__('No PDF')}</span>`;
					return `<tr>
						<td><strong>${esc(i.invoice_no)}</strong>${part}</td>
						<td>${esc(date)}</td>
						<td class="text-right">${amt}</td>
						<td class="text-right">${dl}</td>
					</tr>`;
				})
				.join('');
			const d = new frappe.ui.Dialog({
				title: __('Invoices for {0}', [sales_order]),
				size: 'large',
				primary_action_label: __('Close'),
				primary_action() { d.hide(); },
			});
			d.$body.html(`
				<table class="table table-bordered" style="margin-bottom:0;">
					<thead><tr>
						<th>${__('Invoice No')}</th>
						<th>${__('Invoice Date')}</th>
						<th class="text-right">${__('Amount')}</th>
						<th class="text-right">${__('Download')}</th>
					</tr></thead>
					<tbody>${body}</tbody>
				</table>`);
			d.$body.on('click', '.oi-download', (e) => {
				alpinos.download_order_invoice(sales_order, $(e.currentTarget).attr('data-inv'));
			});
			d.show();
		},
	});
};

// The SI button of an order list row: one invoice downloads as before, several open the list.
alpinos.order_invoice_button = function (d, cls) {
	const n = cint(d.invoice_count);
	if (!d.has_invoice_pdf && n < 2) return '';
	const esc = frappe.utils.escape_html;
	const title = n > 1
		? __('{0} invoices: {1} and more', [n, d.invoice_no || ''])
		: __('Download invoice PDF {0}', [d.invoice_no || '']);
	return `<button type="button" class="btn btn-xs btn-default ${cls}" data-so="${esc(d.name)}" data-count="${n}"
		title="${esc(title)}">SI${n > 1 ? ` (${n})` : ''}</button>`;
};

alpinos.order_invoice_click = function (e) {
	e.stopPropagation();
	const $b = $(e.currentTarget);
	const so = $b.attr('data-so') || '';
	if (!so) return;
	if (cint($b.data('count')) > 1) alpinos.show_order_invoices(so);
	else alpinos.download_order_invoice(so);
};
