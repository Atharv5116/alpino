// Per-user saved list-view preferences (filters, sort, page size), keyed by user + route
// so shared warehouse machines with multiple logins don't bleed views into each other.
frappe.provide("alpinos.list_prefs");

alpinos.list_prefs = {
	_key(route) {
		return "alpinos_lv::" + (frappe.session.user || "Guest") + "::" + route;
	},

	save(route, state) {
		try {
			localStorage.setItem(this._key(route), JSON.stringify(state || {}));
		} catch (e) {
			// quota exceeded / private mode — losing prefs is acceptable
		}
	},

	load(route) {
		try {
			return JSON.parse(localStorage.getItem(this._key(route)) || "{}") || {};
		} catch (e) {
			return {};
		}
	},

	clear(route) {
		try {
			localStorage.removeItem(this._key(route));
		} catch (e) {
		}
	},
};
