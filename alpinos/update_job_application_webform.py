"""
Update Job Application Web Form to auto-populate job_title from URL
"""
import frappe

def update_web_form_script():
	"""Update the job-application web form client script and field defaults"""
	
	web_form = frappe.get_doc("Web Form", "job-application")
	
	# Update job_title field to get default from URL
	for field in web_form.web_form_fields:
		if field.fieldname == "job_title":
			# Don't set a static default, but ensure it can be set from URL
			# The URL parameter will be picked up by Frappe's built-in mechanism
			pass
	
	# No-op base script (avoid attaching to missing fields)
	existing_script = ""

	# Script to ensure job_requisition is set from URL parameter (job_title)
	new_script = """
// Ensure job_requisition from URL parameter job_title is set in form data
(function() {
    const urlParams = new URLSearchParams(window.location.search);
    const jobTitle = urlParams.get('job_title');
    const sourceParam = urlParams.get('source');
    
    if (!jobTitle && !sourceParam) return;
    
    const sourceMap = {
        'linkedin': 'LinkedIn',
        'indeed': 'Indeed',
        'naukari.com': 'Naukari.com',
        'naukari': 'Naukari.com',
        'naukri.com': 'Naukri.com',
        'naukri': 'Naukri.com'
    };
    const sourceValue = sourceParam ? (sourceMap[sourceParam.toLowerCase()] || sourceParam) : null;
    
    if (jobTitle) {
        console.log('🔍 Found job_title in URL:', jobTitle);
    }
    if (sourceValue) {
        console.log('🔍 Found source in URL:', sourceValue);
    }
    
    // Simple DOM-based approach - find input by name
    function setFieldValue() {
        // Find the input field for job_requisition
        const $input = $('input[data-fieldname="job_requisition"]');
        
        if (!$input.length) {
            console.log('⏳ Input field not found yet...');
            return false;
        }
        
        console.log('✅ Found input field, setting value...');
        
        // Set the value
        $input.val(jobTitle);
        $input.trigger('change');
        $input.trigger('input');
        
        console.log('✅ Value set to:', jobTitle);
        
        // Set in frappe.web_form.doc if available
        if (frappe.web_form && frappe.web_form.doc) {
            frappe.web_form.doc.job_requisition = jobTitle;
            console.log('✅ Set in doc');
        }
        
        // Make read-only after setting
        setTimeout(function() {
            $input.prop('readonly', true);
            $input.attr('disabled', 'disabled');
            $input.css({
                'background-color': '#f5f5f5',
                'cursor': 'not-allowed',
                'pointer-events': 'none'
            });
            
            // Hide link button if exists
            $input.closest('.frappe-control').find('.link-btn').hide();
            
            console.log('✅ Made read-only');
        }, 300);
        
        return true;
    }
    
    // Wait for DOM to be ready
    $(document).ready(function() {
        console.log('📄 DOM ready, waiting for field...');
        
        // Try immediately
        setTimeout(setFieldValue, 1000);
        
        // Retry multiple times
        let attempts = 0;
        const retry = setInterval(function() {
            attempts++;
            if (setFieldValue() || attempts >= 15) {
                clearInterval(retry);
                if (attempts >= 15) {
                    console.log('❌ Failed to find field after 15 attempts');
                }
            }
        }, 500);
    });
    
    // Also try with frappe.ready
    frappe.ready(function() {
        setTimeout(setFieldValue, 1000);
    });
    
    // Ensure value is set before submit
    $(document).on('submit', '.web-form', function() {
        const $input = $('input[data-fieldname="job_requisition"]');
        if ($input.length && !$input.val()) {
            $input.val(jobTitle);
        }
        if (frappe.web_form && frappe.web_form.doc) {
            frappe.web_form.doc.job_requisition = jobTitle;
        }
        console.log('✅ Ensured value before submit');
    });
})();

// Resume file type validation (PDF and Word only)
$(document).ready(function() {
    // Function to validate resume file
    function validateResumeFile(fileInput) {
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
            return { valid: false, message: 'No file selected' };
        }
        
        const file = fileInput.files[0];
        const fileName = file.name.toLowerCase();
        
        // Allowed extensions
        const allowedExtensions = ['.pdf', '.doc', '.docx'];
        
        // Get file extension
        const lastDotIndex = fileName.lastIndexOf('.');
        if (lastDotIndex === -1) {
            return { valid: false, message: 'File has no extension' };
        }
        
        const fileExtension = fileName.substring(lastDotIndex);
        
        // Check if extension is allowed
        if (!allowedExtensions.includes(fileExtension)) {
            return {
                valid: false,
                message: 'Resume/CV must be a PDF or Word document (.pdf, .doc, .docx).<br>Current file: ' + file.name + '<br>Extension: ' + fileExtension
            };
        }
        
        // Check file size (max 5MB)
        const maxSize = 5 * 1024 * 1024; // 5MB in bytes
        if (file.size > maxSize) {
            return {
                valid: false,
                message: 'Resume/CV file size must not exceed 5 MB.<br>Current file size: ' + (file.size / (1024 * 1024)).toFixed(2) + ' MB'
            };
        }
        
        // Also check MIME type for extra security
        const allowedMimeTypes = [
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ];
        
        if (!allowedMimeTypes.includes(file.type)) {
            return {
                valid: false,
                message: 'Invalid file type detected.<br>File: ' + file.name + '<br>Type: ' + file.type + '<br>Only PDF and Word documents are allowed.'
            };
        }
        
        return { valid: true, message: 'Valid file: ' + file.name };
    }
    
    // Multiple selectors to catch file input in web forms
    const selectors = [
        'input[data-fieldname="resume_attachment"]',
        'input[name="resume_attachment"]',
        'input[type="file"][data-fieldname="resume_attachment"]',
        '.frappe-control[data-fieldname="resume_attachment"] input[type="file"]',
        'input.input-with-feedback[data-fieldname="resume_attachment"]'
    ];
    
    console.log('🔍 Setting up resume validation handlers...');
    
    // Attach to all possible selectors
    selectors.forEach(selector => {
        $('body').off('change', selector).on('change', selector, function(e) {
            console.log('📎 File selected via selector:', selector);
            
            const file = this.files[0];
            if (!file) {
                console.log('⚠️ No file selected');
                return;
            }
            
            console.log('File details:', {
                name: file.name,
                type: file.type,
                size: file.size
            });
            
            const result = validateResumeFile(this);
            console.log('Validation result:', result);
            
            if (!result.valid) {
                console.log('❌ File validation FAILED:', result.message);
                
                // Clear the file input immediately
                $(this).val('');
                this.value = '';
                if (this.files) {
                    // Try to clear files array (some browsers)
                    try {
                        const dt = new DataTransfer();
                        this.files = dt.files;
                    } catch (err) {
                        console.log('Could not clear files array:', err);
                    }
                }
                
                // Show error message
                frappe.msgprint({
                    title: __('Invalid File'),
                    message: __(result.message),
                    indicator: 'red'
                });
                
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                return false;
            }
            
            console.log('✅ Resume file validated:', result.message);
        });
    });
    
    console.log('✅ Resume validation handlers attached');
    
    // Validate existing attached file on page load
    setTimeout(function() {
        const resumeInput = $('input[data-fieldname="resume_attachment"]')[0];
        if (resumeInput) {
            // Check if there's an existing file URL (already attached file)
            const existingFileUrl = $(resumeInput).attr('data-file-url') || frappe.web_form?.doc?.resume_attachment;
            
            if (existingFileUrl) {
                console.log('🔍 Found existing attached file:', existingFileUrl);
                
                // Extract filename from URL
                const urlParts = existingFileUrl.split('/');
                const fileName = urlParts[urlParts.length - 1].toLowerCase();
                const fileExtension = fileName.substring(fileName.lastIndexOf('.'));
                
                console.log('Existing file extension:', fileExtension);
                
                const allowedExtensions = ['.pdf', '.doc', '.docx'];
                
                if (!allowedExtensions.includes(fileExtension)) {
                    console.log('❌ Existing file has invalid extension:', fileExtension);
                    
                    // Clear the attachment
                    $(resumeInput).val('');
                    $(resumeInput).attr('data-file-url', '');
                    if (frappe.web_form && frappe.web_form.doc) {
                        frappe.web_form.doc.resume_attachment = '';
                    }
                    
                    // Remove the file display
                    $(resumeInput).closest('.frappe-control').find('.attached-file').remove();
                    $(resumeInput).closest('.frappe-control').find('.attached-file-link').remove();
                    
                    // Show warning
                    frappe.msgprint({
                        title: __('Invalid Resume File Removed'),
                        message: __('The previously attached file was not a valid PDF or Word document and has been removed.<br>File: ' + fileName + '<br>Please upload a PDF or Word document (.pdf, .doc, .docx).'),
                        indicator: 'orange'
                    });
                } else {
                    console.log('✅ Existing file is valid:', fileName);
                }
            }
        }
    }, 2000); // Wait 2 seconds for page to fully load
    
    // 2. Phone Number Validation
    let phoneValidated = false;
    $(document).off('blur', 'input[data-fieldname="phone_number"]').on('blur', 'input[data-fieldname="phone_number"]', function() {
        if (phoneValidated) {
            phoneValidated = false;
            return;
        }
        phoneValidated = true;
        
        const phone = $(this).val().trim();
        if (!phone) {
            phoneValidated = false;
            return; // Skip if empty
        }
        
        // Remove spaces, hyphens, parentheses for validation
        const cleanPhone = phone.replace(/[\s\-\(\)]/g, '');
        
        // Check if it contains only digits and +
        if (!/^[\+]?[0-9]+$/.test(cleanPhone)) {
            frappe.msgprint({
                title: __('Invalid Phone Number'),
                message: __('Phone number can only contain numbers, spaces, +, -, ( )'),
                indicator: 'red'
            });
            phoneValidated = false;
            return;
        }
        
        // Check minimum length (at least 10 digits)
        const digitsOnly = cleanPhone.replace(/\+/g, '');
        if (digitsOnly.length < 10) {
            frappe.msgprint({
                title: __('Invalid Phone Number'),
                message: __('Phone number must be at least 10 digits'),
                indicator: 'red'
            });
            phoneValidated = false;
            return;
        }
        
        phoneValidated = false;
    });
    
    // 3. Name Validation
    $(document).on('blur', 'input[data-fieldname="applicant_name"]', function() {
        const name = $(this).val().trim();
        if (!name) return;
        
        // Check minimum 2 characters
        if (name.length < 2) {
            frappe.msgprint({
                title: __('Invalid Name'),
                message: __('Name must be at least 2 characters'),
                indicator: 'red'
            });
            $(this).focus();
            return;
        }
        
        // Check for numbers or invalid special characters
        if (/[0-9@#$%^&*()_+=\[\]{};:"\\|,.<>\/?]/.test(name)) {
            frappe.msgprint({
                title: __('Invalid Name'),
                message: __('Name cannot contain numbers or special characters (except spaces, hyphens, apostrophes)'),
                indicator: 'red'
            });
            $(this).focus();
            return;
        }
        
        // Check if only whitespace
        if (!/[a-zA-Z]/.test(name)) {
            frappe.msgprint({
                title: __('Invalid Name'),
                message: __('Name must contain at least one letter'),
                indicator: 'red'
            });
            $(this).focus();
            return;
        }
    });
    
    // 5. Experience Validation
    $(document).on('blur', 'input[data-fieldname="total_experience"]', function() {
        const experience = parseFloat($(this).val());
        if (isNaN(experience)) return;
        
        if (experience < 0) {
            frappe.msgprint({
                title: __('Invalid Experience'),
                message: __('Total Experience cannot be negative'),
                indicator: 'red'
            });
            $(this).val('0');
            return;
        }
        
        if (experience > 50) {
            frappe.msgprint({
                title: __('Invalid Experience'),
                message: __('Total Experience cannot exceed 50 years'),
                indicator: 'red'
            });
            $(this).focus();
            return;
        }
    });
    
    // Current CTC validation
    $(document).on('blur', 'input[data-fieldname="employment_current_ctc"]', function() {
        const ctc = parseFloat($(this).val());
        if (isNaN(ctc)) return;
        
        if (ctc < 0) {
            frappe.msgprint({
                title: __('Invalid CTC'),
                message: __('Current CTC cannot be negative'),
                indicator: 'red'
            });
            $(this).val('');
            return;
        }
    });
    
    // Expected CTC validation
    $(document).on('blur', 'input[data-fieldname="employment_expected_ctc"]', function() {
        const expectedCtc = parseFloat($(this).val());
        if (isNaN(expectedCtc)) return;
        
        if (expectedCtc < 0) {
            frappe.msgprint({
                title: __('Invalid CTC'),
                message: __('Expected CTC cannot be negative'),
                indicator: 'red'
            });
            $(this).val('');
            return;
        }
        
        // Check against current CTC if provided
        const currentCtc = parseFloat($('input[data-fieldname="employment_current_ctc"]').val());
        if (!isNaN(currentCtc) && currentCtc > 0) {
            if (expectedCtc < currentCtc * 0.8) {
                frappe.msgprint({
                    title: __('Warning'),
                    message: __('Expected CTC is significantly lower than Current CTC. Please verify.'),
                    indicator: 'orange'
                });
            }
        }
    });
    
    // 6. Employment History - Notice Period validation
    $(document).on('blur', 'input[data-fieldname="employment_notice_period"]', function() {
        const noticePeriod = parseInt($(this).val());
        if (isNaN(noticePeriod)) return;
        
        if (noticePeriod < 0) {
            frappe.msgprint({
                title: __('Invalid Notice Period'),
                message: __('Notice Period cannot be negative'),
                indicator: 'red'
            });
            $(this).val('0');
            return;
        }
        
        if (noticePeriod > 180) {
            frappe.msgprint({
                title: __('Invalid Notice Period'),
                message: __('Notice Period cannot exceed 180 days'),
                indicator: 'red'
            });
            $(this).focus();
            return;
        }
    });
    
    // Employment dates validation
    $(document).on('change', 'input[data-fieldname="employment_end_date"]', function() {
        const startDate = $('input[data-fieldname="employment_start_date"]').val();
        const endDate = $(this).val();
        
        if (startDate && endDate) {
            const start = new Date(startDate);
            const end = new Date(endDate);
            
            if (end < start) {
                frappe.msgprint({
                    title: __('Invalid Date'),
                    message: __('End Date cannot be before Start Date'),
                    indicator: 'red'
                });
                $(this).val('');
                return;
            }
            
            // Check if end date is in the future
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            if (end > today) {
                frappe.msgprint({
                    title: __('Warning'),
                    message: __('End Date is in the future. If you are still employed, leave this field blank.'),
                    indicator: 'orange'
                });
            }
        }
    });
    
    // 10. Portfolio URL Validation
    $(document).on('blur', 'input[data-fieldname="portfolio"]', function() {
        const url = $(this).val().trim();
        if (!url) return; // Optional field
        
        // Basic URL validation
        const urlPattern = /^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$/;
        if (!urlPattern.test(url)) {
            frappe.msgprint({
                title: __('Invalid URL'),
                message: __('Please enter a valid URL (e.g., https://example.com)'),
                indicator: 'red'
            });
            $(this).focus();
            return;
        }
        
        // Ensure it starts with http:// or https://
        if (!url.startsWith('http://') && !url.startsWith('https://')) {
            const correctedUrl = 'https://' + url;
            $(this).val(correctedUrl);
            frappe.msgprint({
                title: __('URL Corrected'),
                message: __('Added https:// to your URL'),
                indicator: 'blue'
            });
        }
    });
    
    // 11. Degree/Qualification validation
    $(document).on('blur', 'input[data-fieldname="degree"]', function() {
        const degree = $(this).val().trim();
        if (!degree) return; // Optional field
        
        if (degree.length < 2) {
            frappe.msgprint({
                title: __('Invalid Degree'),
                message: __('Degree must be at least 2 characters'),
                indicator: 'red'
            });
            $(this).focus();
            return;
        }
    });
    
    // 12. Pre-Submit Validation
    $(document).on('submit', '.web-form', function(e) {
        let errors = [];
        
        // Check required fields
        const applicantName = $('input[data-fieldname="applicant_name"]').val();
        const email = $('input[data-fieldname="email_id"]').val();
        const phone = $('input[data-fieldname="phone_number"]').val();
        const maritalStatus = $('select[data-fieldname="marital_status"]').val();
        const cityState = $('input[data-fieldname="city_state"]').val();
        const jobOpening = $('input[data-fieldname="job_requisition"]').val();
        const applicationDate = $('input[data-fieldname="application_date"]').val();
        const totalExperience = $('input[data-fieldname="total_experience"]').val();
        const source = $('select[data-fieldname="source"]').val();
        
        if (!applicantName || applicantName.trim().length < 2) {
            errors.push('Applicant Name is required (minimum 2 characters)');
        }
        
        if (!email || !email.includes('@')) {
            errors.push('Valid Email Address is required');
        }
        
        if (!phone || phone.trim().length < 10) {
            errors.push('Valid Phone Number is required (minimum 10 digits)');
        }
        
        if (!maritalStatus) {
            errors.push('Marital Status is required');
        }
        
        if (!cityState || cityState.trim().length < 2) {
            errors.push('City / State is required');
        }
        
        if (!jobOpening) {
            errors.push('Job Opening is required');
        }
        
        if (!applicationDate) {
            errors.push('Application Date is required');
        }
        
        if (!totalExperience) {
            errors.push('Total Experience is required');
        }
        
        if (!source) {
            errors.push('Source is required');
        }
        
        // Check resume attachment
        const resumeInput = $('input[data-fieldname="resume_attachment"]')[0];
        const hasResume = resumeInput && (resumeInput.files.length > 0 || $(resumeInput).attr('data-file-url'));
        if (!hasResume) {
            errors.push('Resume/CV is required');
        } else if (resumeInput.files.length > 0) {
            // Validate the file type before submit
            const file = resumeInput.files[0];
            const fileName = file.name.toLowerCase();
            const fileExtension = fileName.substring(fileName.lastIndexOf('.'));
            const allowedExtensions = ['.pdf', '.doc', '.docx'];
            
            if (!allowedExtensions.includes(fileExtension)) {
                errors.push('Resume/CV must be PDF or Word document (.pdf, .doc, .docx). Current: ' + file.name);
            }
            
            // Also check MIME type
            const allowedMimeTypes = [
                'application/pdf',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            ];
            
            if (!allowedMimeTypes.includes(file.type)) {
                errors.push('Invalid resume file type detected. Only PDF and Word documents are allowed.');
            }
        }
        
<<<<<<< HEAD
        // If there are errors, show them and prevent submit
        if (errors.length > 0) {
            e.preventDefault();
            frappe.msgprint({
                title: __('Validation Errors'),
                message: '<ul><li>' + errors.join('</li><li>') + '</li></ul>',
                indicator: 'red'
            });
            return false;
        }
=======
        waitForWebForm(function() {
            function setJobRequisition() {
                if (!frappe.web_form) return false;
                
                try {
                    // CRITICAL: Set job_requisition (this is the required field)
                    if (frappe.web_form.doc && jobTitle) {
                        frappe.web_form.doc.job_requisition = jobTitle;
                        console.log('✅ Set job_requisition in doc:', jobTitle);
                    }
                    
                    // Also set job_title for compatibility
                    if (frappe.web_form.doc && jobTitle) {
                        frappe.web_form.doc.job_title = jobTitle;
                    }
                    
                    if (frappe.web_form.doc && sourceValue) {
                        frappe.web_form.doc.source = sourceValue;
                    }
                    
                    // Set via web form API - job_requisition (the actual form field)
                    if (frappe.web_form.set_value) {
                        if (jobTitle) {
                            frappe.web_form.set_value('job_requisition', jobTitle);
                            frappe.web_form.set_value('job_title', jobTitle);
                        }
                        if (sourceValue) {
                            frappe.web_form.set_value('source', sourceValue);
                        }
                    }
                    
                    // Set via field if available
                    if (frappe.web_form.fields_dict) {
                        // Set job_requisition field (the visible form field)
                        if (frappe.web_form.fields_dict.job_requisition && jobTitle) {
                            const field = frappe.web_form.fields_dict.job_requisition;
                            if (field) {
                                if (field.set_value) {
                                    field.set_value(jobTitle);
                                }
                                if (field.$input) {
                                    field.$input.val(jobTitle);
                                    field.$input.trigger('change');
                                }
                            }
                        }
                        // Also set job_title if field exists
                        if (frappe.web_form.fields_dict.job_title && jobTitle) {
                            const field = frappe.web_form.fields_dict.job_title;
                            if (field && field.set_value) {
                                field.set_value(jobTitle);
                            }
                        }
                        if (frappe.web_form.fields_dict.source && sourceValue) {
                            const field = frappe.web_form.fields_dict.source;
                            if (field) {
                                if (field.set_value) {
                                    field.set_value(sourceValue);
                                }
                                if (field.df) {
                                    field.df.read_only = 1;
                                }
                                if (field.$input) {
                                    field.$input.val(sourceValue);
                                    field.$input.prop('disabled', true);
                                    field.$input.trigger('change');
                                }
                                if (field.refresh) {
                                    field.refresh();
                                }
                            }
                        }
                    }
                    
                    return true;
                } catch (e) {
                    console.error('❌ Error setting job_requisition:', e);
                    return false;
                }
            }
            
            // Set immediately
            setJobRequisition();
            
            // Retry a few times
            let attempts = 0;
            const retry = setInterval(function() {
                attempts++;
                if (setJobRequisition() || attempts >= 5) {
                    clearInterval(retry);
                }
            }, 300);
            
            // CRITICAL: Ensure job_requisition before submit
            $(document).on('submit', '.web-form', function(e) {
                if (frappe.web_form && frappe.web_form.doc) {
                    if (jobTitle) {
                        frappe.web_form.doc.job_requisition = jobTitle;
                        frappe.web_form.doc.job_title = jobTitle;
                        console.log('✅ Set job_requisition before submit:', jobTitle);
                    }
                    if (sourceValue) {
                        frappe.web_form.doc.source = sourceValue;
                    }
                }
            });
            
            // Intercept save method safely
            if (frappe.web_form && frappe.web_form.save) {
                const originalSave = frappe.web_form.save.bind(frappe.web_form);
                frappe.web_form.save = function() {
                    if (this.doc) {
                        if (jobTitle) {
                            this.doc.job_requisition = jobTitle;
                            this.doc.job_title = jobTitle;
                        }
                        if (sourceValue) {
                            this.doc.source = sourceValue;
                        }
                    }
                    return originalSave();
                };
            }
        });
>>>>>>> 7d11622 (Source urls)
    });
});"""
	
	# Combine scripts
	web_form.client_script = existing_script + new_script
	web_form.save(ignore_permissions=True)
	frappe.db.commit()
	
	print("✅ Updated job-application web form client script")

if __name__ == "__main__":
	frappe.init(site="alpinos.local")
	frappe.connect()
	update_web_form_script()
