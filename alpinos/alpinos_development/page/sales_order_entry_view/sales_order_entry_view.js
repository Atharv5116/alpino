frappe.pages['sales-order-entry-view'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Alpino Sales Order View'),
		single_column: true,
	});
	page.main.html(frappe.render_template('sales_order_entry_view'));
	const view = new SalesOrderEntryView(page);
	wrapper.so_entry_view = view;
	wrapper.on_page_show = function () {
		if (wrapper.so_entry_view) {
			wrapper.so_entry_view.sync_from_route();
		}
	};
};

class SalesOrderEntryView {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this._so_name = '';
		this.setup_toolbar();
		this.setup();
	}

	setup_toolbar() {
		// Idempotent: if this page instance is ever re-created, clear the existing
		// buttons/menu first so the action bar never accumulates duplicates.
		this.page.clear_inner_toolbar && this.page.clear_inner_toolbar();
		this.page.clear_menu && this.page.clear_menu();
		// Utility actions live in the "⋯" menu to keep the action bar uncluttered.
		this.page.add_menu_item(__('Print'), () => this.open_default_print_preview());
		this.page.add_menu_item(__('Download PDF'), () => this.download_default_print_pdf());
		this.page.add_menu_item(__('Back to Sales Order List'), () =>
			frappe.set_route('sales-order-entry-list')
		);
		// Always-visible Download PDF button (every Sales Order, any status).
		this.page.add_inner_button(__('Download PDF'), () => this.download_default_print_pdf(), __('PDF'));
		// Fetch the customer PO PDF (named by 'PO No for PDF') from the folder
		// set in Alpino General Settings and attach it to the order.
		this.page.add_inner_button(__('Fetch PO PDF'), () => {
			const me = this;
			frappe.call({
				method: 'alpinos.po_pdf.fetch_po_pdf',
				args: { sales_order: me._so_name },
				freeze: true,
				freeze_message: __('Fetching PO PDF...'),
				callback: (r) => {
					if (r.message && r.message.file_url) {
						frappe.show_alert({ message: __('PO PDF attached: {0}', [r.message.file_name]), indicator: 'green' }, 5);
					}
				}
			});
		}, __('PDF'));
		// Edit re-opens the entry form on the SAME draft (shown for drafts only).
		// E-com orders edit on the e-com entry page; offline on the offline one.
		this.btn_edit_so = this.page.add_inner_button(__('Edit Order'), () => {
			if (this._channel === 'E-com') {
				frappe.route_options = { edit_eso: this._so_name };
				frappe.set_route('ecom-sales-order-entry');
			} else {
				frappe.route_options = { edit_so: this._so_name };
				frappe.set_route('sales-order-entry');
			}
		}, __('Order'));
		if (this.btn_edit_so) this.btn_edit_so.hide();
		// Duplicate prefills the entry form with this order's data; saving
		// creates a NEW order (fresh workflow state, status and Created By).
		this.page.add_inner_button(__('Duplicate'), () => {
			if (this._channel === 'E-com') {
				frappe.route_options = { duplicate_eso: this._so_name };
				frappe.set_route('ecom-sales-order-entry');
			} else {
				frappe.route_options = { duplicate_so: this._so_name };
				frappe.set_route('sales-order-entry');
			}
		}, __('Order'));
		// Cancel: submitted orders only, and only for roles with cancel rights
		// (server re-checks). The guard blocks with the linked Pick List /
		// Delivery Note ID while one is still active.
		this.btn_cancel_so = this.page.add_inner_button(__('Cancel Order'), () => {
			const me = this;
			frappe.confirm(__('Cancel Sales Order {0}?', [me._so_name]), () => {
				frappe.call({
					method: 'alpinos.workflow_engine.cancel_document',
					args: { doctype: 'Sales Order', name: me._so_name },
					freeze: true,
					freeze_message: __('Cancelling...'),
					callback: (r) => {
						if (r.exc) return;
						frappe.show_alert({ message: __('Sales Order cancelled'), indicator: 'red' });
						me.load_order(me._so_name);
					}
				});
			});
		}, __('Order'));
		if (this.btn_cancel_so) this.btn_cancel_so.hide();
		// The main "next stage" action is set as the page primary action by
		// update_actions(). This is the only stage-secondary inline button.
		this.btn_future_dispatch = this.page.add_inner_button(
			__('Mark as Future Dispatch'),
			() => this.do_future_dispatch(),
			__('Order')
		);
		if (this.btn_future_dispatch) this.btn_future_dispatch.hide();
		// Forced Close — permanently close the order at the qty already dispatched.
		this.btn_force_close = this.page.add_inner_button(
			__('Force Close Order'),
			() => this.do_force_close(),
			__('Order')
		);
		if (this.btn_force_close) this.btn_force_close.hide();
	}

	_has_any_role(roles) {
		const mine = frappe.user_roles || [];
		return roles.some((r) => mine.includes(r));
	}

	/** One coherent action bar: a prominent primary "next stage" button + at
	 * most one contextual secondary button + the status badge. Folds in the
	 * Pick List create/continue logic so nothing is scattered. */
	update_actions() {
		this.page.clear_primary_action();
		if (this.btn_future_dispatch) this.btn_future_dispatch.hide();
		this.page.remove_inner_button(__('Create'), __('Pick List'));
		this.page.remove_inner_button(__('Edit'), __('Pick List'));
		if (!this._so_name) return;
		const me = this;
		const plStatus = new Promise((resolve) => {
			frappe.call({
				method: 'alpinos.sales_order_api.get_so_pick_list_status',
				args: { sales_order: this._so_name },
				callback: (r) => resolve(r.message || {}),
			});
		});
		Promise.all([
			frappe.db.get_value('Sales Order', this._so_name, ['custom_workflow_status', 'docstatus']),
			plStatus,
		]).then(([sv, pl]) => {
			const status = (sv && sv.message && sv.message.custom_workflow_status) || '';
			const docstatus = cint(sv && sv.message && sv.message.docstatus);
			// Edit only while the order is still a draft (server enforces too).
			if (me.btn_edit_so) {
				if (docstatus === 0 && status !== 'Cancelled') me.btn_edit_so.show();
				else me.btn_edit_so.hide();
			}
			// Cancel: submitted only + role must have cancel rights (server re-checks).
			if (me.btn_cancel_so) {
				const can_cancel = frappe.model.can_cancel && frappe.model.can_cancel('Sales Order');
				if (docstatus === 1 && status !== 'Cancelled' && can_cancel) me.btn_cancel_so.show();
				else me.btn_cancel_so.hide();
			}
			// Status badge next to the title.
			const colorMap = {
				Draft: 'gray',
				'Warehouse Approval Pending': 'orange',
				'Future Dispatch': 'yellow',
				"Today's Dispatch": 'purple',
				'Warehouse Approved': 'blue',
				'Picking In Progress': 'blue',
				'Submission Pending': 'orange',
				'Ready For Dispatch': 'blue',
				'Delivery Note Created': 'blue',
				Dispatched: 'green',
				'Partial Ready For Dispatch': 'blue',
				'Partial Delivery Note Created': 'blue',
				'Partial Dispatched': 'purple',
				'Forced Ready For Dispatch': 'orange',
				'Forced Delivery Note Created': 'orange',
				'Forced Dispatched': 'red',
				Completed: 'green',
				'Forced Completed': 'red',
				Cancelled: 'red',
			};
			if (status && me.page.set_indicator) {
				me.page.set_indicator(status, colorMap[status] || 'gray');
			} else if (me.page.clear_indicator) {
				me.page.clear_indicator();
			}

			const isWarehouse = me._has_any_role(['Warehouse Admin', 'Warehouse Manager', 'System Manager']);
			const isSales = me._has_any_role(['Sales Admin', 'Sales Manager', 'System Manager']);

			// Force Close available to warehouse while an order has been picked but
			// isn't fully dispatched, isn't already force-closed, and isn't terminal.
			const terminal = ['Completed', 'Forced Completed', 'Cancelled'].includes(status);
			if (me.btn_force_close) {
				const can_force = isWarehouse && docstatus === 1 && !terminal &&
					!cint(pl.force_closed) && cint(pl.has_pick_list) && cint(pl.has_remaining_qty);
				if (can_force) me.btn_force_close.show();
				else me.btn_force_close.hide();
			}

			// PRIMARY action = the clear "next stage" step for this stage + role.
			if (status === 'Draft' && isSales) {
				me.page.set_primary_action(__('Send for Warehouse Approval'), () => me.do_submit_order());
			} else if (status === 'Warehouse Approval Pending' && isWarehouse) {
				// Warehouse must approve before the order enters the dispatch queue.
				me.page.set_primary_action(__('Approve Order'), () => me.do_approve());
			} else if (
				['Future Dispatch', "Today's Dispatch", 'Warehouse Approved'].includes(status) &&
				isWarehouse
			) {
				if (pl.has_draft) {
					me.page.set_primary_action(__('Continue Pick List'), () =>
						frappe.set_route('pick_list_entry', pl.draft_name)
					);
				} else if (!pl.has_pick_list) {
					me.page.set_primary_action(__('Create Pick List'), () => {
						frappe.route_options = { so_name: me._so_name };
						frappe.set_route('pick_list_entry', 'New Pick List');
					});
				}
			} else if (status === 'Dispatched' && isSales) {
				me.page.set_primary_action(__('Mark Delivered'), () => me.do_mark_delivered());
			} else if (status === 'Forced Dispatched' && isSales) {
				me.page.set_primary_action(__('Confirm Forced Delivery'), () => me.do_confirm_forced());
			} else if (
				['Partial Dispatched', 'Partial Delivery Note Created', 'Partial Ready For Dispatch'].includes(status) &&
				isWarehouse
			) {
				// Partial chain: continue an in-progress round, or start a Pick List
				// for the outstanding qty (pre-filled with remaining only).
				if (pl.has_draft) {
					me.page.set_primary_action(__('Continue Pick List'), () =>
						frappe.set_route('pick_list_entry', pl.draft_name)
					);
				} else if (!cint(pl.force_closed) && cint(pl.partial_order_allowed) && cint(pl.has_remaining_qty)) {
					me.page.set_primary_action(__('Create PL for Remaining Qty'), () => {
						frappe.route_options = { so_name: me._so_name, remaining_only: 1 };
						frappe.set_route('pick_list_entry', 'New Pick List');
					});
				}
			} else if (pl.has_draft && isWarehouse) {
				// Mid-flow (Warehouse Approved / Picking) — jump back into the Pick List.
				me.page.set_primary_action(__('Continue Pick List'), () =>
					frappe.set_route('pick_list_entry', pl.draft_name)
				);
			}

			// SECONDARY: park / update the dispatch date (warehouse, early stages).
			if (
				me.btn_future_dispatch &&
				isWarehouse &&
				['Warehouse Approval Pending', 'Future Dispatch', "Today's Dispatch"].includes(status)
			) {
				me.btn_future_dispatch.text(
					['Future Dispatch', "Today's Dispatch"].includes(status)
						? __('Update Dispatch Date')
						: __('Mark as Future Dispatch')
				);
				me.btn_future_dispatch.show();
			}
		});
	}

	do_submit_order() {
		if (!this._so_name) return;
		const me = this;
		frappe.confirm(
			__('Submit this Sales Order for warehouse approval? It becomes read-only after this.'),
			() => {
				frappe.call({
					method: 'alpinos.workflow_engine.submit_sales_order',
					args: { sales_order: me._so_name },
					freeze: true,
					freeze_message: __('Submitting...'),
					callback(r) {
						if (r.exc) return;
						frappe.show_alert({ message: __('Sent for Warehouse Approval'), indicator: 'green' });
						me.load_order(me._so_name);
					},
				});
			}
		);
	}

	do_future_dispatch() {
		if (!this._so_name) return;
		const me = this;
		// Prefill the date: the existing expected date if already parked, else
		// fall back to the Sales Order's own dispatch date.
		frappe.db
			.get_value('Sales Order', this._so_name, [
				'custom_expected_dispatch_date',
				'custom_dispatch_date',
			])
			.then((r) => {
				const m = (r && r.message) || {};
				const default_date = m.custom_expected_dispatch_date || m.custom_dispatch_date || '';
				frappe.prompt(
					[
						{
							fieldname: 'expected_date',
							fieldtype: 'Date',
							label: __('Expected Dispatch Date'),
							reqd: 1,
							default: default_date,
						},
					],
					(values) => {
						frappe.call({
							method: 'alpinos.workflow_engine.mark_future_dispatch',
							args: { sales_order: me._so_name, expected_date: values.expected_date },
							freeze: true,
							callback(rr) {
								if (rr.exc) return;
								frappe.show_alert({ message: __('Marked as Future Dispatch'), indicator: 'orange' });
								me.load_order(me._so_name);
							},
						});
					},
					__('Future Dispatch'),
					__('Confirm')
				);
			});
	}

	do_approve() {
		if (!this._so_name) return;
		const me = this;
		frappe.confirm(__('Approve this order and move it into the dispatch queue?'), () => {
			frappe.call({
				method: 'alpinos.workflow_engine.approve_sales_order',
				args: { sales_order: me._so_name },
				freeze: true,
				freeze_message: __('Approving...'),
				callback(r) {
					if (r.exc) return;
					const st = (r.message && r.message.status) || '';
					frappe.show_alert({ message: __('Order approved → {0}', [st]), indicator: 'green' });
					me.load_order(me._so_name);
				},
			});
		});
	}

	do_mark_delivered() {
		if (!this._so_name) return;
		const me = this;
		frappe.confirm(__('Confirm delivery received by customer and mark this order Completed?'), () => {
			frappe.call({
				method: 'alpinos.workflow_engine.mark_delivered',
				args: { sales_order: me._so_name },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					frappe.show_alert({ message: __('Order marked Completed'), indicator: 'green' });
					me.load_order(me._so_name);
				},
			});
		});
	}

	do_force_close() {
		if (!this._so_name) return;
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Force Close Order'),
			fields: [
				{
					fieldtype: 'HTML',
					options: `<p class="text-danger"><b>${__('Warning:')}</b> ${__(
						'This permanently closes the order at the qty already dispatched. The remaining qty is abandoned and no further Pick List / Delivery Note can be created. This cannot be undone.'
					)}</p>`,
				},
				{
					fieldtype: 'Select',
					fieldname: 'reason',
					label: __('Reason for Force Close'),
					options: ['Damage', 'Stock Shortage', 'Expiry', 'Others'].join('\n'),
					reqd: 1,
				},
			],
			primary_action_label: __('Force Close'),
			primary_action(values) {
				frappe.call({
					method: 'alpinos.forced_close.force_close_sales_order',
					args: { sales_order: me._so_name, reason: values.reason },
					freeze: true,
					freeze_message: __('Force closing...'),
					callback(r) {
						if (r.exc) return;
						d.hide();
						frappe.show_alert({ message: __('Order Force Closed'), indicator: 'red' });
						me.load_order(me._so_name);
					},
				});
			},
		});
		d.show();
	}

	do_confirm_forced() {
		if (!this._so_name) return;
		const me = this;
		frappe.confirm(__('Confirm delivery and mark this force-closed order as Forced Completed?'), () => {
			frappe.call({
				method: 'alpinos.forced_close.confirm_forced_completion',
				args: { sales_order: me._so_name },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					frappe.show_alert({ message: __('Order marked Forced Completed'), indicator: 'green' });
					me.load_order(me._so_name);
				},
			});
		});
	}

	_ensure_loaded_name() {
		if (!this._so_name) {
			frappe.msgprint(__('Open a Sales Order first.'));
			return false;
		}
		if (!frappe.model.can_print('Sales Order')) {
			frappe.msgprint(__('You do not have permission to print Sales Orders.'));
			return false;
		}
		return true;
	}

	/** Desk print preview: uses DocType default print format (same as Form → Print). */
	open_default_print_preview() {
		if (!this._ensure_loaded_name()) return;
		frappe.set_route('print', 'Sales Order', this._so_name);
	}

	/** PDF download using the default print format for Sales Order. */
	download_default_print_pdf() {
		if (!this._ensure_loaded_name()) return;

		frappe.model.with_doctype('Sales Order', () => {
			const meta = frappe.get_meta('Sales Order');
			const format_name = (meta.default_print_format || '').trim() || 'Standard';

			const open_wk = () => {
				const url =
					'/api/method/frappe.utils.print_format.download_pdf?' +
					'doctype=' +
					encodeURIComponent('Sales Order') +
					'&name=' +
					encodeURIComponent(this._so_name) +
					'&format=' +
					encodeURIComponent(format_name) +
					'&no_letterhead=0';
				const w = window.open(frappe.urllib.get_full_url(url));
				if (!w) frappe.msgprint(__('Please allow pop-ups to download the PDF.'));
			};

			frappe.db.get_value('Print Format', format_name, 'print_format_builder_beta').then((r) => {
				const beta = r.message && r.message.print_format_builder_beta;
				if (cint(beta)) {
					const params = new URLSearchParams({
						doctype: 'Sales Order',
						name: this._so_name,
						print_format: format_name,
						letterhead: '',
					});
					const w = window.open(
						frappe.urllib.get_full_url(
							'/api/method/frappe.utils.weasyprint.download_pdf?' + params.toString()
						)
					);
					if (!w) frappe.msgprint(__('Please allow pop-ups to download the PDF.'));
				} else {
					open_wk();
				}
			});
		});
	}

	setup() {
		const so_name = this._resolve_sales_order_name();
		if (!so_name) {
			this._ask_for_order();
			return;
		}
		this.load_order(so_name);
	}

	/** Prefer URL path `/app/sales-order-entry-view/<name>` so refresh and router do not drop context. */
	_resolve_sales_order_name() {
		const ro = frappe.route_options || {};
		let so_name = ro.sales_order || ro.name || '';
		if (!so_name && frappe.urllib && frappe.urllib.get_arg) {
			so_name = frappe.urllib.get_arg('sales_order') || '';
		}
		const r = frappe.get_route() || [];
		const slug = 'sales-order-entry-view';
		if (!so_name && r.length >= 2 && String(r[0]).toLowerCase() === slug) {
			so_name = r[1] || '';
		}
		return String(so_name || '').trim();
	}

	sync_from_route() {
		// Always re-fetch on page show — returning here after an edit lands on the
		// SAME order name, so a "skip if unchanged" guard would leave stale data on
		// screen until a manual browser refresh.
		const so_name = this._resolve_sales_order_name();
		if (so_name) {
			// First open freezes (reassuring); later re-shows refresh silently so
			// navigating back doesn't flash a loading overlay each time.
			this.load_order(so_name, { silent: !!this._loaded_once });
			this._loaded_once = true;
		}
	}

	_ask_for_order() {
		frappe.prompt(
			[
				{
					fieldname: 'sales_order',
					label: __('Sales Order'),
					fieldtype: 'Link',
					options: 'Sales Order',
					reqd: 1,
				},
			],
			(v) => this.load_order(v.sales_order),
			__('Open Sales Order View'),
			__('Open')
		);
	}

	load_order(name, opts = {}) {
		this._so_name = name;
		frappe.call({
			method: 'alpinos.sales_order_api.get_sales_order_entry_view_payload',
			args: { sales_order: name },
			freeze: !opts.silent,
			freeze_message: __('Loading Sales Order...'),
			callback: (r) => {
				if (r.exc) {
					frappe.msgprint({ title: __('Error'), indicator: 'red', message: r.exc });
					return;
				}
				if (!r.message) {
					frappe.msgprint(__('Could not load Sales Order data.'));
					return;
				}
				this.page.set_title(__('Alpino Sales Order View — {0}', [name]));
				// Channel drives where Edit/Duplicate route (offline vs e-com entry).
				this._channel = r.message.channel || '';
				this.render(r.message);
			},
		});
	}

	_has(parent, key) {
		return parent && Object.prototype.hasOwnProperty.call(parent, key);
	}

	_esc(s) {
		return frappe.utils.escape_html(s == null ? '' : String(s));
	}

	/** Decode HTML entities (e.g. `&amp;` → `&`) for plain Select / Data fields. */
	_plain_text(s) {
		if (s == null || s === '') return '';
		const t = document.createElement('textarea');
		t.innerHTML = String(s);
		return t.value;
	}

	/** Turn address HTML from ERPNext into readable multiline plain text. */
	_address_plain(html) {
		if (html == null || html === '') return '';
		let s = String(html)
			.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
			.replace(/<\/?(p|div|li|tr|table|tbody|thead|h[1-6])[^>]*>/gi, '\n')
			.replace(/<br\s*\/?>/gi, '\n');
		const el = document.createElement('div');
		el.innerHTML = s;
		return (el.textContent || '')
			.replace(/\r\n/g, '\n')
			.replace(/[ \t]+\n/g, '\n')
			.replace(/\n{3,}/g, '\n\n')
			.trim();
	}

	_fmt_date(parent, key) {
		if (!this._has(parent, key)) return '—';
		const v = parent[key];
		if (!v) return '—';
		try {
			return frappe.datetime.str_to_user(v);
		} catch (e) {
			return this._esc(v);
		}
	}

	_fmt_num(parent, key, as_currency) {
		if (!this._has(parent, key)) return '—';
		const v = parent[key];
		if (v === '' || v === null || v === undefined) return '—';
		const n = flt(v);
		if (as_currency) {
			const cur = parent.currency || frappe.boot?.sysdefaults?.currency;
			return format_currency(n, cur);
		}
		return String(n);
	}

	_set_kv_row(parent, key, $td) {
		if (!this._has(parent, key)) {
			$td.closest('tr').hide();
			return;
		}
		$td.closest('tr').show();
	}

	render(payload) {
		const p = payload.parent || {};
		const w = this.wrapper;
		const currency = p.currency || frappe.boot?.sysdefaults?.currency || '';

		this.update_actions();

		// Customer block — order matches template
		w.find('.v-customer-name').text(
			this._has(p, 'customer_name') ? this._plain_text(p.customer_name) : '—'
		);
		w.find('.v-order-type').text(this._has(p, 'order_type') ? this._plain_text(p.order_type) : '—');
		// E-com orders store billing/shipping as free text (custom_*_address_text),
		// not as ERPNext Address records — prefer that so the entered/fetched
		// address shows instead of the customer's auto-linked default (or blank).
		const billing_txt = (this._has(p, 'custom_billing_address_text') && p.custom_billing_address_text)
			? p.custom_billing_address_text
			: (this._has(p, 'address_display') ? this._address_plain(p.address_display) : '—');
		const shipping_txt = (this._has(p, 'custom_shipping_address_text') && p.custom_shipping_address_text)
			? p.custom_shipping_address_text
			: (this._has(p, 'shipping_address') ? this._address_plain(p.shipping_address) : '—');
		w.find('.v-billing').text(billing_txt);
		w.find('.v-shipping').text(shipping_txt);
		w.find('.v-date').text(this._fmt_date(p, 'transaction_date'));
		w.find('.v-po-no').text(this._has(p, 'po_no') ? this._plain_text(p.po_no) : '—');
		w.find('.v-tax-id').text(this._has(p, 'tax_id') ? this._plain_text(p.tax_id) : '—');
		w.find('.v-dispatch-date').text(this._fmt_date(p, 'custom_dispatch_date'));
		w.find('.v-delivery-date').text(this._fmt_date(p, 'delivery_date'));
		w.find('.v-created-by').text(this._plain_text(p.owner_full_name || p.owner || '—'));
		w.find('.v-created-on').text(
			this._has(p, 'creation') && p.creation ? frappe.datetime.str_to_user(p.creation) : '—'
		);

		// E-com order flags (carried from Buyer Master) — surface what was stored.
		if ((this._channel || '') === 'E-com') {
			const yn = (v) => (cint(v) ? 'Yes' : 'No');
			// One span per flag (styled via .v-ecom-flag in the page style block) so
			// each "Label: Yes/No" pair wraps as a unit on narrow screens instead of
			// one long dot-separated string breaking mid-label. Static labels +
			// Yes/No values only — nothing user-supplied is interpolated.
			const flag = (label, v) => `<span class="v-ecom-flag">${label}: ${yn(v)}</span>`;
			w.find('.v-ecom-flags').html(
				flag('Appointment Required', p.custom_appointment_required) +
				flag('GRN Available', p.custom_grn_available) +
				flag('Partial Order Allowed', p.custom_partial_order_allowed) +
				flag('GST-Exclusive Buyer', p.custom_gst_exclusive_buyer)
			);
			w.find('.v-ecom-flags-row').show();
		} else {
			w.find('.v-ecom-flags-row').hide();
		}

		// Hide customer rows where field not permitted
		[
			['customer_name', '.v-customer-name'],
			['order_type', '.v-order-type'],
			['address_display', '.v-billing'],
			['shipping_address', '.v-shipping'],
			['transaction_date', '.v-date'],
			['po_no', '.v-po-no'],
			['tax_id', '.v-tax-id'],
			['custom_dispatch_date', '.v-dispatch-date'],
			['delivery_date', '.v-delivery-date'],
		].forEach(([key, sel]) => {
			const $tr = w.find(sel).closest('tr');
			if (!this._has(p, key)) {
				$tr.hide();
			} else {
				$tr.show();
			}
		});
		// E-com free-text addresses keep the billing/shipping rows visible even
		// when there is no linked ERPNext Address record.
		if (this._has(p, 'custom_billing_address_text') && p.custom_billing_address_text) {
			w.find('.v-billing').closest('tr').show();
		}
		if (this._has(p, 'custom_shipping_address_text') && p.custom_shipping_address_text) {
			w.find('.v-shipping').closest('tr').show();
		}

		const items = Array.isArray(payload.items) ? payload.items : [];
		w.find('.sec-order-items').show();
		const tb = w.find('.v-items tbody').empty();
		// Partial orders: per-SKU Remaining column (outstanding = ordered − committed).
		const show_remaining = !!cint(payload.show_remaining);
		const remaining_map = payload.remaining_qty || {};
		w.find('.v-remaining-th').toggle(show_remaining);
		if (!items.length) {
			tb.append(
				`<tr><td colspan="14" class="text-muted text-center">${__('No line items on this order.')}</td></tr>`
			);
		} else {
			items.forEach((it, i) => {
				const img = it.custom_product_image_url || it.custom_product_image || '';
				const imgTag = img
					? `<img src="${this._esc(img)}" alt="" class="so-view-item-img" />`
					: '—';
				const sku = this._has(it, 'item_code') ? this._esc(it.item_code) : '—';
				const nm = this._has(it, 'item_name') ? this._esc(it.item_name) : '—';
				const qty = this._has(it, 'qty') ? flt(it.qty) : null;
				const box = this._has(it, 'custom_box') ? flt(it.custom_box) : null;
				const rowCur = it.currency || currency;
				const mrp = this._has(it, 'custom_customer_mrp')
					? format_currency(flt(it.custom_customer_mrp), rowCur)
					: '—';
				const sp = this._has(it, 'custom_selling_price')
					? format_currency(flt(it.custom_selling_price), rowCur)
					: '—';
				const fd = this._has(it, 'custom_flat_discount') ? flt(it.custom_flat_discount) : null;
				const of = this._has(it, 'custom_offer') ? flt(it.custom_offer) : null;
				const ad = this._has(it, 'custom_additional_discount') ? flt(it.custom_additional_discount) : null;
				const rmk = this._has(it, 'custom_remarks') && String(it.custom_remarks).trim() !== ''
					? this._esc(it.custom_remarks)
					: '—';
				const amt = this._has(it, 'amount')
					? format_currency(
							flt(it.amount) + flt(it.custom_item_tax || 0),
							rowCur
					  )
					: '—';
				let remTd = '';
				if (show_remaining) {
					const rem = flt(remaining_map[it.item_code] || 0);
					remTd = `<td class="text-right">${rem > 0 ? `<strong>${rem}</strong>` : '0'}</td>`;
				}
				tb.append(`<tr>
					<td>${i + 1}</td>
					<td class="text-center">${imgTag}</td>
					<td>${sku}</td>
					<td>${nm}</td>
					<td class="text-right">${qty != null ? qty : '—'}</td>
					${remTd}
					<td class="text-right">${box != null ? box : '—'}</td>
					<td class="text-right">${mrp}</td>
					<td class="text-right">${sp}</td>
					<td class="text-right">${fd != null ? fd : '—'}</td>
					<td class="text-right">${of != null ? of : '—'}</td>
					<td class="text-right">${ad != null ? ad : '—'}</td>
					<td>${rmk}</td>
					<td class="text-right"><strong>${amt}</strong></td>
				</tr>`);
			});
		}

		const freebies = Array.isArray(payload.freebies) ? payload.freebies : [];
		if (freebies.length) {
			w.find('.sec-marketing-freebies').show();
			const fb = w.find('.v-freebies tbody').empty();
			freebies.forEach((row) => {
				fb.append(`<tr>
					<td>${this._has(row, 'item_code') ? this._esc(row.item_code) : '—'}</td>
					<td>${this._has(row, 'item_name') ? this._esc(row.item_name) : '—'}</td>
					<td class="text-right">${this._has(row, 'qty') ? flt(row.qty) : '—'}</td>
					<td>${this._has(row, 'remarks') ? this._esc(row.remarks) : '—'}</td>
				</tr>`);
			});
		} else {
			w.find('.sec-marketing-freebies').hide();
		}

		const damage = !!payload.additional_units_damage;
		const schemeRows = Array.isArray(payload.scheme_rows) ? payload.scheme_rows : [];
		const damageItemRows = Array.isArray(payload.damage_item_rows) ? payload.damage_item_rows : [];

		if (schemeRows.length) {
			w.find('.sec-scheme').show();
			const sb = w.find('.v-scheme tbody').empty();
			schemeRows.forEach((row) => {
				const sch = row.scheme != null && String(row.scheme).trim() !== '' ? String(row.scheme) : '';
				sb.append(`<tr>
					<td>${this._has(row, 'item_code') ? this._esc(row.item_code) : '—'}</td>
					<td>${this._has(row, 'item_name') ? this._esc(row.item_name) : '—'}</td>
					<td class="text-right">${this._has(row, 'qty') ? flt(row.qty) : '—'}</td>
					<td>${sch ? this._esc(sch) : '—'}</td>
				</tr>`);
			});
		} else {
			w.find('.sec-scheme').hide();
		}

		if (damage) {
			w.find('.sec-damage-items').show();
			const db = w.find('.v-damage-items tbody').empty();
			if (!damageItemRows.length) {
				db.append(
					`<tr><td colspan="5" class="text-muted text-center">${__('No lines in Additional Units – Damage.')}</td></tr>`
				);
			} else {
				damageItemRows.forEach((row) => {
					db.append(`<tr>
						<td>${this._has(row, 'item_code') ? this._esc(row.item_code) : '—'}</td>
						<td>${this._has(row, 'item_name') ? this._esc(row.item_name) : '—'}</td>
						<td class="text-right">${this._has(row, 'qty') ? flt(row.qty) : '—'}</td>
						<td>${this._has(row, 'previous_order_id') ? this._esc(row.previous_order_id) : '—'}</td>
						<td>${this._has(row, 'remarks') ? this._esc(row.remarks) : '—'}</td>
					</tr>`);
				});
			}
		} else {
			w.find('.sec-damage-items').hide();
		}

		const cashPct = flt(p.custom_cash_discount);
		const cashAmt = flt(p.custom_cash_discount_amount);
		// Only surface cash discount when one was actually applied.
		if (cashPct > 0) {
			w.find('.sec-cash-disc').show();
			w.find('.v-cash-disc-pct').text(
				cashAmt > 0 ? `${cashPct}%  (- ${format_currency(cashAmt, currency)})` : `${cashPct}%`
			);
		} else {
			w.find('.sec-cash-disc').hide();
		}

		const showMoneyBlock = (keys) => keys.some((k) => this._has(p, k));
		if (showMoneyBlock(['total_qty', 'total', 'custom_cash_discount', 'grand_total'])) {
			w.find('.sec-grand').show();
			w.find('.v-total-qty').text(this._has(p, 'total_qty') ? String(flt(p.total_qty)) : '—');
			w.find('.v-total-amount').text(this._fmt_num(p, 'total', true));
			if (cashPct > 0) {
				w.find('.v-grand-cash-row').show();
				w.find('.v-grand-cash-pct').text(`${cashPct}%`);
				w.find('.v-grand-cash-amt').text(cashAmt > 0 ? `(- ${format_currency(cashAmt, currency)})` : '');
			} else {
				w.find('.v-grand-cash-row').hide();
			}
			w.find('.v-grand-total').html(`<strong>${this._fmt_num(p, 'grand_total', true)}</strong>`);
		} else {
			w.find('.sec-grand').hide();
		}

		if (this._has(p, 'total_taxes_and_charges')) {
			w.find('.sec-taxes').show();
			w.find('.v-total-gst').text(this._fmt_num(p, 'total_taxes_and_charges', true));
		} else {
			w.find('.sec-taxes').hide();
		}

		if (showMoneyBlock(['net_total', 'total_taxes_and_charges', 'rounding_adjustment', 'rounded_total'])) {
			w.find('.sec-net').show();
			w.find('.v-net-total-excl').text(this._fmt_num(p, 'net_total', true));
			w.find('.v-net-total-gst').text(this._fmt_num(p, 'total_taxes_and_charges', true));
			w.find('.v-rounding').text(this._fmt_num(p, 'rounding_adjustment', true));
			w.find('.v-rounded-total').html(`<strong>${this._fmt_num(p, 'rounded_total', true)}</strong>`);
		} else {
			w.find('.sec-net').hide();
		}

		w.find('.so-view-order-details-wrap').show();
	}
}
