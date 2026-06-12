const root = root_element;
const monthLabel = root.querySelector("#cal-month-label");
const grid = root.querySelector("#alp-att-cal-grid");
const prevBtn = root.querySelector("#cal-prev-month");
const nextBtn = root.querySelector("#cal-next-month");

let current = new Date();

// ── CONFIG ──────────────────────────────────────────────────
// Grace period in minutes after shift start before showing "Late"
var GRACE_PERIOD_MINUTES = 15;

// Shift start time (HH:MM) — used to detect late after grace period
var SHIFT_START = "10:00";

// Shift end time (HH:MM) — used to detect early leaving
var SHIFT_END = "18:30";

// Required working hours per day in minutes
var MIN_HOURS_WEEKDAY  = 480;  // 8h  — Mon–Fri
var REQUIRED_DURATION  = 495;  // 8h15m — minimum gap between check-in and check-out
var MIN_HOURS_SATURDAY  = 240; // 4h  — Saturday minimum for Present
var HALF_DAY_THRESHOLD  = 360; // 6h  — below this is Half Day
var ABSENT_THRESHOLD    = 240; // 4h  — below this is Absent
// ────────────────────────────────────────────────────────────

function changeMonth(delta) {
  const year = current.getFullYear();
  const month = current.getMonth() + 1 + delta;
  const d = new Date(year, month - 1, 1);
  loadMonth(d.getFullYear(), d.getMonth() + 1);
}

prevBtn.addEventListener("click", function () { changeMonth(-1); });
nextBtn.addEventListener("click", function () { changeMonth(1); });

function loadMonth(year, month) {
  current = new Date(year, month - 1, 1);
  monthLabel.innerText = current.toLocaleString("default", { month: "long", year: "numeric" });

  frappe.call({
    method: "alpinos.attendance_widget.get_monthly_attendance",
    args: { year: year, month: month },
    freeze: true,
    freeze_message: "Loading attendance...",
    callback: function (r) {
      if (r.exc) {
        frappe.msgprint("Could not load attendance calendar. Please try again.");
        return;
      }
      const data = r.message || {};
      renderCalendar(data.days || {}, year, month);
    },
  });
}

// ── Helpers ─────────────────────────────────────────────────

function timeToHHMM(t) {
  if (t == null || t === undefined || t === "") return "—";
  var s = String(t).trim();
  if (s === "—") return "—";
  if (s.indexOf("T") !== -1) s = s.split("T")[1] || s;
  if (s.indexOf(" ") !== -1) s = s.split(" ")[s.split(" ").length - 1] || s;
  var parts = s.split(":");
  if (parts.length >= 2) return parts[0] + ":" + parts[1];
  return s || "—";
}

function formatWorked(minutes) {
  if (minutes == null || minutes < 0) return "";
  var h = Math.floor(minutes / 60);
  var m = minutes % 60;
  if (h > 0 && m > 0) return h + "h " + m + "m";
  if (h > 0) return h + "h";
  return m + "m";
}

function formatDateKey(year, month, day) {
  const m = String(month).padStart(2, "0");
  const d = String(day).padStart(2, "0");
  return `${year}-${m}-${d}`;
}

// Convert "HH:MM" or full datetime string → total minutes from midnight
function timeStringToMinutes(t) {
  var hhmm = timeToHHMM(t);
  if (!hhmm || hhmm === "—") return null;
  var parts = hhmm.split(":");
  if (parts.length < 2) return null;
  return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
}

// Saturday = 4h, all other days = 8h
function getMinRequired(dateKey) {
  var d = new Date(dateKey);
  return d.getDay() === 6 ? MIN_HOURS_SATURDAY : MIN_HOURS_WEEKDAY;
}

// ── Late check: check_in > SHIFT_START + GRACE_PERIOD_MINUTES ──
function isLate(item) {
  var checkInMins = timeStringToMinutes(item.check_in);
  if (checkInMins === null) return !!item.late_coming;
  var parts       = SHIFT_START.split(":");
  var shiftMins   = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
  var graceCutoff = shiftMins + GRACE_PERIOD_MINUTES;
  return checkInMins > graceCutoff;
}

