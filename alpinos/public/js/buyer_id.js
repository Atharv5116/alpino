// Changes(HP) #64: "Gainsx Nutrition (OBM-2627-00175)" -- the Buyer ID (Buyer Master) after the
// buyer's name on the Pick List, Delivery Note and Sales Order screens. Display only: the
// boxes it fills are read-only and never saved back.
frappe.provide("alpinos.buyer_id");

alpinos.buyer_id._cache = {};

alpinos.buyer_id.label = function (name, buyer_id) {
	name = name || "";
	return buyer_id ? `${name} (${buyer_id})` : name;
};

// The Buyer ID of a Sales Order (cached per page load); resolves "" when there is none.
alpinos.buyer_id.of_order = function (sales_order) {
	if (!sales_order) return Promise.resolve("");
	const cache = alpinos.buyer_id._cache;
	if (cache[sales_order] === undefined) {
		cache[sales_order] = frappe.db
			.get_value("Sales Order", sales_order, "custom_offline_buyer_master")
			.then((r) => (r && r.message && r.message.custom_offline_buyer_master) || "")
			.catch(() => "");
	}
	return cache[sales_order];
};

// Fill a read-only input with "Name (Buyer ID)" once the order's Buyer ID is known.
alpinos.buyer_id.fill = function ($input, name, sales_order) {
	$input.val(name || "");
	alpinos.buyer_id.of_order(sales_order).then((id) => {
		if (id && $input.val() === (name || "")) $input.val(alpinos.buyer_id.label(name, id));
	});
};
