// filter.js — shared round-trip filter + ranking engine.
// Used by BOTH the Scriptable widget and the web app, so results always match.
// Pure: `computeTrips(flights, options)` → sorted list of trips. No I/O.
//
// options:
//   from, to                  airports (default BRU/VCE)
//   minNights, maxNights      trip length range
//   nonstopOnly               only direct flights
//   airlines                  comma-separated name substrings, e.g. "SN"
//   saturdayIn                require a Saturday night in the trip
//   earliestDeparture         "HH:MM": drop ANY leg leaving before this
//   depWeekdays               numbers 0=Sun..6=Sat; restrict OUTBOUND days
//   depAfterHour              OUTBOUND only: depart at/after this hour (24h)
//   searchFrom, searchTo      OUTBOUND window (YYYY-MM-DD, "" = open)
//   includeFrom / includeTo   trip must span the whole range: leave on/before
//                             includeFrom and return on/after includeTo ("" = off)
//
// Ranking: price only (ties: longer trip first, then earlier departures).
(function (global) {
  "use strict";

  function toDate(isoStr) {
    const [y, m, d] = isoStr.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }
  function addDays(date, days) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + days));
  }
  function iso(date) {
    return date.toISOString().slice(0, 10);
  }
  function toMinutes(hhmm) {
    const [h, m] = String(hhmm).split(":").map(Number);
    return h * 60 + m;
  }
  function hasSaturdayNight(dep, ret) {
    for (let day = dep; day < ret; day = addDays(day, 1)) {
      if (day.getUTCDay() === 6) return true;
    }
    return false;
  }
  function firstSaturday(dep, ret) {
    for (let day = dep; day < ret; day = addDays(day, 1)) {
      if (day.getUTCDay() === 6) return day;
    }
    return null;
  }

  // Filters that apply to EVERY leg (outbound and return).
  function legOk(flight, o) {
    if (o.nonstopOnly && flight.stops > 0) return false;
    const wanted = String(o.airlines || "")
      .split(",").map((a) => a.trim().toLowerCase()).filter(Boolean);
    if (wanted.length &&
        !wanted.some((a) => String(flight.airline || "").toLowerCase().includes(a))) {
      return false;
    }
    if (o.earliestDeparture &&
        toMinutes(flight.departure) < toMinutes(o.earliestDeparture)) {
      return false;
    }
    return true;
  }

  // Outbound-only filters on top of legOk.
  function outLegOk(flight, o) {
    if (!legOk(flight, o)) return false;
    if (o.depWeekdays && o.depWeekdays.length &&
        !o.depWeekdays.includes(toDate(flight.date).getUTCDay())) {
      return false;
    }
    if (o.depAfterHour && toMinutes(flight.departure) < Number(o.depAfterHour) * 60) {
      return false;
    }
    if (o.searchFrom && flight.date < o.searchFrom) return false;
    if (o.searchTo && flight.date > o.searchTo) return false;
    return true;
  }

  function computeTrips(flights, options) {
    const o = options || {};
    const from = (o.from || "BRU").toUpperCase();
    const to = (o.to || "VCE").toUpperCase();
    const minN = o.minNights || 1;
    const maxN = o.maxNights || 14;

    const outByDate = new Map();
    for (const f of flights) {
      if (f.origin === from && f.destination === to && outLegOk(f, o)) {
        if (!outByDate.has(f.date)) outByDate.set(f.date, []);
        outByDate.get(f.date).push(f);
      }
    }
    const retByDate = new Map();
    for (const f of flights) {
      if (f.origin === to && f.destination === from && legOk(f, o)) {
        if (!retByDate.has(f.date)) retByDate.set(f.date, []);
        retByDate.get(f.date).push(f);
      }
    }

    const trips = [];
    for (const [outDateStr, outFlights] of outByDate) {
      const outDate = toDate(outDateStr);
      for (let nights = minN; nights <= maxN; nights++) {
        const retIso = iso(addDays(outDate, nights));
        if (o.includeFrom && !(outDateStr <= o.includeFrom)) continue;
        if (o.includeTo && !(retIso >= o.includeTo)) continue;
        const retFlights = retByDate.get(retIso) || [];
        if (retFlights.length === 0) continue;
        if (o.saturdayIn && !hasSaturdayNight(outDate, toDate(retIso))) continue;
        const sat = o.saturdayIn ? firstSaturday(outDate, toDate(retIso)) : null;

        for (const of2 of outFlights) {
          for (const rf of retFlights) {
            const price = Math.round((of2.price + rf.price) * 100) / 100;
            trips.push({
              out: of2, ret: rf,
              outDate: outDateStr,
              retDate: retIso,
              nights: nights,
              saturday: sat ? iso(sat) : null,
              price: price,
              score: price,
            });
          }
        }
      }
    }

    trips.sort((a, b) =>
      a.price - b.price ||
      b.nights - a.nights ||
      a.out.departure.localeCompare(b.out.departure) ||
      a.ret.departure.localeCompare(b.ret.departure) ||
      a.outDate.localeCompare(b.outDate) ||
      a.retDate.localeCompare(b.retDate));
    return trips;
  }

  global.Filter = { computeTrips: computeTrips };
  if (typeof module !== "undefined" && module.exports) module.exports = global.Filter;
  if (typeof self !== "undefined") self.Filter = global.Filter;
})(typeof globalThis !== "undefined" ? globalThis : this);