// ── Early check: (check_out - check_in) < required duration ──
function isEarlyLeaving(item, dateKey) {
  var checkInMins  = timeStringToMinutes(item.check_in);
  var checkOutMins = timeStringToMinutes(item.check_out);
  if (checkInMins === null || checkOutMins === null) return !!item.early_leaving;
  var duration    = checkOutMins - checkInMins;
  var isSaturday  = dateKey ? (new Date(dateKey).getDay() === 6) : false;
  var required    = isSaturday ? MIN_HOURS_SATURDAY : REQUIRED_DURATION;
  return duration < required;
}

// ── Is everything proper for this day? ──────────────────────
function isAllGood(status, item, dateKey) {
  if (status !== "Present" && status !== "Work From Home") return false;
  var noCheckout  = !item.check_out || item.check_out === "";
  var shortHours  = item.worked_minutes != null && item.worked_minutes < getMinRequired(dateKey);
  var late        = isLate(item);
  var early       = isEarlyLeaving(item, dateKey);
  var geo         = !!item.out_of_geo;
  return !noCheckout && !shortHours && !late && !early && !geo;
}

// ── Cell background & border ─────────────────────────────────
function getDayStyle(status, isToday, item, dateKey) {
  var bg = "#f9fafb";
  var borderColor = "#e5e7eb";

  if (status === "Present") {
    var noCheckout = !item.check_out || item.check_out === "";
    var shortHours = item.worked_minutes != null && item.worked_minutes < getMinRequired(dateKey);
    if (noCheckout || shortHours) {
      bg          = "#fff3e0";
      borderColor = "#ffb74d";
    } else {
      bg          = "#ecfdf5";
      borderColor = "#a7f3d0";
    }
  } else if (status === "Work From Home") {
    bg          = "#eff6ff";
    borderColor = "#bfdbfe";
  } else if (status === "Absent") {
    if (item.check_in && item.check_in !== "") {
      bg          = "#fff3e0";
      borderColor = "#ffb74d";
    } else {
      bg          = "#fef2f2";
      borderColor = "#fca5a5";
    }
  } else if (status === "Half Day") {
    bg          = "#fefce8";
    borderColor = "#fde047";
  } else if (status === "On Leave") {
    bg          = "#f5f3ff";
    borderColor = "#ddd6fe";
  } else if (status === "Holiday") {
    bg          = "#f1f5f9";
    borderColor = "#cbd5e1";
  }

  var border = isToday ? "2px solid #3b82f6" : "1px solid " + borderColor;
  var shadow = isToday ? "0 0 0 1px rgba(59,130,246,0.25)" : "none";

  return (
    "border-radius:12px;padding:6px 6px;min-height:68px;display:flex;flex-direction:column;"
    + "gap:2px;align-items:flex-start;background:" + bg + ";border:" + border
    + ";box-shadow:" + shadow + ";box-sizing:border-box;cursor:pointer;"
    + "transition:transform 0.12s,box-shadow 0.12s;position:relative;"
  );
}

