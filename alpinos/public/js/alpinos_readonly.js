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
