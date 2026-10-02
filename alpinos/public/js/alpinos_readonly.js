/**
 * Close a section for editing without dimming it.
 *
 * The Purchase screens used to mark a closed card with `opacity:.55; pointer-events:none`.
 * That reads as a veil over the whole document -- the values go grey and hard to read at
 * exactly the moment the document stops being a form and becomes a record people need to
 * READ. A submitted order is not faded paper; it is a finished document.
 *
 * So the card is left at full contrast and its fields are switched off instead:
 *
 *   1. Every input, select, textarea and button in the card is `disabled`. That is the
 *      real lock -- it stops the mouse AND the keyboard, which `pointer-events:none`
 *      never did (Tab still reached a closed section and typing still changed it, and
 *      the save was then refused by the server with a permission error that reads like
 *      a crash).
 *   2. The `alpinos-readonly` class, which the stylesheet uses to undo the browser's
 *      grey-out on a disabled field and to hide the Add Row / Remove buttons.
 *
 * Deliberately NOT done here: flipping `df.read_only` and calling `control.refresh()` on
 * each control. That is how a FORM control locks and it renders the nicer plain-text
 * value -- but on a page control built by `make_control` there is no frm behind it, so
 * refresh() redraws the display area from a value the control may not hold yet. Doing it
 * while a document was still loading blanked the fields and left the load unfinished,
 * which showed up as an existing order that never opened. The disabled-field treatment
 * below needs no redraw, so it cannot race the load.
 */

/**
 * @param {jQuery} $cards   the section(s) to close
 * @param {boolean} locked
 */
window.alpinos_set_readonly = function ($cards, locked) {
	if (!$cards || !$cards.length) return;
	locked = !!locked;

	$cards.toggleClass('alpinos-readonly', locked);

	$cards.find('input, select, textarea, button').each(function () {
		const $i = $(this);
		if (locked) {
			// Remembered the first time, so unlocking can never enable a field that was
			// already disabled for its own reason -- a server-derived total, an ID.
			if ($i.attr('data-alpinos-prev') === undefined) {
				$i.attr('data-alpinos-prev', $i.prop('disabled') ? '1' : '0');
			}
			$i.prop('disabled', true);
		} else if ($i.attr('data-alpinos-prev') !== undefined) {
			$i.prop('disabled', $i.attr('data-alpinos-prev') === '1');
			$i.removeAttr('data-alpinos-prev');
		}
	});
};

/**
 * May the current user edit this document at all? (PO-42)
 *
 * A saved document needs write on its doctype, a new one needs create. The screens used
 * to lock only on docstatus and workflow stage, so a user with read-only access saw live
 * fields and a Save button, and the server then refused the save. The server still
 * decides; this only stops the screen offering an edit that cannot be saved.
 *
 * @param {string} doctype
 * @param {object} [doc]   the loaded document; blank or unsaved means "new"
 */
window.alpinos_can_write = function (doctype, doc) {
	const is_new = !doc || !doc.name || doc.__islocal;
	return is_new ? frappe.model.can_create(doctype) : frappe.model.can_write(doctype);
};

/**
 * A "List View" button that goes back to the screen's list page.
 *
 * Called right after an action bar is emptied, so it survives every re-render of the
 * bar (each screen rebuilds its buttons whenever the document or its status changes)
 * and every early return in the code that adds the other buttons.
 *
 * @param {jQuery} $bar   the action bar, already emptied
 * @param {string} route  the list page route, e.g. 'purchase_qc_list'
 */
window.alpinos_list_view_button = function ($bar, route) {
	if (!$bar || !$bar.length || !route) return;
	$(`<button class="btn btn-sm btn-default alp-list-view" style="margin-left:8px;">
		<i class="fa fa-list" style="margin-right:4px;"></i>${frappe.utils.escape_html(__('List View'))}</button>`)
		.on('click', () => frappe.set_route(route))
		.appendTo($bar);
};

