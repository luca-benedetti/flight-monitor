// BRU ⇄ VCE flight widget (Scriptable)
// =====================================
// Edit the CONFIG block below to change what the widget computes. Save the
// script in the Scriptable app and add it as a home-screen widget.
//
// Data: reads fares.json (one-way legs both directions, produced by
// `build-fares`) from a static URL; scoring runs locally on the phone
// (a direct port of find_round_trips.py).

const CONFIG = {
  from: "BRU",
  to: "VCE",
  faresUrl: "https://luca-benedetti.github.io/flight-monitor/fares.json",

  // Hard filters
  nonstopOnly: true,        // only direct flights (no stops)
  airlines: "",             // comma-separated airline substrings, e.g. "SN"
  saturdayIn: true,         // require a Saturday night in the trip

  // Soft scoring (mirrors config/round_trip_config.json)
  periods: [
    {
      from: "2026-09-01", to: "2026-11-30",
      minNights: 4, maxNights: 10,
      earliestDeparture: "08:30",
      preferredDeparture: "10:00", earlyPenaltyPerMin: 1.0,
      preferredNights: 7, shortStayPenaltyPerNight: 8.0,
    },
    {
      from: "2026-12-01", to: "2027-01-31",
      minNights: 5, maxNights: 14,
      earliestDeparture: "09:00",
      preferredDeparture: "09:00", earlyPenaltyPerMin: 0.0,
      preferredNights: 10, shortStayPenaltyPerNight: 6.0,
    },
  ],

  // Display
  topLines: 4,              // combo rows to show (medium widget fits ~4-5)
  currency: "€",
};

// ---------------------------------------------------------------------------
// Helpers (do not edit below this line)
// ---------------------------------------------------------------------------

function toDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function addDays(date, days) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + days));
}

function iso(date) {
  return date.toISOString().slice(0, 10);
}

function shortDate(isoStr) {
  const [y, m, d] = isoStr.split("-").map(Number);
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1];
  return `${d} ${month}`;
}

