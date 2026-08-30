// BRU ⇄ VCE flight widget (Scriptable)
// =====================================
// Edit the CONFIG block below to change what the widget computes. Save the
// script in the Scriptable app and add it as a home-screen widget.
//
// Data: reads fares.json (one-way legs both directions, produced by
// `build-fares`) from a static URL; scoring runs locally on the phone using
// the shared engine in web/filter.js (a direct port of find_round_trips.py).

const CONFIG = {
  from: "BRU",
  to: "VCE",
  faresUrl: "https://luca-benedetti.github.io/flight-monitor/fares.json",
  engineUrl: "https://luca-benedetti.github.io/flight-monitor/filter.js",

  // Trip shape
  minNights: 4,
  maxNights: 10,

  // Hard filters
  nonstopOnly: true,        // only direct flights (no stops)
  airlines: "",             // comma-separated airline substrings, e.g. "SN"
  saturdayIn: true,         // require a Saturday night in the trip
  earliestDeparture: "",    // "08:30" = drop any leg leaving before this

  // Outbound "leave" filters (disable by leaving empty / 0)
  depWeekdays: [],          // e.g. [1,4] = only leave on Monday or Thursday (0=Sun..6=Sat)
  depAfterHour: 0,          // only leave at/after this hour (24h); combine with depWeekdays
                            // for "Monday/Thursday evening". 0 = any time.

  // Outbound departure window ("" = any date in the scrape horizon)
  searchFrom: "",           // e.g. "2026-09-07"
  searchTo: "",             // e.g. "2026-10-31"

  // Force every shown trip to span a date range ("" = off): the trip must
  // leave on/before includeFrom AND return on/after includeTo.
  includeFrom: "",           // e.g. "2026-12-24"
  includeTo: "",             // e.g. "2027-01-02"

  // Display
  topLines: 4,              // combo rows to show (medium widget fits ~4-5)
  currency: "€",
};

// ---------------------------------------------------------------------------
// Rendering helpers (do not edit below this line)
// ---------------------------------------------------------------------------

function shortDate(isoStr) {
  const [y, m, d] = isoStr.split("-").map(Number);
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1];
  return `${d} ${month}`;
}

function airlineLabel(flight) {
  return (flight.airline || "?").replace(/ \/ /g, "+");
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

async function buildWidget(combos, fares) {
  const meta = fares || {};
  const generatedAt = meta.generated_at;
  const skipped = meta.skipped_days || [];
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

  if (skipped.length > 0) {
    const warn = widget.addText(
      `${skipped.length} date(s) missing from scan (partial data)`);
    warn.font = Font.regularSystemFont(9);
    warn.textColor = new Color("#e8a33d");
  }

  return widget;
}

async function main() {
  let widget;
  try {
    const engine = new Request(CONFIG.engineUrl);
    engine.headers = { "Accept": "text/javascript" };
    const engineSrc = await engine.loadString();
    eval(engineSrc);

    const req = new Request(CONFIG.faresUrl);
    req.headers = { "Accept": "application/json" };
    const fares = await req.loadJSON();
    const combos = Filter.computeTrips(fares.flights || [], CONFIG);
    widget = await buildWidget(combos, fares.metadata);
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