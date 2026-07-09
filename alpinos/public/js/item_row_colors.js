/**
 * Tint report rows with the Item's SKU color (Item.custom_color).
 *
 * Covers the standard query reports listed in COLOR_REPORTS: the report's
 * formatter is wrapped so every cell of an item's row gets a translucent
 * background in that item's color. The map of item -> color is fetched once
 * per session from alpinos.item_colors.get_item_color_map.
 *
 * To cover another report, add its name and the field that holds the item
 * code to COLOR_REPORTS below.
 */
(function () {
	// report name -> row field carrying the item code
	const COLOR_REPORTS = {
		'Stock Ledger': 'item_code',
		'Stock Balance': 'item_code',
		'Stock Projected Qty': 'item_code',
		'Item-wise Sales Register': 'item_code',
		'Item-wise Delivery Notes': 'item_code',
		'Stock Ageing': 'item_code',
	};
	const TINT_ALPHA = 0.22;

	let color_map = null;

	function fetch_color_map() {
		if (color_map !== null) return;
		color_map = {};
		frappe.call({
			method: 'alpinos.item_colors.get_item_color_map',
			callback: function (r) {
				color_map = r.message || {};
			},
		});
	}

	function hex_to_rgba(hex, alpha) {
		const m = /^#?([0-9a-f]{6})$/i.exec((hex || '').trim());
		if (!m) return '';
		const n = parseInt(m[1], 16);
		return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
	}

	function wrap_formatter(settings, item_field) {
		if (!settings || settings._alpino_sku_tint) return;
		settings._alpino_sku_tint = true;
		const base = settings.formatter;
		settings.formatter = function (value, row, column, data, default_formatter) {
			let out = base
				? base(value, row, column, data, default_formatter)
				: default_formatter(value, row, column, data);
			const color = data && color_map && color_map[data[item_field]];
			if (color) {
				const bg = hex_to_rgba(color, TINT_ALPHA);
				if (bg) {
					// Bleed over the cell padding so the whole row reads as tinted.
					out = `<div style="background:${bg};margin:-8px;padding:8px;">${out}</div>`;
				}
			}
			return out;
		};
	}

	function attach() {
		if (attach._done) return;
		if (!frappe.views || !frappe.views.QueryReport) return;
		attach._done = true;
		fetch_color_map();

		const orig = frappe.views.QueryReport.prototype.render_datatable;
		frappe.views.QueryReport.prototype.render_datatable = function () {
			const item_field = COLOR_REPORTS[this.report_name];
			if (item_field) wrap_formatter(this.report_settings, item_field);
			return orig.apply(this, arguments);
		};
	}

	$(document).on('app_ready', attach);
	setTimeout(attach, 1000);
})();