// ── Status icon ──────────────────────────────────────────────
function getStatusIcon(status, item, dateKey) {
  if (status === "Present") {
    var noCheckout = !item.check_out || item.check_out === "";
    var shortHours = item.worked_minutes != null && item.worked_minutes < getMinRequired(dateKey);
    if (noCheckout || shortHours) {
      return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
        + '<circle cx="7" cy="7" r="6.5" fill="#ffedd5" stroke="#fdba74" stroke-width="0.8"/>'
        + '<text x="7" y="10.5" text-anchor="middle" font-size="8" fill="#c2410c" font-weight="700">!</text>'
        + '</svg>';
    }
    return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
      + '<circle cx="7" cy="7" r="6.5" fill="#e2e8f0" stroke="#94a3b8" stroke-width="0.8"/>'
      + '<path d="M4 7l2 2 4-4" stroke="#16a34a" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>'
      + '</svg>';
  }
  if (status === "Work From Home") {
    return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
      + '<circle cx="7" cy="7" r="6.5" fill="#dbeafe" stroke="#93c5fd" stroke-width="0.8"/>'
      + '<path d="M3 7.5L7 4l4 3.5" stroke="#2563eb" stroke-width="1" stroke-linecap="round"/>'
      + '<path d="M4.5 7.5v3h2V9h1v1.5h2v-3" stroke="#2563eb" stroke-width="0.9" stroke-linecap="round" stroke-linejoin="round"/>'
      + '</svg>';
  }
  if (status === "Absent") {
    if (item.check_in && item.check_in !== "") {
      return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
        + '<circle cx="7" cy="7" r="6.5" fill="#ffedd5" stroke="#fdba74" stroke-width="0.8"/>'
        + '<text x="7" y="10.5" text-anchor="middle" font-size="8" fill="#c2410c" font-weight="700">!</text>'
        + '</svg>';
    }
    return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
      + '<circle cx="7" cy="7" r="6.5" fill="#fee2e2" stroke="#fca5a5" stroke-width="0.8"/>'
      + '<path d="M4.5 4.5l5 5M9.5 4.5l-5 5" stroke="#dc2626" stroke-width="1.4" stroke-linecap="round"/>'
      + '</svg>';
  }
  if (status === "Half Day") {
    return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
      + '<circle cx="7" cy="7" r="6.5" fill="#fef9c3" stroke="#fde047" stroke-width="0.8"/>'
      + '<text x="7" y="10" text-anchor="middle" font-size="9" fill="#854d0e">½</text>'
      + '</svg>';
  }
  if (status === "On Leave") {
    return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
      + '<circle cx="7" cy="7" r="6.5" fill="#ede9fe" stroke="#c4b5fd" stroke-width="0.8"/>'
      + '<text x="7" y="10" text-anchor="middle" font-size="9" fill="#6d28d9">L</text>'
      + '</svg>';
  }
  if (status === "Holiday") {
    return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">'
      + '<circle cx="7" cy="7" r="6.5" fill="#e2e8f0" stroke="#94a3b8" stroke-width="0.8"/>'
      + '<text x="7" y="10" text-anchor="middle" font-size="9" fill="#475569">H</text>'
      + '</svg>';
  }
  return "&#8212;";
}

