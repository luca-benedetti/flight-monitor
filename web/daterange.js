// daterange.js — lightweight range picker: preset chips + dual-month calendar.
// Turns a `.range` block into a picker backed by two hidden inputs.
//
// Markup expected:
//   <div class="range" data-range="within"
//        data-from="tripWithinFrom" data-to="tripWithinTo">
//     <div class="range-head">...</div>
//     <div class="range-presets">
//       <button data-preset="any">Any</button>
//       <button data-preset="thisweekend">This weekend</button>
//       <button data-preset="next2w">Next 2 weeks</button>
//       <button data-preset="next30">Next 30 days</button>
//       <button data-preset="custom">Custom…</button>
//     </div>
//     <button class="range-value" type="button"></button>
//     <div class="cal-pop"></div>
//   </div>
(function (global) {
  "use strict";

  const MONTHS = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"];
  const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const WD = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  function parse(s) {
    if (!s) return null;
    const [y, m, d] = String(s).split("-").map(Number);
    if (!y || !m || !d) return null;
    return new Date(y, m - 1, d);
  }
  const startOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
  const addMonths = (d, n) => new Date(d.getFullYear(), d.getMonth() + n, 1);
  const sameDay = (a, b) => !!a && !!b && iso(a) === iso(b);
  const shortLabel = (d) =>
    d ? `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}` : "";

  function closeAllPopovers() {
    document.querySelectorAll(".cal-pop.open").forEach((p) =>
      p.classList.remove("open"));
    document.body.classList.remove("cal-open");
  }

  function buildMonth(year, month, start, end) {
    const first = new Date(year, month, 1);
    const offset = (first.getDay() + 6) % 7; // Monday-first grid
    const days = new Date(year, month + 1, 0).getDate();
    const cells = [];
    for (let i = 0; i < offset; i++) {
      cells.push('<span class="cal-day is-empty"></span>');
    }
    for (let day = 1; day <= days; day++) {
      const d = new Date(year, month, day);
      let cls = "cal-day";
      if (start && end && d >= start && d <= end) cls += " in-range";
      if (sameDay(d, start)) cls += " is-start";
      if (sameDay(d, end)) cls += " is-end";
      cells.push(
        `<button type="button" class="${cls}" data-date="${iso(d)}">${day}</button>`);
    }
    return `<div class="cal-month">
      <div class="cal-month-title">${MONTHS[month]} ${year}</div>
      <div class="cal-wd">${WD.map((w) => `<span>${w}</span>`).join("")}</div>
      <div class="cal-days">${cells.join("")}</div>
    </div>`;
  }

  function RangePicker(root, onChange) {
    const fromEl = document.getElementById(root.dataset.from);
    const toEl = document.getElementById(root.dataset.to);
    const valueBtn = root.querySelector(".range-value");
    const pop = root.querySelector(".cal-pop");
    let start = parse(fromEl.value);
    let end = parse(toEl.value);
    let view = startOfMonth(start || end || new Date());

    function renderValue() {
      if (start && end) {
        valueBtn.textContent = `${shortLabel(start)} → ${shortLabel(end)}`;
        valueBtn.classList.remove("is-empty");
      } else if (start) {
        valueBtn.textContent = `${shortLabel(start)} → …`;
        valueBtn.classList.remove("is-empty");
      } else {
        valueBtn.textContent = "Any dates";
        valueBtn.classList.add("is-empty");
      }
    }
    function sync(fire) {
      fromEl.value = start ? iso(start) : "";
      toEl.value = end ? iso(end) : "";
      renderValue();
      if (fire) onChange();
    }
    function renderCal() {
      const m1 = addMonths(view, 1);
      pop.innerHTML =
        `<div class="cal-nav">
           <button type="button" class="cal-arrow" data-nav="-1" aria-label="Previous month">‹</button>
           <span class="cal-range">${shortLabel(start) || "…"} → ${shortLabel(end) || "…"}</span>
           <button type="button" class="cal-arrow" data-nav="1" aria-label="Next month">›</button>
         </div>
         <div class="cal-grids">
           ${buildMonth(view.getFullYear(), view.getMonth(), start, end)}
           ${buildMonth(m1.getFullYear(), m1.getMonth(), start, end)}
         </div>
         <div class="cal-actions">
           <button type="button" class="ghost" data-clear>Clear</button>
           <button type="button" class="primary" data-done>Done</button>
         </div>`;
    }
    function open() {
      closeAllPopovers();
      view = startOfMonth(start || end || new Date());
      renderCal();
      pop.classList.add("open");
      valueBtn.setAttribute("aria-expanded", "true");
      document.body.classList.add("cal-open");
    }
    function close() {
      pop.classList.remove("open");
      valueBtn.setAttribute("aria-expanded", "false");
      if (!document.querySelector(".cal-pop.open")) {
        document.body.classList.remove("cal-open");
      }
    }
    function toggle() {
      pop.classList.contains("open") ? close() : open();
    }

    valueBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggle();
    });

    pop.addEventListener("click", (e) => {
      e.stopPropagation();
      const nav = e.target.closest("[data-nav]");
      if (nav) {
        view = addMonths(view, Number(nav.dataset.nav));
        renderCal();
        return;
      }
      if (e.target.closest("[data-clear]")) {
        start = end = null;
        sync(true);
        renderCal();
        return;
      }
      if (e.target.closest("[data-done]")) {
        close();
        return;
      }
      const day = e.target.closest("[data-date]");
      if (day) {
        const d = parse(day.dataset.date);
        if (!start || (start && end)) { start = d; end = null; }
        else if (d < start) { start = d; end = null; }
        else { end = d; }
        sync(true);
        renderCal();
      }
    });

    root.querySelectorAll("[data-preset]").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        const p = b.dataset.preset;
        if (p === "custom") { open(); return; }
        closeAllPopovers();
        if (p === "any") {
          start = end = null;
        } else {
          const t = new Date();
          t.setHours(0, 0, 0, 0);
          if (p === "thisweekend") {
            const diff = (5 - ((t.getDay() + 6) % 7) + 7) % 7;
            const fri = new Date(t);
            fri.setDate(t.getDate() + diff);
            start = fri;
            end = new Date(fri);
            end.setDate(fri.getDate() + 2);
          } else if (p === "next2w") {
            start = t;
            end = new Date(t);
            end.setDate(end.getDate() + 13);
          } else if (p === "next30") {
            start = t;
            end = new Date(t);
            end.setDate(end.getDate() + 29);
          }
        }
        sync(true);
      });
    });

    renderValue();

    return {
      set(s, e) {
        start = parse(s);
        end = parse(e);
        sync(false);
        if (pop.classList.contains("open")) renderCal();
      },
      clear() {
        start = end = null;
        sync(false);
      },
    };
  }

  // Clicking anywhere outside an open popover closes it.
  document.addEventListener("click", () => closeAllPopovers());

  global.createRangePicker = RangePicker;
})(typeof window !== "undefined" ? window : globalThis);
