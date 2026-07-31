/**
 * Item list view: tint each row with the item's SKU color (custom_color).
 * Extends — never replaces — erpnext's Item listview settings (alpinos loads
 * after erpnext, so its settings object already exists).
 */
(function () {
	const TINT_ALPHA = 0.22;

	function hex_to_rgba(hex, alpha) {
		const m = /^#?([0-9a-f]{6})$/i.exec((hex || '').trim());
		if (!m) return '';
		const n = parseInt(m[1], 16);
		return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
	}

	function apply_colors(listview) {
		if (!listview || !listview.data) return;
		const rows = listview.$result && listview.$result.find('.list-row-container');
		if (!rows || !rows.length) return;
		listview.data.forEach(function (doc, i) {
			const bg = doc.custom_color ? hex_to_rgba(doc.custom_color, TINT_ALPHA) : '';
			if (rows[i]) rows[i].style.background = bg;
		});
	}

	frappe.listview_settings['Item'] = frappe.listview_settings['Item'] || {};
	const settings = frappe.listview_settings['Item'];

	settings.add_fields = (settings.add_fields || []).concat(['custom_color']);

	const orig_refresh = settings.refresh;
	settings.refresh = function (listview) {
		if (orig_refresh) orig_refresh(listview);
		apply_colors(listview);
	};
	const orig_onload = settings.onload;
	settings.onload = function (listview) {
		if (orig_onload) orig_onload(listview);
		// render happens after onload; refresh() covers subsequent renders
		setTimeout(function () { apply_colors(listview); }, 300);
	};
})();
