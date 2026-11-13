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

	// Changes(HP) #104: rows are matched to their Item by name, not by position. Frappe 16 wraps
	// the column header in a .list-row-container as well, so painting the n-th container with
	// the n-th item's colour put every colour one row too high, on items that have none.
	function apply_colors(listview) {
		if (!listview || !listview.data || !listview.$result) return;
		const colors = {};
		listview.data.forEach(function (doc) {
			colors[doc.name] = doc.custom_color ? hex_to_rgba(doc.custom_color, TINT_ALPHA) : '';
		});
		listview.$result.find('.list-row-container').each(function () {
			const $named = $(this).find('.list-row [data-name]').first();
			const name = $named.attr('data-name');
			this.style.background = name && colors[name] ? colors[name] : '';
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
