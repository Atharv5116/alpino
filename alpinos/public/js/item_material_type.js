// Item form: the Material Type field is gone. Production reads an item's type from its Item
// Group (Raw Material / Packaging Material / Additive / Finished Goods), so the sections that
// only make sense for one type follow the group here.
//
//   Finished Goods      -> Filling section (Target SKU Name, Filling Categories, Pack Size)
//   Packaging Material  -> Material Category (shown for packaging; optional)

(function () {
	const FG_FIELDS = [
		'custom_filling_section', 'custom_target_sku_name',
		'custom_allowed_filling_categories', 'custom_pack_size_kg',
	];

	function apply(frm, kind) {
		const fg = kind === 'FG';
		const pm = kind === 'PM';
		FG_FIELDS.forEach((f) => frm.toggle_display(f, fg));
		frm.toggle_display('custom_material_category', pm);
		frm.toggle_reqd('custom_material_category', 0);
	}

	function refresh_type(frm) {
		if (!frm.doc.item_group) {
			apply(frm, '');
			return;
		}
		frappe.call({
			method: 'alpinos.production.material_type.get_group_type',
			args: { item_group: frm.doc.item_group },
			callback(r) { apply(frm, (r && r.message) || ''); },
		});
	}

	frappe.ui.form.on('Item', {
		refresh: refresh_type,
		item_group: refresh_type,
	});
})();
