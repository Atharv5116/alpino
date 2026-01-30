"""
Job Opening Automation
Handles auto-population of job_application_route and other automation
"""

import frappe
from frappe import _
from frappe.utils import get_url
from urllib.parse import urlencode


def set_job_application_route(doc, method=None):
	"""
	Auto-populate job_application_route with the web form base route
	The template will append /new?job_title={job_opening_id}
	"""
	if not doc.job_application_route and doc.publish:
		# Set the base web form route (template will add /new?job_title=...)
		doc.job_application_route = "job-application"
		
		frappe.logger().info(f"Set job_application_route for {doc.name}: job-application")


def ensure_job_application_route(doc, method=None):
	"""
	Ensure job_application_route is set when publish is enabled
	"""
	if doc.publish and not doc.job_application_route:
		# Set the base web form route (template will add /new?job_title=...)
		frappe.db.set_value("Job Opening", doc.name, "job_application_route", "job-application", update_modified=False)
		doc.job_application_route = "job-application"
		
		frappe.logger().info(f"Updated job_application_route for {doc.name}: job-application")


def set_source_urls(doc, method=None):
	"""
	Populate source-specific application URLs for the Job Opening
	"""
	if not doc.name:
		return
	
	route = doc.job_application_route or "job-application"
	base_url = get_url(f"/{route}/new")
	
	def build_url(source_value):
		query = urlencode({"job_title": doc.name, "source": source_value})
		return f"{base_url}?{query}"
	
	# Only set if fields exist to avoid errors in older sites
	if hasattr(doc, "source_linkedin"):
		doc.source_linkedin = build_url("LinkedIn")
	
	if hasattr(doc, "source_indeed"):
		doc.source_indeed = build_url("Indeed")
	
	if hasattr(doc, "source_naukari"):
		doc.source_naukari = build_url("Naukari.com")
