"""Hide the "Stock Levels" section from the Item form dashboard.

ERPNext's item.js adds a form-dashboard section titled "Stock Levels" (warehouse-wise
stock) asynchronously on refresh. We hide it with an Item Form client script — the
async load means we re-hide a couple of times after refresh so we catch it once rendered.
Installed on after_migrate (see hooks.py).
"""

import frappe

ITEM_HIDE_STOCK_SCRIPT = r"""
frappe.ui.form.on('Item', {
    refresh(frm) {
        const hide_stock_levels = () => {
            try {
                frm.dashboard.wrapper.find('.form-dashboard-section').each(function () {
                    const label = ($(this).find('.section-head, .h6').first().text() || '').trim();
                    if (label === 'Stock Levels') {
                        $(this).hide();
                    }
                });
            } catch (e) {}
        };
        // ERPNext loads the stock dashboard async (frappe.require), so re-hide a few times.
        hide_stock_levels();
        setTimeout(hide_stock_levels, 500);
        setTimeout(hide_stock_levels, 1500);
        setTimeout(hide_stock_levels, 3000);
    }
});
"""


def create_item_hide_stock_dashboard_client_script():
    """Create or update the 'Item - Hide Stock Dashboard' client script."""
    script_name = "Item - Hide Stock Dashboard"
    if frappe.db.exists("Client Script", {"name": script_name}):
        doc = frappe.get_doc("Client Script", script_name)
        doc.script = ITEM_HIDE_STOCK_SCRIPT
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        print(f"✅ Updated client script: {script_name}")
    else:
        frappe.get_doc(
            {
                "doctype": "Client Script",
                "name": script_name,
                "dt": "Item",
                "view": "Form",
                "script": ITEM_HIDE_STOCK_SCRIPT,
                "enabled": 1,
                "module": "Alpinos Development",
            }
        ).insert(ignore_permissions=True)
        print(f"✅ Created client script: {script_name}")
