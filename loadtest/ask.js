// k6 load test for POST /api/v1/analytics/ask against the mock provider.
//
//   k6 run -e BASE_URL=http://localhost:8000 loadtest/ask.js
//   k6 run -e SCENARIO=saturation -e BASE_URL=http://localhost:8000 loadtest/ask.js
//
// Run against the backend directly with rate limiting off and a simulated provider latency; see
// docker-compose.loadtest.yml and docs/capacity.md. Thresholds fail the run (exit code 99), so a
// scheduled job reports p95 latency and error rate and goes red when either regresses.
import http from "k6/http";
import { check } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN || "";
const SCENARIO = __ENV.SCENARIO || "steady";
// Answers the mock provider can produce. Mixing them exercises different SQL shapes.
const QUESTIONS = [
  "How many active vehicles do we have?",
  "What were the top 10 customers by revenue?",
  "Show monthly revenue for the last 12 months.",
  "Which vehicles had the highest idle time?",
  "Show fuel consumption by vehicle.",
];

const askDuration = new Trend("ask_duration", true);
const askFailed = new Rate("ask_failed");

const scenarios = {
  // Constant arrival rate: the realistic shape for "N questions per second".
  steady: {
    executor: "constant-arrival-rate",
    rate: Number(__ENV.RATE || 10),
    timeUnit: "1s",
    duration: __ENV.DURATION || "3m",
    preAllocatedVUs: 50,
    maxVUs: 200,
  },
  // Ramp until something breaks, to find the saturation point recorded in docs/capacity.md.
  saturation: {
    executor: "ramping-arrival-rate",
    startRate: 2,
    timeUnit: "1s",
    preAllocatedVUs: 100,
    maxVUs: 500,
    stages: [
      { target: 10, duration: "1m" },
      { target: 25, duration: "2m" },
      { target: 50, duration: "2m" },
      { target: 100, duration: "2m" },
    ],
  },
};

export const options = {
  scenarios: { [SCENARIO]: scenarios[SCENARIO] },
  thresholds:
    SCENARIO === "steady"
      ? {
          ask_failed: ["rate<0.01"],
          ask_duration: ["p(95)<2000"],
          http_req_failed: ["rate<0.01"],
        }
      : {}, // the saturation run only records; read the summary instead of failing it
};

export default function () {
  const question = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const headers = { "Content-Type": "application/json" };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;

  const response = http.post(
    `${BASE_URL}/api/v1/analytics/ask`,
    JSON.stringify({ question }),
    { headers, tags: { endpoint: "ask" } },
  );

  const ok = check(response, {
    "status is 200": (r) => r.status === 200,
    "has rows": (r) => r.status === 200 && r.json("row_count") >= 0,
  });
  askFailed.add(!ok);
  askDuration.add(response.timings.duration);
}

export function handleSummary(data) {
  return { "loadtest-summary.json": JSON.stringify(data, null, 2) };
}
