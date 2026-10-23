// Reads {flights, options} as JSON on stdin, prints Filter.computeTrips(...) as JSON.
// Driven by test_filter_parity.py to compare web/filter.js with the Python ranker.
const path = require("path");
const Filter = require(path.join(__dirname, "..", "web", "filter.js"));

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const { flights, options } = JSON.parse(input);
  process.stdout.write(JSON.stringify(Filter.computeTrips(flights, options)));
});