// ── Render Calendar ──────────────────────────────────────────
function renderCalendar(days, year, month) {
  var first        = new Date(year, month - 1, 1);
  var last         = new Date(year, month, 0);
  var startWeekday = first.getDay();
  var totalDays    = last.getDate();

  grid.innerHTML = "";
  grid.setAttribute("style", "display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;max-width:760px;margin-left:auto;margin-right:auto;");

  for (var i = 0; i < startWeekday; i++) {
    var emptyCell = document.createElement("div");
    emptyCell.setAttribute("style", "min-height:68px;box-sizing:border-box;");
    grid.appendChild(emptyCell);
  }

  var today    = new Date();
  var todayKey = formatDateKey(today.getFullYear(), today.getMonth() + 1, today.getDate());

  for (var day = 1; day <= totalDays; day++) {
    var key    = formatDateKey(year, month, day);
    var item   = days[key] || {};
    var status = item.status || null;
    var isToday = key === todayKey;

    var cell = document.createElement("div");
    cell.setAttribute("style", getDayStyle(status, isToday, item, key));

    cell.addEventListener("mouseenter", function () {
      this.style.transform = "translateY(-2px)";
      this.style.boxShadow = "0 6px 14px rgba(0,0,0,0.08)";
    });
    cell.addEventListener("mouseleave", function () {
      this.style.transform = "translateY(0)";
      this.style.boxShadow = isToday ? "0 0 0 1px rgba(59,130,246,0.25)" : "none";
    });

    // Top row: day number + (WFH marker) + status icon
    var head = document.createElement("div");
    head.setAttribute("style", "display:flex;align-items:center;justify-content:space-between;gap:4px;min-width:0;width:100%;");

    var dayEl = document.createElement("span");
    dayEl.setAttribute("style", "font-weight:600;font-size:13px;color:#111827;");
    dayEl.textContent = String(day);

    var rightWrap = document.createElement("span");
    rightWrap.setAttribute("style", "display:inline-flex;align-items:center;gap:3px;flex-shrink:0;");

    // WFH marker: a Work From Home Request was applied for this day (even if Present)
    if (item.wfh) {
      var wfhMark = document.createElement("span");
      wfhMark.setAttribute("style", "font-size:12px;line-height:1;");
      wfhMark.setAttribute("title", "Work From Home");
      wfhMark.innerHTML = "&#127968;";
      rightWrap.appendChild(wfhMark);
    }

    var iconEl = document.createElement("span");
    iconEl.setAttribute("style", "font-size:13px;line-height:1;flex-shrink:0;");
    iconEl.innerHTML = getStatusIcon(status, item, key);
    rightWrap.appendChild(iconEl);

    head.appendChild(dayEl);
    head.appendChild(rightWrap);
    cell.appendChild(head);

    // ── Badge row — only show when something is wrong ──
    if (!isAllGood(status, item, key)) {

      var badgeRow = document.createElement("div");
      badgeRow.setAttribute("style", "display:flex;flex-wrap:wrap;gap:2px;margin-top:1px;");

      var canShowTimeBadge = (status === "Present" || status === "Work From Home" || (status === "Absent" && item.check_in && item.check_in !== ""));
      if (canShowTimeBadge && item.check_in && isLate(item)) {
        var bl = document.createElement("span");
        bl.setAttribute("style", "font-size:9px;padding:1px 4px;border-radius:4px;font-weight:500;line-height:1.4;display:inline-flex;align-items:center;gap:2px;background:#fef3c7;color:#92400e;white-space:nowrap;");
        bl.innerHTML = "&#128340; Late";
        badgeRow.appendChild(bl);
      }

      if (canShowTimeBadge && item.check_out && isEarlyLeaving(item, key)) {
        var be = document.createElement("span");
        be.setAttribute("style", "font-size:9px;padding:1px 4px;border-radius:4px;font-weight:500;line-height:1.4;display:inline-flex;align-items:center;gap:2px;background:#ede9fe;color:#5b21b6;white-space:nowrap;");
        be.innerHTML = "&#9201; Early";
        badgeRow.appendChild(be);
      }

      if (item.out_of_geo) {
        var bgBadge = document.createElement("span");
        bgBadge.setAttribute("style", "font-size:9px;padding:1px 4px;border-radius:4px;font-weight:500;line-height:1.4;display:inline-flex;align-items:center;gap:2px;background:#fce7f3;color:#9d174d;white-space:nowrap;");
        bgBadge.innerHTML = "&#128205; Geo";
        badgeRow.appendChild(bgBadge);
      }

      if (badgeRow.children.length > 0) {
        cell.appendChild(badgeRow);
      }
    }

    // Check-in / Check-out time row
    if (item.check_in || item.check_out) {
      var timeRow = document.createElement("div");
      timeRow.setAttribute("style", "font-size:9px;color:#9ca3af;margin-top:auto;");
      timeRow.textContent = timeToHHMM(item.check_in) + " → " + timeToHHMM(item.check_out);
      cell.appendChild(timeRow);
    }

    // Tooltip
    var worked    = formatWorked(item.worked_minutes);
    var tipExtras = "";
    if (item.wfh)                             tipExtras += " Work From Home";
    if (isLate(item) && item.check_in)        tipExtras += " Late";
    if (isEarlyLeaving(item, key) && item.check_out) tipExtras += " Early Out";
    if (item.out_of_geo)                        tipExtras += " Out of Geo";

    cell.setAttribute(
      "title",
      key
      + " — " + (status || "Not Marked")
      + " — In: "  + (item.check_in  || "—")
      + " Out: " + (item.check_out || "—")
      + (worked    ? " — " + worked + " worked" : "")
      + (tipExtras ? " —" + tipExtras            : "")
    );

    grid.appendChild(cell);
  }
}

// ── Initial load ─────────────────────────────────────────────
loadMonth(current.getFullYear(), current.getMonth() + 1);

