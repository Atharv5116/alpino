frappe.pages['attendance_batch_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Attendance Batch'),
		single_column: true,
	});
	page.main.html(frappe.render_template('attendance_batch_entry'));
	wrapper.page_instance = new AttendanceBatchEntryPage(page);
};

frappe.pages['attendance_batch_entry'].on_page_show = function (wrapper) {
	// route_options carries the batch name from the list page / new-entry dialog.
	const batch = frappe.route_options && frappe.route_options.batch;
	if (batch) {
		frappe.route_options = null;
		wrapper.page_instance.load(batch);
	} else if (!wrapper.page_instance.batch_name) {
		wrapper.page_instance.pick_batch();
	}
};

const ABE_STATUS_COLORS = {
	Draft: 'orange',
	'Pending Approval': 'blue',
	Approved: 'green',
	Locked: 'gray',
};

// Grid column sets per rule engine: [label, fieldname]
const ABE_COLUMNS = {
	common: [
		[__('Employee'), 'employee'],
		[__('Name'), 'employee_name'],
		[__('Working Days'), 'working_days'],
		[__('Payable Days'), 'payable_days'],
		[__('Present'), 'present_days'],
		[__('Absent'), 'absent_days'],
		[__('Half Days'), 'half_days'],
		[__('Paid Leaves'), 'paid_leaves'],
		[__('Unpaid (LOP)'), 'unpaid_leaves'],
	],
	'HO/Admin': [
		[__('Late >10:15'), 'late_group1_count'],
		[__('Late >10:30'), 'late_group2_count'],
		[__('Late Ded. (Days)'), 'late_deduction_days'],
		[__('WFH'), 'wfh_count'],
		[__('OD'), 'od_days'],
		[__('Comp-Off'), 'comp_off_earned'],
	],
	'WH ESSL': [
		[__('OT (H:MM)'), 'ot_hours_display'],
		[__('EL (H:MM)'), 'el_hours_display'],
		[__('OT Min'), 'ot_minutes'],
		[__('EL Min'), 'el_minutes'],
		[__('Weekends'), 'weekends'],
	],
	'Offline Sales': [
		[__('PH'), 'public_holidays'],
		[__('Weekends'), 'weekends'],
		[__('Present on Weekend'), 'present_on_weekend'],
		[__('PL Opening'), 'pl_opening_balance'],
		[__('PL Taken'), 'pl_taken'],
		[__('PL Closing'), 'pl_closing_balance'],
		[__('TADA Days'), 'tada_days'],
	],
};

// Summary tiles per engine: [label, fieldname, aggregation]
const ABE_SUMMARY = {
	'HO/Admin': [
		[__('Employees'), null, 'count'],
		[__('Payable Days'), 'payable_days', 'sum'],
		[__('Late Deductions'), 'late_deduction_days', 'sum'],
		[__('WFH Count'), 'wfh_count', 'sum'],
		[__('Unpaid (LOP)'), 'unpaid_leaves', 'sum'],
	],
	'WH ESSL': [
		[__('Employees'), null, 'count'],
		[__('Payable Days'), 'payable_days', 'sum'],
		[__('OT Minutes'), 'ot_minutes', 'sum'],
		[__('EL Minutes'), 'el_minutes', 'sum'],
	],
	'Offline Sales': [
		[__('Employees'), null, 'count'],
		[__('Payable Days'), 'payable_days', 'sum'],
		[__('TADA Days'), 'tada_days', 'sum'],
		[__('Unpaid (LOP)'), 'unpaid_leaves', 'sum'],
	],
};

class AttendanceBatchEntryPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.batch_name = null;
		this.data = null;
	}

	pick_batch() {
		// Direct navigation without a batch in route_options — offer a picker.
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Open Attendance Batch'),
			fields: [
				{
					fieldtype: 'Link',
					fieldname: 'batch',
					label: __('Batch'),
					options: 'Monthly Attendance Batch',
					reqd: 1,
				},
			],
			primary_action_label: __('Open'),
			primary_action(values) {
				d.hide();
				me.load(values.batch);
			},
			secondary_action_label: __('Go to Batch List'),
			secondary_action() {
				d.hide();
				frappe.set_route('attendance_batch_list');
			},
		});
		d.show();
	}

	load(name) {
		this.batch_name = name;
		frappe.xcall('alpinos.attendance_batch_api.get_batch', { name }).then((r) => {
			this.data = r;
			this.render();
		});
	}

	// ------------------------------------------------------------------ render

	render() {
		const { doc, transitions, is_editable } = this.data;
		this.page.set_title(doc.month_title || doc.name);

		// Header
		const color = ABE_STATUS_COLORS[doc.workflow_state] || 'gray';
		this.wrapper.find('.abe-month').text(doc.month_title || '');
		this.wrapper.find('.abe-engine').text(doc.rule_engine);
		this.wrapper.find('.abe-company').text(doc.company);
		this.wrapper
			.find('.abe-status')
			.attr('class', `abe-status indicator-pill ${color}`)
			.text(__(doc.workflow_state || 'Draft'));
		this.wrapper
			.find('.abe-fetched')
			.text(
				doc.fetched_on
					? __('Data fetched by {0} on {1}', [doc.fetched_by, frappe.datetime.str_to_user(doc.fetched_on)])
					: __('No data fetched yet.')
			);

		this.render_actions(transitions);
		this.render_ingestion(doc, is_editable);
		this.render_grid(doc);
		this.render_summary(doc);
	}

	render_actions(transitions) {
		this.page.clear_inner_toolbar();
		this.page.add_inner_button(__('Back to List'), () => frappe.set_route('attendance_batch_list'));
		this.page.add_inner_button(__('Open Form'), () =>
			frappe.set_route('Form', 'Monthly Attendance Batch', this.batch_name)
		);
		(transitions || []).forEach((action) => {
			this.page.add_inner_button(
				__(action),
				() => this.apply_action(action),
				__('Workflow')
			);
		});
	}

	apply_action(action) {
		frappe.confirm(__('Apply action {0} on this batch?', [`<b>${action}</b>`]), () => {
			frappe
				.xcall('alpinos.attendance_batch_api.apply_batch_action', {
					name: this.batch_name,
					action,
				})
				.then(() => {
					frappe.show_alert({ message: __('{0} done', [action]), indicator: 'green' });
					this.load(this.batch_name);
				});
		});
	}

	// Per-engine ingestion slot: Generate (HO) / Fetch + PH (WH) / Upload (Offline).
	render_ingestion(doc, is_editable) {
		const slot = this.wrapper.find('.abe-ingestion').empty();
		if (!is_editable) {
			slot.html(
				`<span class="text-muted">${__(
					'This batch is {0} — data can no longer be changed.',
					[__(doc.workflow_state)]
				)}</span>`
			);
			return;
		}

		const btn = (label) => $(`<button class="btn btn-sm btn-primary">${label}</button>`);
		const me = this;

		if (doc.rule_engine === 'HO/Admin') {
			slot.append(
				`<span style="margin-right:8px;">${__('Generate rows from attendance records for the month.')}</span>`
			);
			btn(__('Generate'))
				.appendTo(slot)
				.on('click', () => me.populate());
		} else if (doc.rule_engine === 'WH ESSL') {
			slot.append(
				`<span style="margin-right:8px;">${__('Fetch eSSL punches and compute OT/EL. Mark month-specific Public Holidays on the form first (Update & Refresh re-runs the calculation).')}</span>`
			);
			btn(__('Fetch ESSL Data'))
				.appendTo(slot)
				.on('click', () => me.populate());
			$(`<button class="btn btn-sm btn-default" style="margin-left:8px;">${__('Update & Refresh')}</button>`)
				.appendTo(slot)
				.on('click', () => me.populate());
		} else {
			slot.append(
				`<span style="margin-right:8px;">${__('Upload the monthly attendance Excel. Re-uploading while in Draft updates the data.')}</span>`
			);
			btn(__('Upload Excel'))
				.appendTo(slot)
				.on('click', () => me.upload_excel());
		}
	}

	populate() {
		frappe
			.xcall('alpinos.attendance_batch_api.populate_batch_rows', { name: this.batch_name })
			.then((r) => {
				frappe.show_alert({
					message: __('{0} employee rows generated', [r.rows]),
					indicator: 'green',
				});
				this.load(this.batch_name);
			});
	}

	upload_excel() {
		const me = this;
		new frappe.ui.FileUploader({
			doctype: 'Monthly Attendance Batch',
			docname: this.batch_name,
			fieldname: 'source_file',
			allow_multiple: false,
			restrictions: { allowed_file_types: ['.xlsx', '.xls', '.csv'] },
			on_success(file) {
				frappe.db
					.set_value('Monthly Attendance Batch', me.batch_name, 'source_file', file.file_url)
					.then(() => me.populate());
			},
		});
	}

	columns_for(engine) {
		return [...ABE_COLUMNS.common, ...(ABE_COLUMNS[engine] || [])];
	}

	render_grid(doc) {
		const cols = this.columns_for(doc.rule_engine);
		const head = this.wrapper.find('.abe-grid-head');
		const body = this.wrapper.find('.abe-grid-body');

		head.html(
			`<tr><th style="width:40px;">#</th>${cols
				.map(([label]) => `<th>${label}</th>`)
				.join('')}</tr>`
		);
		body.empty();

		if (!(doc.rows || []).length) {
			body.html(
				`<tr><td colspan="${cols.length + 1}" class="text-muted text-center">${__(
					'No data yet — generate / fetch / upload above.'
				)}</td></tr>`
			);
			return;
		}

		doc.rows.forEach((row, i) => {
			body.append(
				`<tr>
					<td>${i + 1}</td>
					${cols
						.map(([, field]) => {
							let v = row[field];
							if (v === null || v === undefined) v = '';
							return `<td>${frappe.utils.escape_html(String(v))}</td>`;
						})
						.join('')}
				</tr>`
			);
		});
	}

	render_summary(doc) {
		const card = this.wrapper.find('.abe-summary');
		const tiles = this.wrapper.find('.abe-summary-tiles').empty();
		const spec = ABE_SUMMARY[doc.rule_engine] || [];
		const rows = doc.rows || [];

		if (!rows.length) {
			card.hide();
			return;
		}
		spec.forEach(([label, field, agg]) => {
			let value;
			if (agg === 'count') value = rows.length;
			else value = rows.reduce((acc, r) => acc + (parseFloat(r[field]) || 0), 0);
			value = Math.round(value * 100) / 100;
			tiles.append(
				`<div class="col-sm-2" style="min-width:140px;">
					<div class="text-muted small">${label}</div>
					<div style="font-size:1.3em;font-weight:600;">${value}</div>
				</div>`
			);
		});
		card.show();
	}
}
