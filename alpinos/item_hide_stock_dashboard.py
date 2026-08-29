"""Hide the "Stock Levels" section from the Item form dashboard via a client script."""

import frappe

ITEM_HIDE_STOCK_SCRIPT = r"""
frappe.ui.form.on('Item', {
    refresh(frm) {
        // The dashboard container is frm.dashboard.parent (v15 FormDashboard sets .parent,
        // NOT .wrapper). Match the section by its head text; use the translated label so it
        // works in non-English locales too.
        const target = __('Stock Levels');
        const hide_stock_levels = () => {
            try {
                const root = (frm.dashboard && frm.dashboard.parent)
                    ? $(frm.dashboard.parent) : frm.$wrapper;
                if (!root) return;
                root.find('.form-dashboard-section').each(function () {
                    const label = ($(this).find('.section-head').first().text() || '').trim();
                    if (label === target || label === 'Stock Levels') {
                        $(this).hide();
                    }
                });
            } catch (e) { console && console.warn && console.warn('hide stock levels failed', e); }
        };
        hide_stock_levels();
        // ERPNext loads the stock dashboard async, so watch the dashboard node and re-hide
        // whenever a section appears (more reliable than fixed timers alone).
        try {
            const node = (frm.dashboard && frm.dashboard.parent)
                ? frm.dashboard.parent : (frm.$wrapper && frm.$wrapper[0]);
            if (node && window.MutationObserver) {
                if (frm.__stock_hide_observer) frm.__stock_hide_observer.disconnect();
                const obs = new MutationObserver(hide_stock_levels);
                obs.observe(node, { childList: true, subtree: true });
                frm.__stock_hide_observer = obs;
                setTimeout(() => obs.disconnect(), 8000);  // stop once the async load settles
            }
        } catch (e) {}
        setTimeout(hide_stock_levels, 600);
        setTimeout(hide_stock_levels, 1800);
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
