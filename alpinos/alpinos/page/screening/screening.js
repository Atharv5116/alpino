frappe.pages['screening'].on_page_load = function(wrapper) {
	var me = this;
	
	// Create page container
	var $wrapper = $(wrapper);
	$wrapper.html('<div class="screening-page">\
		<div class="page-header">\
			<h2>Job Applicant Screening</h2>\
		</div>\
		<div class="screening-container">\
			<div class="table-container">\
				<div class="table-responsive">\
					<table class="table table-bordered table-hover screening-table">\
						<thead>\
							<tr>\
								<th>Candidate ID</th>\
								<th>Applicant Name</th>\
								<th>Resume Link</th>\
								<th>Degree</th>\
								<th>Expected CTC</th>\
								<th>Category</th>\
								<th>Screening Status</th>\
								<th>Actions</th>\
							</tr>\
						</thead>\
						<tbody id="screening-table-body">\
							<tr><td colspan="8" class="text-center">Loading...</td></tr>\
						</tbody>\
					</table>\
				</div>\
			</div>\
		</div>\
	</div>');
	
	// Load data
	load_screening_data();
	
	function load_screening_data() {
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Job Applicant',
				fields: [
					'name',
					'candidate_id',
					'applicant_name',
					'resume_link',
					'degree',
					'employment_expected_ctc',
					'candidate_category',
					'screening_status'
				],
				order_by: 'creation desc'
			},
			callback: function(r) {
				if (r.message) {
					render_table(r.message);
				} else {
					$('#screening-table-body').html('<tr><td colspan="8" class="text-center">No applicants found</td></tr>');
				}
			},
			error: function(r) {
				console.error('Error loading data:', r);
				$('#screening-table-body').html('<tr><td colspan="8" class="text-center text-danger">Error loading data. Please refresh the page.</td></tr>');
			}
		});
	}
	
	function render_table(applicants) {
		var tbody = $('#screening-table-body');
		tbody.empty();
		
		if (applicants.length === 0) {
			tbody.append('<tr><td colspan="8" class="text-center">No applicants found</td></tr>');
			return;
		}
		
		applicants.forEach(function(applicant) {
			var row = $('<tr data-name="' + applicant.name + '"></tr>');
			
			// Candidate ID
			var candidateId = applicant.candidate_id || '-';
			row.append('<td>' + candidateId + '</td>');
			
			// Applicant Name
			row.append('<td>' + (applicant.applicant_name || '-') + '</td>');
			
			// Resume Link
			var resumeLink = '';
			if (applicant.resume_link) {
				resumeLink = '<a href="' + applicant.resume_link + '" target="_blank" class="btn btn-sm btn-link">View Resume</a>';
			} else {
				resumeLink = '-';
			}
			row.append('<td>' + resumeLink + '</td>');
			
			// Degree
			row.append('<td>' + (applicant.degree || '-') + '</td>');
			
			// Expected CTC
			var expectedCTC = '-';
			if (applicant.employment_expected_ctc) {
				var ctcValue = parseFloat(applicant.employment_expected_ctc) || 0;
				if (ctcValue > 0) {
					// Format as currency (INR by default)
					expectedCTC = 'INR ' + format_currency(ctcValue);
				}
			}
			row.append('<td>' + expectedCTC + '</td>');
			
			// Category dropdown
			var categoryDropdown = '<select class="form-control candidate-category" data-name="' + applicant.name + '" data-field="candidate_category">\
				<option value="">-- Select --</option>\
				<option value="White"' + (applicant.candidate_category === 'White' ? ' selected' : '') + '>White</option>\
				<option value="Hold"' + (applicant.candidate_category === 'Hold' ? ' selected' : '') + '>Hold</option>\
				<option value="Black"' + (applicant.candidate_category === 'Black' ? ' selected' : '') + '>Black</option>\
			</select>';
			row.append('<td>' + categoryDropdown + '</td>');
			
			// Screening Status dropdown
			var statusOptions = [
				'Pending Screening',
				'Screening Call Scheduled',
				'On Hold',
				'Not Eligible',
				'Interview Scheduled',
				'Accepted',
				'Rejected',
				'Hired'
			];
			var statusDropdown = '<select class="form-control screening-status" data-name="' + applicant.name + '" data-field="screening_status">\
				<option value="">-- Select --</option>';
			statusOptions.forEach(function(option) {
				var selected = (applicant.screening_status === option) ? ' selected' : '';
				statusDropdown += '<option value="' + option + '"' + selected + '>' + option + '</option>';
			});
			statusDropdown += '</select>';
			row.append('<td>' + statusDropdown + '</td>');
			
			// Actions
			row.append('<td>\
				<button class="btn btn-sm btn-primary save-btn" data-name="' + applicant.name + '">Save</button>\
			</td>');
			
			tbody.append(row);
		});
		
		// Attach event handlers
		attach_event_handlers();
	}
	
	function attach_event_handlers() {
		// Save button handler
		$wrapper.find('.save-btn').off('click').on('click', function() {
			var applicant_name = $(this).data('name');
			var row = $(this).closest('tr');
			var category = row.find('.candidate-category').val();
			var status = row.find('.screening-status').val();
			
			save_applicant_data(applicant_name, {
				candidate_category: category,
				screening_status: status
			});
		});
	}
	
	function save_applicant_data(applicant_name, data) {
		frappe.call({
			method: 'frappe.client.set_value',
			args: {
				doctype: 'Job Applicant',
				name: applicant_name,
				fieldname: data
			},
			callback: function(r) {
				if (!r.exc) {
					frappe.show_alert({
						message: __('Updated successfully'),
						indicator: 'green'
					}, 3);
					// Reload the page data
					setTimeout(function() {
						load_screening_data();
					}, 500);
				} else {
					frappe.msgprint({
						title: __('Error'),
						message: __('Failed to update: ' + (r.exc || 'Unknown error')),
						indicator: 'red'
					});
				}
			},
			error: function(r) {
				frappe.msgprint({
					title: __('Error'),
					message: __('Failed to update: ' + (r.message || 'Unknown error')),
					indicator: 'red'
				});
			}
		});
	}
	
	function format_currency(value) {
		if (!value) return '0.00';
		return parseFloat(value).toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
	}
	
	// Add some basic styling
	if (!$('style#screening-page-styles').length) {
		$('<style id="screening-page-styles">').prop('type', 'text/css').html(`
			.screening-page {
				padding: 20px;
			}
			.page-header {
				margin-bottom: 20px;
			}
			.page-header h2 {
				margin: 0;
				padding: 0;
			}
			.screening-table {
				font-size: 13px;
			}
			.screening-table th {
				background-color: #f5f5f5;
				font-weight: 600;
			}
			.screening-table td {
				vertical-align: middle;
			}
			.screening-table select {
				min-width: 150px;
			}
			.table-container {
				background: white;
				padding: 15px;
				border-radius: 4px;
				box-shadow: 0 1px 3px rgba(0,0,0,0.1);
			}
		`).appendTo('head');
	}
};

