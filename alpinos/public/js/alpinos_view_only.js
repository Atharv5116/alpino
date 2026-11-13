// Changes(HP) #71: a page opened by someone who may only read the document (a Sales Officer
// on a Pick List / Delivery Note of their Buyer) shows it in view-only mode: every action is
// visibly disabled instead of failing with "No permission" when clicked. The server refuses
// the same actions anyway; this only makes the screen say so.
//
//   alpinos.view_only.apply(page, "Pick List", { keep: ["#btn-print-packing", "#btn-go-to-list"] })
frappe.provide("alpinos.view_only");

(function () {
	let style_added = false;
	function add_style() {
		if (style_added) return;
		style_added = true;
		$(`<style>
			.alp-view-only .btn:not(.alp-keep), .alp-view-only button:not(.alp-keep),
			.alp-view-only input, .alp-view-only select, .alp-view-only textarea {
				opacity: 0.45; pointer-events: none; filter: blur(0.3px);
			}
			.alp-view-only-banner { margin: 0 0 10px 0; padding: 6px 12px; border-radius: 6px; font-size: 12px;
				background: var(--subtle-fg, #f4f5f6); color: var(--text-muted, #6b7280); }
		</style>`).appendTo("head");
	}

	alpinos.view_only.applies = function (doctype) {
		return !frappe.model.can_write(doctype);
	};

	alpinos.view_only.apply = function (page, doctype, opts = {}) {
		if (!alpinos.view_only.applies(doctype)) return false;
		add_style();
		const $main = $(page.main);
		(opts.keep || []).forEach((sel) => $main.find(sel).addClass("alp-keep"));
		$main.addClass("alp-view-only");
		// the page header's own buttons (Submit, Cancel ...) too, except navigation / print
		page.clear_primary_action && page.clear_primary_action();
		$(page.wrapper)
			.find(".page-actions .btn")
			.each(function () {
				const text = ($(this).text() || "").trim().toLowerCase();
				if (!/print|download|list|back/.test(text)) $(this).prop("disabled", true).css("opacity", 0.45);
			});
		if (!$main.find(".alp-view-only-banner").length) {
			$main.prepend(
				`<div class="alp-view-only-banner">${__("View only: you can read this {0} but not change it.", [__(doctype)])}</div>`
			);
		}
		return true;
	};
})();
