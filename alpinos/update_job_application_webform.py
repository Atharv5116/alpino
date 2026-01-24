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
    
    if (!jobTitle) return;
    
    console.log('🔍 Found job_title in URL:', jobTitle);
    
    // Wait for Frappe and web form to be ready
    frappe.ready(function() {
        // Wait for web form to be initialized
        function waitForWebForm(callback) {
            if (frappe.web_form && frappe.web_form.doc !== undefined) {
                callback();
            } else {
                setTimeout(function() {
                    waitForWebForm(callback);
                }, 100);
            }
        }
        
        waitForWebForm(function() {
            function setJobRequisition() {
                if (!frappe.web_form) return false;
                
                try {
                    // CRITICAL: Set job_requisition (this is the required field)
                    if (frappe.web_form.doc) {
                        frappe.web_form.doc.job_requisition = jobTitle;
                        console.log('✅ Set job_requisition in doc:', jobTitle);
                    }
                    
                    // Also set job_title for compatibility
                    if (frappe.web_form.doc) {
                        frappe.web_form.doc.job_title = jobTitle;
                    }
                    
                    // Set via web form API - job_requisition (the actual form field)
                    if (frappe.web_form.set_value) {
                        frappe.web_form.set_value('job_requisition', jobTitle);
                        frappe.web_form.set_value('job_title', jobTitle);
                    }
                    
                    // Set via field if available
                    if (frappe.web_form.fields_dict) {
                        // Set job_requisition field (the visible form field)
                        if (frappe.web_form.fields_dict.job_requisition) {
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
                        if (frappe.web_form.fields_dict.job_title) {
                            const field = frappe.web_form.fields_dict.job_title;
                            if (field && field.set_value) {
                                field.set_value(jobTitle);
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
                    frappe.web_form.doc.job_requisition = jobTitle;
                    frappe.web_form.doc.job_title = jobTitle;
                    console.log('✅ Set job_requisition before submit:', jobTitle);
                }
            });
            
            // Intercept save method safely
            if (frappe.web_form && frappe.web_form.save) {
                const originalSave = frappe.web_form.save.bind(frappe.web_form);
                frappe.web_form.save = function() {
                    if (this.doc) {
                        this.doc.job_requisition = jobTitle;
                        this.doc.job_title = jobTitle;
                    }
                    return originalSave();
                };
            }
        });
    });
})();"""
	
	# Combine scripts
	web_form.client_script = existing_script + new_script
	web_form.save(ignore_permissions=True)
	frappe.db.commit()
	
	print("✅ Updated job-application web form client script")

if __name__ == "__main__":
	frappe.init(site="alpinos.local")
	frappe.connect()
	update_web_form_script()
