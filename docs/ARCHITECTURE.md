Architecture Documentation: Alpinos

1. Introduction
Alpinos (module: Alpinos Development) is a custom Frappe application built on top of ERPNext and HRMS. It handles sales-order entry and dispatch, buyer and customer masters, pick list to delivery note workflows, HR attendance, employee onboarding, and invoicing.

Our golden rule: we never modify core files in ERPNext, HRMS, or Frappe. Every custom behavior goes through standard framework extension points, all wired up in alpinos/hooks.py. Start there when looking for how things fit together.

2. Extension Mechanisms
When adding new features, use these extension mechanisms. Pick the cleanest one that gets the job done, in this order:

Priority 1: Doc-event handler (doc_events). Add validations or side effects on a doctype's lifecycle (validate, on_submit).
Priority 2: Controller subclass (override_doctype_class). Change how a doctype behaves (override methods, skip stock checks).
Priority 3: Custom fields and Property Setters (after_migrate + fixtures). Add fields or tweak field properties on standard doctypes.
Priority 4: Whitelisted-method override (override_whitelisted_methods). Replace specific server-side API endpoints.
Priority 5: Monkey-patch (boot_session / before_request). Last resort for patching vendor functions you can't reach otherwise.

2.1 Doc-Event Handlers
We map doctype lifecycle events to specific handlers. For example, the Sales Order validate event runs an 8-function pipeline to enforce business rules. Keep these handlers in hooks.py files (like pick_list_hooks.py) or dedicated feature modules.

2.2 Controller Subclasses
We replace standard Python controllers with subclasses so frappe.get_doc loads our custom logic. These live in alpinos/overrides/ and generally follow an extend-and-delegate pattern (adding rules around super() or skipping standard checks).

2.3 Schema Management
We don't manually edit the site database for core doctypes. Schema changes are managed in code and re-applied every time we run bench migrate. 
1. Programmatic custom fields: Executed via after_migrate from custom_fields.py. This is the primary way we add fields.
2. Property setters: Used to override field attributes without touching the DocField.
3. Patches: Run once per site for data migrations or ordering-sensitive fixes.

(Note: We only use static fixtures in fixtures/custom_field.json for a few specific doctypes. Almost everything else is programmatic.)

2.4 Monkey-Patches
Monkey-patching is our last resort. We only use this when overrides or custom fields don't cut it. These patches are re-applied during boot_session or before_request to make sure they stick.

3. Custom Doctypes
We have around 50 custom doctypes in alpinos_development/doctype/, split across these domains:

- Customer & Buyer: buyer_master, buyer_address, buyer_item, alpino_customer_type.
- Sales & Dispatch: post_dispatch, sales_order_marketing_freebie, product_bundle_mapping.
- HR & Attendance: monthly_attendance_batch, attendance_request_detail, essl_settings, work_from_home_request, late_entry_threshold.
- Onboarding: branch_policy_access, policy, experience.
- Integrations: invoice_sync_settings, invoice_sync_log.

4. Frontend & Views

4.1 Desk Pages (SPAs)
We use an SPA-in-a-page pattern for our custom desk pages (like sales_order_entry and dispatch_report). 
- Registered via page.json. 
- Rendered using frappe.ui.make_app_page with co-located .html templates and a JS controller.
- We use native Frappe controls (frappe.ui.form.make_control) so they look and feel like the rest of the desk.

4.2 Reports
All our reports are standard Script Reports. They return columns and data dynamically. For complex workflows that span multiple stages, we use shared wrappers to keep the logic consistent.

5. API Layer
Our RPC surface is built with @frappe.whitelist() functions, called from the frontend via frappe.call:
- Shared Services: Reusable modules (e.g., sales_order_api.py) used across different pages.
- Page Controllers: Dedicated endpoints specific to a single page's workflow.

6. Automation & Background Jobs
- Scheduler Events: Daily and cron jobs for things like onboarding emails, syncs, and auto-attendance.
- Workflow Engine: We have a custom state engine for complex transitions (like Sales Order to Pick List to Delivery Note), separate from Frappe's standard Workflow feature.
- Attendance Automation: Background jobs that handle check-in healing, default markings, and request resolution.

7. Folder Structure
alpinos/
  hooks.py                     (Start here to see how everything is wired)
  *_api.py                     (Whitelisted RPC endpoints)
  *_hooks.py                   (Doc-event handlers)
  *_custom_fields.py           (Schema definitions and migrations)
  *_client_script.py           (Injected client-side JS)
  *_workflow_setup.py          (Programmatic workflow records)
  overrides/                   (Controller subclasses and monkey-patches)
  workflow_engine.py           (Custom state engine logic)
  patches/                     (One-time site migrations)
  public/                      (Static assets like CSS, JS)
  fixtures/                    (Static schema fixtures)
  alpinos_development/
    doctype/                   (Custom domain data models)
    page/                      (Custom SPA desk pages)
    report/                    (Script reports)

8. Dev Rules & Gotchas
1. Schema Changes: Use after_migrate to add fields. Update the right custom_fields.py file instead of editing the database by hand.
2. Fixtures: Keep in mind that fixtures re-sync after patches. If you want to delete a fixtured field, you have to write a delete patch and drop the fixture entry.
3. JS Caching: If you change a client script (doctype_js), you need to run bench clear-cache for it to show up.
4. Permissions: Raw database queries (get_all, db.sql) bypass our row-level visibility rules. Always test data access as a restricted user.
5. Overrides over Patches: Whenever possible, use a controller subclass and super() instead of monkey-patching. If you absolutely have to patch, re-apply it during boot_session.
6. Deploying Schema Changes: The order matters: bench migrate, then bench build, then bench restart.