// ── Birthdays & Anniversaries ────────────────────────────────
(function () {
  var birthdaysList     = root.querySelector("#alp-birthdays-list");
  var anniversariesList = root.querySelector("#alp-anniversaries-list");
  if (!birthdaysList && !anniversariesList) return;
  if (birthdaysList)     birthdaysList.innerHTML     = "<span style='color:#9ca3af;'>Loading...</span>";
  if (anniversariesList) anniversariesList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
  frappe.call({
    method: "alpinos.people_events.get_upcoming_birthdays_and_anniversaries",
    args: { days: 30 },
    freeze: false,
    callback: function (r) {
      if (r.exc) {
        if (birthdaysList)     birthdaysList.innerHTML     = "<span style='color:#9ca3af;'>Unable to load</span>";
        if (anniversariesList) anniversariesList.innerHTML = "<span style='color:#9ca3af;'>Unable to load</span>";
        return;
      }
      var data = r.message || {};
      function renderList(container, items, emptyText, isAnniv) {
        if (!container) return;
        container.innerHTML = "";
        if (!items || !items.length) {
          container.innerHTML = "<span style='color:#9ca3af;'>" + emptyText + "</span>";
          return;
        }
        items.forEach(function (item) {
          var row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";
          var left = document.createElement("div");
          left.style.cssText = "display:flex;flex-direction:column;gap:2px;min-width:0;";
          var name = document.createElement("div");
          name.style.cssText = "font-size:11px;font-weight:500;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
          name.textContent = item.employee_name || "";
          left.appendChild(name);
          if (item.company) {
            var company = document.createElement("div");
            company.style.cssText = "font-size:10px;color:#9ca3af;";
            company.textContent = item.company;
            left.appendChild(company);
          }
          var right = document.createElement("div");
          right.style.cssText = "display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0;";
          var dayEl = document.createElement("div");
          dayEl.style.cssText = "font-size:10px;color:#4b5563;";
          dayEl.textContent = item.date ? (function(d) {
            var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
            var parts = d.split("-");
            return parseInt(parts[2], 10) + " " + months[parseInt(parts[1], 10) - 1];
          })(item.date) : (item.day || "");
          right.appendChild(dayEl);
          if (isAnniv && item.years) {
            var years = document.createElement("div");
            years.style.cssText = "font-size:10px;color:#2563eb;font-weight:500;";
            years.textContent = item.years + " yr";
            right.appendChild(years);
          }
          row.appendChild(left);
          row.appendChild(right);
          container.appendChild(row);
        });
      }
      renderList(birthdaysList,     data.birthdays     || [], "No upcoming birthdays",    false);
      renderList(anniversariesList, data.anniversaries || [], "No upcoming anniversaries", true);
    },
  });
})();

// ── On Leave Today & On WFH Today ────────────────────────────
(function () {
  var onLeaveList = root.querySelector("#alp-on-leave-list");
  var onWfhList   = root.querySelector("#alp-on-wfh-list");
  var widget      = root.querySelector("#alp-on-leave-wfh-widget");
  if (!widget) return;
  if (onLeaveList) onLeaveList.innerHTML = "<span style='color:#9ca3af;'>Loading...</span>";
  if (onWfhList)   onWfhList.innerHTML   = "<span style='color:#9ca3af;'>Loading...</span>";
  frappe.call({
    method: "alpinos.people_events.get_on_leave_and_wfh_today",
    freeze: false,
    callback: function (r) {
      if (r.exc) { return; }
      var data = r.message || {};
      function renderOnLeave(containerEl, items) {
        if (!containerEl) return;
        containerEl.innerHTML = "";
        if (!items || !items.length) {
          containerEl.innerHTML = "<span style='color:#9ca3af;'>No one on leave today</span>";
          return;
        }
        items.forEach(function (item) {
          var row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";
          var left = document.createElement("div");
          left.style.cssText = "display:flex;flex-direction:column;gap:2px;min-width:0;";
          var name = document.createElement("div");
          name.style.cssText = "font-size:11px;font-weight:500;color:#111827;";
          name.textContent = item.employee_name || item.employee || "";
          left.appendChild(name);
          var leaveType = document.createElement("div");
          leaveType.style.cssText = "font-size:10px;color:#6b7280;";
          leaveType.textContent = (item.leave_type || "") + (item.half_day ? " (Half day)" : "");
          left.appendChild(leaveType);
          var right = document.createElement("div");
          right.style.cssText = "font-size:10px;color:#4b5563;flex-shrink:0;";
          right.textContent = (item.from_date || "") + " to " + (item.to_date || "");
          row.appendChild(left);
          row.appendChild(right);
          containerEl.appendChild(row);
        });
      }
      function renderOnWfh(containerEl, items) {
        if (!containerEl) return;
        containerEl.innerHTML = "";
        if (!items || !items.length) {
          containerEl.innerHTML = "<span style='color:#9ca3af;'>No one on WFH today</span>";
          return;
        }
        items.forEach(function (item) {
          var row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";
          var name = document.createElement("div");
          name.style.cssText = "font-size:11px;font-weight:500;color:#111827;";
          name.textContent = item.employee_name || item.employee || "";
          row.appendChild(name);
          containerEl.appendChild(row);
        });
      }
      renderOnLeave(onLeaveList, data.on_leave || []);
      renderOnWfh(onWfhList,   data.on_wfh   || []);
    },
  });
})();
