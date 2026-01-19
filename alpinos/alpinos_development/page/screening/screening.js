frappe.pages['screening'].on_page_load = function(wrapper) {
	var me = this;
	
	// Create page container
	var $wrapper = $(wrapper);
	$wrapper.html('<div class="screening-page">\
		<div class="page-header">\
			<h2>Job Applicant Screening</h2>\
		</div>\
		<div class="filter-section" style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px;">\
			<div class="filter-control">\
				<label for="category-filter">Filter by Category:</label>\
				<select id="category-filter" class="form-control">\
					<option value="">All</option>\
					<option value="White">White</option>\
					<option value="Hold">Hold</option>\
					<option value="Black">Black</option>\
				</select>\
			</div>\
			<div class="filter-control">\
				<label for="status-filter">Filter by Status:</label>\
				<select id="status-filter" class="form-control">\
					<option value="">All</option>\
					<option value="Pending Screening">Pending Screening</option>\
					<option value="Shortlisted">Shortlisted</option>\
					<option value="Screening Call Scheduled">Screening Call Scheduled</option>\
					<option value="On Hold">On Hold</option>\
					<option value="Not Eligible">Not Eligible</option>\
					<option value="Accepted">Accepted</option>\
					<option value="Rejected">Rejected</option>\
					<option value="Hired">Hired</option>\
				</select>\
			</div>\
			<div class="filter-control">\
				<label for="from-date-filter">From Date:</label>\
				<input type="date" id="from-date-filter" class="form-control" />\
			</div>\
			<div class="filter-control">\
				<label for="to-date-filter">To Date:</label>\
				<input type="date" id="to-date-filter" class="form-control" />\
			</div>\
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
	
	// Store all applicants data
	var allApplicants = [];
	
	// Load data
	load_screening_data();
	
	// Filter change handlers
	$wrapper.find('#category-filter, #status-filter, #from-date-filter, #to-date-filter').on('change', function() {
		apply_filters();
	});
	
	function apply_filters() {
		var selectedCategory = $('#category-filter').val() || '';
		var selectedStatus = $('#status-filter').val() || '';
		var fromDate = $('#from-date-filter').val() || '';
		var toDate = $('#to-date-filter').val() || '';
		filter_and_render_table(allApplicants, selectedCategory, selectedStatus, fromDate, toDate);
	}
	
	function load_screening_data() {
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Job Applicant',
				fields: [
					'name',
					'candidate_id',
					'applicant_name',
					'resume_attachment',
					'degree',
					'upper_range',
					'currency',
					'candidate_category',
					'screening_status',
					'creation'
				],
				order_by: 'creation desc',
				limit_page_length: 0  // 0 means no limit - fetch all records
			},
			callback: function(r) {
				if (r.message) {
					allApplicants = r.message;
					apply_filters();
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
	
	function filter_and_render_table(applicants, categoryFilter, statusFilter, fromDate, toDate) {
		var filtered = applicants.filter(function(applicant) {
			// Category filter
			// If "All" is selected, show all entries EXCEPT Black and Hold
			if (!categoryFilter || categoryFilter === '' || categoryFilter === 'All') {
				var category = applicant.candidate_category || '';
				if (category === 'Black' || category === 'Hold') {
					return false;
				}
			} else {
				// If a specific filter is selected (White, Hold, or Black), show that category only
				if (applicant.candidate_category !== categoryFilter) {
					return false;
				}
			}
			
			// Status filter - only filter if a specific status is selected
			if (statusFilter && statusFilter !== '') {
				var applicantStatus = applicant.screening_status || '';
				if (applicantStatus !== statusFilter) {
					return false;
				}
			}
			
			// Date filter (based on creation date)
			if (fromDate || toDate) {
				var creationDate = applicant.creation ? new Date(applicant.creation.split(' ')[0]) : null;
				if (!creationDate) {
					return false;
				}
				
				if (fromDate) {
					var from = new Date(fromDate);
					if (creationDate < from) {
						return false;
					}
				}
				
				if (toDate) {
					var to = new Date(toDate);
					to.setHours(23, 59, 59, 999); // Include the entire day
					if (creationDate > to) {
						return false;
					}
				}
			}
			
			return true;
		});
		
		render_table(filtered);
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
			
			// Candidate ID - make it a clickable link to Job Applicant form
			var candidateId = applicant.candidate_id || applicant.name || '-';
			var candidateIdLink = '';
			if (applicant.name) {
				candidateIdLink = '<a href="/app/job-applicant/' + applicant.name + '" target="_blank" class="text-primary">' + candidateId + '</a>';
			} else {
				candidateIdLink = candidateId;
			}
			row.append('<td>' + candidateIdLink + '</td>');
			
			// Applicant Name
			row.append('<td>' + (applicant.applicant_name || '-') + '</td>');
			
			// Resume Link - only use resume_attachment field
			var resumeLink = '';
			if (applicant.resume_attachment) {
				// Get file URL from resume_attachment (File doctype)
				var fileUrl = applicant.resume_attachment;
				// Handle different file URL formats
				if (fileUrl.startsWith('http://') || fileUrl.startsWith('https://')) {
					// Already a full URL
					resumeLink = '<a href="' + fileUrl + '" target="_blank" class="btn btn-sm btn-link">View Resume</a>';
				} else if (fileUrl.startsWith('/files/') || fileUrl.startsWith('/private/files/')) {
					// Already has /files/ prefix
					resumeLink = '<a href="' + fileUrl + '" target="_blank" class="btn btn-sm btn-link">View Resume</a>';
				} else {
					// Just file name - prepend /files/
					fileUrl = '/files/' + fileUrl;
					resumeLink = '<a href="' + fileUrl + '" target="_blank" class="btn btn-sm btn-link">View Resume</a>';
				}
			} else {
				resumeLink = '-';
			}
			row.append('<td>' + resumeLink + '</td>');
			
			// Degree
			row.append('<td>' + (applicant.degree || '-') + '</td>');
			
			// Expected CTC
			var expectedCTC = '-';
			if (applicant.upper_range || applicant.upper_range === 0) {
				var currency = applicant.currency || '';
				var ctcValue = applicant.upper_range || 0;
				if (currency) {
					expectedCTC = currency + ' ' + format_currency(ctcValue);
				} else {
					expectedCTC = format_currency(ctcValue);
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
			
			// Screening Status (read-only display - automatically updated)
			var statusDisplay = applicant.screening_status || 'Pending Screening';
			row.append('<td><span class="badge badge-secondary">' + statusDisplay + '</span></td>');
			
			// Actions
			var actionsHtml = '<button class="btn btn-sm btn-primary save-btn" data-name="' + applicant.name + '">Save</button>';
			
			// Schedule Interview button - only show for WHITE category
			if (applicant.candidate_category === 'White') {
				actionsHtml += ' <button class="btn btn-sm btn-success schedule-interview-btn" data-name="' + applicant.name + '" style="margin-left: 5px;">Schedule Interview</button>';
			}
			
			row.append('<td>' + actionsHtml + '</td>');
			
			tbody.append(row);
		});
		
		// Attach event handlers
		attach_event_handlers();
	}
	
	function attach_event_handlers() {
		// Save button handler - only saves category (screening_status is auto-updated)
		$wrapper.find('.save-btn').off('click').on('click', function() {
			var applicant_name = $(this).data('name');
			var row = $(this).closest('tr');
			var category = row.find('.candidate-category').val();
			
			save_applicant_data(applicant_name, {
				candidate_category: category
			});
		});
		
		// Schedule Interview button handler
		$wrapper.find('.schedule-interview-btn').off('click').on('click', function() {
			var applicant_name = $(this).data('name');
			schedule_interview(applicant_name);
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
	
	function create_interview_with_resume(job_applicant, interview_round, resumeLink) {
		// Create a new Interview - set job_applicant first, then resume_link
		// The form's fetch_from will auto-populate other fields from job_applicant
		var interviewDoc = frappe.model.get_new_doc("Interview");
		
		// Set basic fields
		interviewDoc.job_applicant = job_applicant.name;
		interviewDoc.interview_round = interview_round;
		
		// Set resume_link from resume_attachment if it exists
		if (resumeLink) {
			interviewDoc.resume_link = resumeLink;
		}
		
		// Open the form
		frappe.set_route("Form", "Interview", interviewDoc.name);
	}
	
	function schedule_interview(applicant_name) {
		// First, ensure "Call Round Interview" exists
		frappe.call({
			method: 'alpinos.job_applicant_automation.ensure_call_round_interview_exists',
			callback: function(round_r) {
				if (round_r.message) {
					var interview_round = round_r.message;
					
					// Get the Job Applicant document
					frappe.call({
						method: 'frappe.client.get',
						args: {
							doctype: 'Job Applicant',
							name: applicant_name
						},
						callback: function(r) {
							if (r.message) {
								var job_applicant = r.message;
								
								// Get resume link - only use resume_attachment field
								var resumeLink = '';
								if (job_applicant.resume_attachment) {
									var fileUrl = job_applicant.resume_attachment;
									// Handle different file URL formats
									if (fileUrl.startsWith('http://') || fileUrl.startsWith('https://')) {
										// Already a full URL
										resumeLink = fileUrl;
									} else if (fileUrl.startsWith('/files/') || fileUrl.startsWith('/private/files/')) {
										// Already has /files/ or /private/files/ prefix
										resumeLink = fileUrl;
									} else {
										// Just file name - prepend /files/
										resumeLink = '/files/' + fileUrl;
									}
								}
								
								// Create interview with resume link
								create_interview_with_resume(job_applicant, interview_round, resumeLink);
							} else {
								frappe.msgprint({
									title: __('Error'),
									message: __('Could not load Job Applicant details'),
									indicator: 'red'
								});
							}
						},
						error: function(r) {
							frappe.msgprint({
								title: __('Error'),
								message: __('Failed to load Job Applicant: ' + (r.message || 'Unknown error')),
								indicator: 'red'
							});
						}
					});
				} else {
					frappe.msgprint({
						title: __('Error'),
						message: __('Could not create or find Interview Round'),
						indicator: 'red'
					});
				}
			},
			error: function(r) {
				frappe.msgprint({
					title: __('Error'),
					message: __('Failed to setup Interview Round: ' + (r.message || 'Unknown error')),
					indicator: 'red'
				});
			}
		});
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
			.filter-section {
				margin-bottom: 20px;
				padding: 15px;
				background: white;
				border-radius: 4px;
				box-shadow: 0 1px 3px rgba(0,0,0,0.1);
			}
			.filter-control {
				display: flex;
				align-items: center;
				gap: 10px;
			}
			.filter-control label {
				margin: 0;
				font-weight: 500;
			}
			.filter-control select {
				width: 200px;
			}
		`).appendTo('head');
	}
};

