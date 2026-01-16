# Vacancy Module - Workflow Implementation

**Date:** 2025-01-27  
**App:** alpinos  
**DocType:** Job Requisition

---

## ✅ WORKFLOW IMPLEMENTATION COMPLETE

### Workflow Name
**Job Requisition Approval Workflow**

### Workflow States (9 states)

| State | Doc Status | Description | Editable By |
|-------|------------|-------------|-------------|
| **Draft** | 0 (Saved) | Vacancy created but not submitted | All (Requestor) |
| **Pending Reporting Manager Approval** | 1 (Submitted) | Awaiting first approval | Reporting Manager |
| **Pending HOD Approval** | 1 (Submitted) | Awaiting HOD/Management approval | HOD |
| **Pending HR Approval** | 1 (Submitted) | Awaiting HR approval | HR Manager |
| **Approved** | 1 (Submitted) | Fully approved | HR Manager |
| **Live** | 1 (Submitted) | Published on website | HR Manager |
| **Rejected** | 0 (Cancelled) | Requisition rejected | All |
| **Returned to Requestor** | 0 (Returned) | Sent back for modification | All (Requestor) |
| **On Hold** | 1 (Submitted) | Temporarily paused | HR Manager |

---

## 🔄 WORKFLOW TRANSITIONS

### Forward Flow (Approval Chain)

1. **Draft → Pending Reporting Manager Approval**
   - Action: "Submit for Approval"
   - Allowed: All (Requestor)
   - Self-approval: Yes

2. **Pending Reporting Manager Approval → Pending HOD Approval**
   - Action: "Approve"
   - Allowed: Reporting Manager
   - Self-approval: No

3. **Pending Reporting Manager Approval → Pending HR Approval** (Skip HOD)
   - Action: "Approve (Skip HOD)"
   - Allowed: Reporting Manager
   - Self-approval: No

4. **Pending HOD Approval → Pending HR Approval**
   - Action: "Approve"
   - Allowed: HOD
   - Self-approval: No

5. **Pending HR Approval → Approved**
   - Action: "Approve"
   - Allowed: HR Manager
   - Self-approval: No

6. **Approved → Live**
   - Action: "Publish"
   - Allowed: HR Manager
   - Self-approval: Yes

### Rejection Flow

7. **Any Approval State → Rejected**
   - Actions: "Reject"
   - Allowed: Reporting Manager / HOD / HR Manager
   - Self-approval: No

### Return to Requestor Flow

8. **Any Approval State → Returned to Requestor**
   - Actions: "Return to Requestor"
   - Allowed: Reporting Manager / HOD / HR Manager
   - Self-approval: No

9. **Returned to Requestor → Pending Reporting Manager Approval**
   - Action: "Resubmit"
   - Allowed: All (Requestor)
   - Self-approval: Yes

### On Hold Flow

10. **Any Approval State → On Hold**
    - Actions: "Put on Hold"
    - Allowed: Reporting Manager / HOD / HR Manager
    - Self-approval: Yes (for HR Manager)

11. **On Hold → Resume**
    - Actions: "Resume" / "Resume to HOD" / "Resume to HR"
    - Allowed: HR Manager
    - Self-approval: Yes

---

## 🤖 AUTOMATION SCRIPTS

### 1. Approval Tracking
**File:** `job_requisition_automation.py`  
**Function:** `update_approval_fields()`

- **Trigger:** Before save
- **Action:** Auto-populates `approved_on` and `approved_by` when status = "Approved"
- **Logic:**
  - Sets `approved_on` = current datetime
  - Sets `approved_by` = current user

### 2. Job Opening Creation
**File:** `job_requisition_automation.py`  
**Function:** `create_job_opening_on_approval()`

- **Trigger:** On update
- **Action:** Auto-creates Job Opening when status = "Approved"
- **Logic:**
  - Checks if Job Opening already exists
  - Creates Job Opening using `make_job_opening()` function
  - Maps additional fields:
    - `location` → Job Opening location
    - `ctc_upper_range` → Job Opening upper_range
    - `hiring_deadline` → Job Opening closes_on
  - Saves Job Opening

