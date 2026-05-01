frappe.pages["offline-buyer-catalog"].on_page_load = function (wrapper) {
	const $wrapper = $(wrapper);
	$wrapper.html(
		`<div class="offline-buyer-catalog-page" style="padding: 1rem;">
			<p class="text-muted">${__("Offline Buyer Items page loaded. Extend this script for list/detail UI and API calls.")}</p>
		</div>`
	);
};
