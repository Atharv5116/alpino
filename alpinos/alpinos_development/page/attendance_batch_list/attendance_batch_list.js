frappe.pages['attendance_batch_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Attendance Batches'),
		single_column: true,
	});
	page.main.html(frappe.render_template('attendance_batch_list'));
	wrapper.page_instance = new AttendanceBatchListPage(page);
};

frappe.pages['attendance_batch_list'].on_page_show = function (wrapper) {
	// Refresh when navigating back from the entry page.
	if (wrapper.page_instance) wrapper.page_instance.load_list(true);
};

const ABL_STATUS_COLORS = {
	Draft: 'orange',
	'Pending Approval': 'blue',
	Approved: 'green',
	Locked: 'gray',
};

class AttendanceBatchListPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.engine = 'All';
		this.start = 0;
		this.page_length = 20;
		this.setup_toolbar();
		this.bind_events();
		this.load_list(true);
	}

	setup_toolbar() {
		this.page.set_primary_action(__('Create New Entry'), () => this.new_entry_dialog());
		this.page.add_inner_button(__('Refresh'), () => this.load_list(true));
	}

	bind_events() {
		const me = this;
		this.wrapper.find('.abl-tabs').on('click', 'a[data-engine]', function (e) {
			e.preventDefault();
			me.wrapper.find('.abl-tabs a').removeClass('active');
			$(this).addClass('active');
			me.engine = $(this).data('engine');
			me.load_list(true);
		});
		this.wrapper.find('.abl-load-more').on('click', () => {
			this.start += this.page_length;
			this.load_list(false);
		});
		this.wrapper.find('.abl-rows').on('click', 'a[data-open]', function (e) {
			e.preventDefault();
			frappe.route_options = { batch: $(this).data('open') };
			frappe.set_route('attendance_batch_entry');
		});
	}

	load_list(reset) {
		if (reset) this.start = 0;
		frappe
			.xcall('alpinos.attendance_batch_api.get_batches', {
				rule_engine: this.engine,
				start: this.start,
				page_length: this.page_length,
			})
			.then((r) => this.render(r, reset));
	}

	render(r, reset) {
		const tbody = this.wrapper.find('.abl-rows');
		if (reset) tbody.empty();

		// Tab counts
		const counts = r.counts || {};
		this.wrapper.find('.abl-count').each(function () {
			const n = counts[$(this).data('engine')];
			$(this).text(n ? n : '');
		});

		if (!r.batches.length && reset) {
			tbody.html(
				`<tr><td colspan="7" class="text-muted text-center">${__(
					'No attendance batches yet. Click Create New Entry to start.'
				)}</td></tr>`
			);
			this.wrapper.find('.abl-more').hide();
			return;
		}

		let sr = tbody.find('tr[data-name]').length;
		r.batches.forEach((b) => {
			sr += 1;
			const color = ABL_STATUS_COLORS[b.workflow_state] || 'gray';
			const editable = b.workflow_state === 'Draft';
			tbody.append(`
				<tr data-name="${frappe.utils.escape_html(b.name)}">
					<td>${sr}</td>
					<td><a data-open="${frappe.utils.escape_html(b.name)}" href="#">${frappe.utils.escape_html(b.name)}</a></td>
					<td>${frappe.utils.escape_html(b.month_title || '')}</td>
					<td>${frappe.utils.escape_html(b.rule_engine)}</td>
					<td>${b.row_count || 0}</td>
					<td><span class="indicator-pill ${color}">${__(b.workflow_state || 'Draft')}</span></td>
					<td>
						<a class="btn btn-xs btn-default" data-open="${frappe.utils.escape_html(b.name)}" href="#">
							${editable ? __('View / Edit') : __('View')}
						</a>
					</td>
				</tr>`);
		});

		this.wrapper.find('.abl-more').toggle(!!r.has_more);
	}

	new_entry_dialog() {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Create New Attendance Batch'),
			fields: [
				{
					fieldtype: 'Select',
					fieldname: 'rule_engine',
					label: __('Staff Category'),
					options: '\nHO/Admin\nWH ESSL\nOffline Sales',
					reqd: 1,
					default: me.engine !== 'All' ? me.engine : '',
				},
				{
					fieldtype: 'Date',
					fieldname: 'payroll_month',
					label: __('Payroll Month (pick any date in the month)'),
					reqd: 1,
				},
				{
					fieldtype: 'Link',
					fieldname: 'company',
					label: __('Company'),
					options: 'Company',
					default: frappe.defaults.get_user_default('Company'),
				},
			],
			primary_action_label: __('Create'),
			primary_action(values) {
				frappe
					.xcall('alpinos.attendance_batch_api.create_batch', values)
					.then((name) => {
						d.hide();
						frappe.route_options = { batch: name };
						frappe.set_route('attendance_batch_entry');
					});
			},
		});
		d.show();
	}
}
