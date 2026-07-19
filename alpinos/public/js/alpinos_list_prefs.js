// Per-user saved list-view preferences for the alpinos list pages.
//
// Each user keeps their own view of every list page (filters, sort, page
// size) across sessions. State is stored in localStorage keyed by user +
// page route, so shared warehouse machines with multiple logins do not
// bleed views into each other.
frappe.provide("alpinos.list_prefs");

alpinos.list_prefs = {
	_key(route) {
		return "alpinos_lv::" + (frappe.session.user || "Guest") + "::" + route;
	},

	// state: plain JSON-serializable object ({filters, sort_by, sort_order,
	// page_length, ...} — each page decides its own shape).
	save(route, state) {
		try {
			localStorage.setItem(this._key(route), JSON.stringify(state || {}));
		} catch (e) {
			// Quota exceeded / private mode — losing prefs is acceptable.
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
			// ignore
		}
	},
};