### 3. Job Opening Publishing
**File:** `job_requisition_automation.py`  
**Function:** `publish_job_opening_on_live()`

- **Trigger:** On update
- **Action:** Auto-publishes Job Opening when status = "Live"
- **Logic:**
  - Finds associated Job Opening
  - Sets `publish` = 1
  - Sets `status` = "Open"

### 4. Status Synchronization
**File:** `job_requisition_automation.py`  
**Function:** `sync_status_with_job_opening()`

- **Trigger:** On update
- **Action:** Syncs status between Job Requisition and Job Opening
- **Status Mapping:**
  - Approved → Open
  - Live → Open
  - Rejected → Closed
  - On Hold → Open

---

## 📋 REQUIRED ROLES

The workflow requires the following roles to be created/configured:

1. **Reporting Manager** - For first level approval
2. **HOD** - For second level approval (optional)
3. **HR Manager** - For final approval and publishing

**Note:** These roles should be assigned to users based on their position in the organization hierarchy.

---

## 🚀 DEPLOYMENT STEPS

### 1. Run Migration
```bash
cd /home/frappe/frappe-bench
bench migrate
```

This will:
- Create custom fields (if not done)
- Create workflow
- Set up automation hooks

### 2. Verify Workflow
- Go to: Workflow → Job Requisition Approval Workflow
- Verify all states and transitions are correct
- Check that workflow is active

### 3. Assign Roles
- Assign "Reporting Manager" role to appropriate users
- Assign "HOD" role to department heads
- Assign "HR Manager" role to HR team

### 4. Test Workflow
1. Create a new Job Requisition
2. Set status to "Draft"
3. Submit for approval
4. Test each approval step
5. Verify Job Opening is created on approval
6. Verify Job Opening is published when status = "Live"

---

## 📊 WORKFLOW DIAGRAM

```
                    [Draft]
                       |
                       | Submit for Approval
                       ↓
    [Pending Reporting Manager Approval]
                       |
        ┌──────────────┼──────────────┐
        |              |              |
    Approve      Approve (Skip)    Reject/Return/Hold
        |              |              |
        ↓              ↓              ↓
[Pending HOD]  [Pending HR]    [Rejected/Returned/On Hold]
    Approval      Approval
        |
        | Approve
        ↓
[Pending HR Approval]
        |
        | Approve
        ↓
    [Approved]
        |
        | Publish
        ↓
     [Live]
```

---

## ⚠️ NOTES

1. **Workflow State Field:** Uses existing `status` field (not a separate workflow_state field)
2. **Status Override:** Workflow overrides status field (`override_status = 1`)
3. **Email Alerts:** Enabled (`send_email_alert = 1`)
4. **Self-Approval:** Disabled for approval actions (except for HR Manager on Hold)
5. **Job Opening Creation:** Only happens once when status first becomes "Approved"
6. **Status Sync:** Bidirectional sync between Job Requisition and Job Opening

---

## ✅ CHECKLIST

- [x] Workflow states defined (9 states)
- [x] Workflow transitions defined (20+ transitions)
- [x] Approval tracking automation
- [x] Job Opening creation automation
- [x] Job Opening publishing automation
- [x] Status synchronization automation
- [x] Hooks configured
- [ ] Roles created and assigned
- [ ] Workflow tested end-to-end
- [ ] Email templates configured (optional)

---

## 🔄 NEXT STEPS

1. **Create/Assign Roles:**
   - Reporting Manager
   - HOD
   - HR Manager

2. **Test Workflow:**
   - Create test Job Requisition
   - Test approval flow
   - Verify automations

3. **Email Templates (Optional):**
   - Create email templates for each workflow state
   - Configure email notifications

4. **Permissions:**
   - Set up role-based permissions for Job Requisition
   - Configure who can create/edit/view

---

**Status:** Ready for Testing  
**Last Updated:** 2025-01-27