function toMinutes(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
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

function legHardOk(flight, period) {
  if (CONFIG.nonstopOnly && flight.stops > 0) return false;
  if (CONFIG.airlines) {
    const wanted = CONFIG.airlines.split(",").map((a) => a.trim().toLowerCase());
    const name = flight.airline.toLowerCase();
    if (!wanted.some((a) => name.includes(a))) return false;
  }
  if (period.earliestDeparture &&
      toMinutes(flight.departure) < toMinutes(period.earliestDeparture)) {
    return false;
  }
  return true;
}

function inWindow(isoStr, period) {
  return isoStr >= period.from && isoStr <= period.to;
}

function earlyPenalty(flight, period) {
  if (!period.preferredDeparture || !period.earlyPenaltyPerMin) return 0;
  const early = toMinutes(period.preferredDeparture) - toMinutes(flight.departure);
  return Math.max(0, early) * period.earlyPenaltyPerMin;
}

function shortStayPenalty(nights, period) {
  if (!period.preferredNights || !period.shortStayPenaltyPerNight) return 0;
  return Math.max(0, period.preferredNights - nights) * period.shortStayPenaltyPerNight;
}

function airlineLabel(flight) {
  return (flight.airline || "?").replace(/ \/ /g, "+");
}

// ---------------------------------------------------------------------------
// Scoring (port of find_round_trips.py)
// ---------------------------------------------------------------------------

function computeCombos(flights) {
  const outbound = flights.filter((f) => f.origin === CONFIG.from && f.destination === CONFIG.to);
  const inbound = flights.filter((f) => f.origin === CONFIG.to && f.destination === CONFIG.from);
  const combos = [];

  for (const period of CONFIG.periods) {
    const outByDate = new Map();
    for (const f of outbound) {
      if (inWindow(f.date, period) && legHardOk(f, period)) {
        if (!outByDate.has(f.date)) outByDate.set(f.date, []);
        outByDate.get(f.date).push(f);
      }
    }
    const retByDate = new Map();
    for (const f of inbound) {
      if (legHardOk(f, period)) {
        if (!retByDate.has(f.date)) retByDate.set(f.date, []);
        retByDate.get(f.date).push(f);
      }
    }

    for (const [outDateStr, outFlights] of outByDate) {
      const outDate = toDate(outDateStr);
      for (let nights = period.minNights; nights <= period.maxNights; nights++) {
        const retDate = addDays(outDate, nights);
        const retFlights = retByDate.get(iso(retDate)) || [];
        if (retFlights.length === 0) continue;
        if (CONFIG.saturdayIn && !hasSaturdayNight(outDate, retDate)) continue;
        const sat = CONFIG.saturdayIn ? firstSaturday(outDate, retDate) : null;

        for (const of2 of outFlights) {
          for (const rf of retFlights) {
            const price = Math.round((of2.price + rf.price) * 100) / 100;
            const penalties =
              earlyPenalty(of2, period) + earlyPenalty(rf, period) +
              shortStayPenalty(nights, period);
            combos.push({
              out: of2, ret: rf,
              outDate: outDateStr,
              retDate: iso(retDate),
              nights,
              saturday: sat ? iso(sat) : null,
              price,
              penalties: Math.round(penalties * 100) / 100,
              score: Math.round((price + penalties) * 100) / 100,
            });
          }
        }
      }
    }
  }

  combos.sort((a, b) =>
    a.score - b.score ||
    a.price - b.price ||
    b.nights - a.nights ||
    a.out.departure.localeCompare(b.out.departure));
  return combos;
}

function comboLine(c) {
  const price = `${CONFIG.currency}${c.score.toFixed(0)}`;
  const trip = `${shortDate(c.outDate)} → ${shortDate(c.retDate)} · ${c.nights}n`;
  const flight = `${c.out.departure}-${c.out.arrival} ${airlineLabel(c.out)}`;
  return { price, trip, flight };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

async function buildWidget(combos, generatedAt) {
  const widget = new ListWidget();
  widget.backgroundColor = new Color("#0f1115", 1);

  const header = widget.addText(`BRU → VCE · best trips`);
  header.font = Font.boldSystemFont(15);
  header.textColor = Color.white();

  if (combos.length === 0) {
    const nothing = widget.addText("No trips match the filters.");
    nothing.font = Font.mediumSystemFont(12);
    nothing.textColor = Color.gray();
  } else {
    for (const c of combos.slice(0, CONFIG.topLines)) {
      const { price, trip, flight } = comboLine(c);
      const row = widget.addText(`${price}   ${trip}`);
      row.font = Font.mediumSystemFont(13);
      row.textColor = new Color("#8ae");
      const sub = widget.addText(`        ${flight}`);
      sub.font = Font.regularSystemFont(10);
      sub.textColor = new Color("#8a8f98");
    }
  }

  const footer = widget.addText(
    `fares updated ${generatedAt ? generatedAt.slice(0, 10) : "?"}`);
  footer.font = Font.regularSystemFont(9);
  footer.textColor = Color.gray();

  return widget;
}

async function main() {
  let widget;
  try {
    const req = new Request(CONFIG.faresUrl);
    req.headers = { "Accept": "application/json" };
    const fares = await req.loadJSON();
    const combos = computeCombos(fares.flights || []);
    widget = await buildWidget(combos, (fares.metadata || {}).generated_at);
  } catch (err) {
    widget = new ListWidget();
    widget.backgroundColor = new Color("#0f1115", 1);
    const fail = widget.addText(`Fares unavailable\n${err}`);
    fail.font = Font.mediumSystemFont(11);
    fail.textColor = new Color("#f66");
  }

  if (config.runsInWidget) {
    Script.setWidget(widget);
  } else {
    await widget.presentMedium();
  }
  Script.complete();
}

if (typeof Script !== "undefined") {
  (async function () {
    await main();
  })();
}