// Frappe v16 moved the desk from /app to /desk. Its router handles a link click itself only
// when the path starts with /desk; an /app/... href (the alpinos pages carry many) still
// works through the server redirect, but reloads the whole desk on every click.
// This rewrites such an href to /desk/... in the capture phase, before the router's own
// handler reads it. On v15, where /app IS the desk route, it does nothing.
(function () {
	function desk_is_slash_desk() {
		return (
			frappe.router &&
			frappe.router.is_app_route &&
			!frappe.router.is_app_route("/app/x") &&
			frappe.router.is_app_route("/desk/x")
		);
	}

	document.addEventListener(
		"click",
		function (e) {
			const a = e.target && e.target.closest && e.target.closest("a[href]");
			if (!a || a.host !== window.location.host) return;
			if (!/^\/app(\/|$)/.test(a.pathname) || !desk_is_slash_desk()) return;
			a.pathname = a.pathname.replace(/^\/app/, "/desk");
		},
		true
	);
})();
