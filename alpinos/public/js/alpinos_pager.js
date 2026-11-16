// Changes(HP) #111: page navigation for the Alpinos list pages (Pick List, Delivery Note).
//
//   alpinos.pager.render($container, { start, page_length, total }, (new_start) => {...})
//
// Draws "Showing 21–40 of 386 records | Page 2 of 20", First / Previous, page numbers
// (1 2 3 ... 20 around the current page), Next / Last, and a Go to page box. The page asks
// the server for that page; searching, filtering and sorting are done by the server over
// every record, and a page resets itself to page 1 when they change.
frappe.provide("alpinos.pager");

(function () {
	let style_added = false;
	function add_style() {
		if (style_added) return;
		style_added = true;
		$(`<style>
			.alp-pager { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; }
			.alp-pager-info { color: var(--text-muted, #6b7280); font-size: 12px; }
			.alp-pager-nav { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
			.alp-pager-nav .btn { min-width: 32px; }
			.alp-pager-nav .btn.active { background: var(--primary, #2490ef); color: #fff; border-color: transparent; }
			.alp-pager-gap { padding: 0 4px; color: var(--text-muted, #6b7280); }
			.alp-pager-goto { display: flex; align-items: center; gap: 4px; margin-left: 8px; font-size: 12px; }
			.alp-pager-goto input { width: 64px; height: 28px; }
		</style>`).appendTo("head");
	}

	// page numbers to show: always 1 and the last, the current one and two either side
	function pages_to_show(current, count) {
		const set = new Set([1, count]);
		for (let p = current - 2; p <= current + 2; p++) if (p >= 1 && p <= count) set.add(p);
		return Array.from(set).sort((a, b) => a - b);
	}

	alpinos.pager.render = function ($container, meta, go) {
		add_style();
		const total = cint(meta.total);
		const size = cint(meta.page_length) || 20;
		const start = cint(meta.start);
		const count = Math.max(1, Math.ceil(total / size));
		const current = Math.min(count, Math.floor(start / size) + 1);
		const shown = total ? Math.min(size, total - start) : 0;
		const info = total
			? __("Showing {0}–{1} of {2} records | Page {3} of {4}", [start + 1, start + shown, total, current, count])
			: __("No records");

		const $pager = $(`<div class="alp-pager">
			<div class="alp-pager-info"></div>
			<div class="alp-pager-nav"></div>
		</div>`);
		$pager.find(".alp-pager-info").text(info);
		const $nav = $pager.find(".alp-pager-nav");
		const to_page = (p) => go(Math.max(0, (Math.min(count, Math.max(1, p)) - 1) * size));
		const btn = (label, page, disabled, active, title) =>
			$(`<button type="button" class="btn btn-default btn-xs"></button>`)
				.text(label)
				.attr("title", title || "")
				.prop("disabled", !!disabled)
				.toggleClass("active", !!active)
				.on("click", () => to_page(page));

		$nav.append(btn("«", 1, current <= 1, false, __("First page")));
		$nav.append(btn("‹", current - 1, current <= 1, false, __("Previous page")));
		let last = 0;
		pages_to_show(current, count).forEach((p) => {
			if (p - last > 1) $nav.append(`<span class="alp-pager-gap">…</span>`);
			$nav.append(btn(String(p), p, false, p === current));
			last = p;
		});
		$nav.append(btn("›", current + 1, current >= count, false, __("Next page")));
		$nav.append(btn("»", count, current >= count, false, __("Last page")));

		const $goto = $(`<span class="alp-pager-goto">${__("Go to page")}
			<input type="number" min="1" class="form-control input-xs">
			<button type="button" class="btn btn-default btn-xs">${__("Go")}</button></span>`);
		const $input = $goto.find("input").attr("max", count);
		const jump = () => {
			const p = cint($input.val());
			if (p >= 1 && p <= count) to_page(p);
			else frappe.show_alert({ message: __("Enter a page between 1 and {0}.", [count]), indicator: "orange" });
		};
		$goto.find("button").on("click", jump);
		$input.on("keydown", (e) => e.which === 13 && jump());
		$nav.append($goto);

		$container.empty().append($pager);
	};
})();