/**
 * A "PDF" button for a list row: downloads that document's PDF straight away, in the
 * given print format, with no print preview in between.
 *
 * The click is taken in the CAPTURE phase so it runs before the list's own row handler,
 * which would otherwise open the document as well.
 *
 * @param {string} doctype
 * @param {string} name
 * @param {string} [format]  print format; blank means the doctype's Standard format
 */
window.alpinos_pdf_button = function (doctype, name, format) {
	const esc = frappe.utils.escape_html;
	return `<button type="button" class="btn btn-xs btn-default alp-pdf-btn" title="${esc(__('Download PDF'))}"
		data-doctype="${esc(doctype)}" data-name="${esc(name)}" data-format="${esc(format || '')}">
		<i class="fa fa-file-pdf-o" style="margin-right:3px;"></i>${esc(__('PDF'))}</button>`;
};

window.alpinos_download_pdf = function (doctype, name, format) {
	const url = '/api/method/frappe.utils.print_format.download_pdf'
		+ '?doctype=' + encodeURIComponent(doctype)
		+ '&name=' + encodeURIComponent(name)
		+ '&format=' + encodeURIComponent(format || 'Standard')
		+ '&no_letterhead=0';
	// Frappe sends the PDF "inline", which some browsers open in a viewer tab instead of
	// saving. Fetching it and saving the blob makes it a real download, named after the
	// document, and the list stays where it is.
	frappe.show_alert({ message: __('Preparing PDF of {0}...', [name]), indicator: 'blue' }, 3);
	fetch(url, { credentials: 'same-origin' })
		.then((r) => {
			const type = r.headers.get('content-type') || '';
			if (!r.ok || type.indexOf('pdf') === -1) throw new Error(r.status + ' ' + type);
			return r.blob();
		})
		.then((blob) => {
			const href = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = href;
			a.download = String(name).replace(/[\\/:*?"<>|]+/g, '-') + '.pdf';
			document.body.appendChild(a);
			a.click();
			a.remove();
			setTimeout(() => URL.revokeObjectURL(href), 10000);
		})
		.catch(() => {
			frappe.msgprint({
				title: __('PDF Not Available'),
				indicator: 'red',
				message: __('The PDF of {0} could not be generated. Please try again, or open the document and print it.', [name]),
			});
		});
};

if (!window.__alpinos_pdf_bound) {
	window.__alpinos_pdf_bound = true;
	document.addEventListener('click', (e) => {
		const btn = e.target && e.target.closest && e.target.closest('.alp-pdf-btn');
		if (!btn) return;
		e.preventDefault();
		e.stopPropagation();
		alpinos_download_pdf(btn.dataset.doctype, btn.dataset.name, btn.dataset.format);
	}, true);
}

/**
 * No PDF button in Frappe's print view for a Purchase Order.
 *
 * The print page is one page reused for every doctype and it adds its PDF button once,
 * so the button is hidden whenever the page is showing a Purchase Order and shown again
 * for anything else. Full Page and the browser's own Print are unaffected.
 */
(function () {
	const HIDE_PDF_FOR = ['Purchase Order'];
	const toggle = () => {
		const route = frappe.get_route() || [];
		if (route[0] !== 'print') return;
		const hide = HIDE_PDF_FOR.includes(route[1]);
		$('#page-print').find('.page-actions button, .page-head button').filter(function () {
			return $(this).text().trim() === __('PDF');
		}).toggle(!hide);
		// Also re-check whenever the print view switches document without a route change.
		const PV = frappe.ui.form && frappe.ui.form.PrintView;
		if (PV && !PV.prototype.__alpinos_pdf_hide) {
			const show = PV.prototype.show;
			PV.prototype.show = function () {
				const out = show.apply(this, arguments);
				setTimeout(toggle, 50);
				return out;
			};
			PV.prototype.__alpinos_pdf_hide = true;
		}
	};
	$(document).on('app_ready', () => {
		frappe.router && frappe.router.on && frappe.router.on('change', () => {
			setTimeout(toggle, 300);
			setTimeout(toggle, 1200);
		});
		setTimeout(toggle, 1200);
	});
})();
