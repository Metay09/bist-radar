# BIST Radar live dashboard acceptance — 2026-08-21

BASELINE COMMIT:

270352a

AUDIT:

ALREADY COMPLETE:

BIST execution rules, RVOL semantics, candidate ranking/deduplication, atomic opportunity identity, candidate/plan timestamp guard, pending/error/invalid plan separation, bounded plan retry, responsive shell, Radar search/filter/scroll restoration, N+1 removal and latency middleware.

PARTIAL:

The frontend consumed candidates and opportunities separately; route state restored controls but not read payloads; retry existed only for opportunities; the atomic endpoint still computed plans during reads.

MISSING:

Reusable route cache, SWR, in-flight deduplication, old-response protection, snapshot-status polling, visibility/focus/online revalidation, manual persisted-truth refresh, warm symbol hero and session-date cache validation.

REGRESSIONS FOUND:

Read-time plan computation violated `PAGE OPEN != FINANCIAL RECALCULATION`. Production acceptance also exposed page analytics that reread all signal pages repeatedly.

ROOT CAUSE:

The original `useLoad` state lived only inside route components and reset on remount. Candidate and plan resources had independent lifecycles. Analytics assembled bounded API pages repeatedly instead of loading persisted analytics truth with set queries.

FALSE INVALID FIX:

Missing, loading, retrying, failed and mismatched plans remain non-financial states. Only an explicit backend `GECERSIZ` plan renders “İşlem Uygun Değil”.

ATOMIC OPPORTUNITY READ MODEL:
YES
Implementation:

`/dashboard/opportunities` now returns candidates plus only worker-persisted plan snapshots. The worker stores each completed-bar plan in the scan report; legacy plans are recovered by one bounded signal-id query. No plan mathematics runs in a UI read endpoint.

SNAPSHOT_ID:
YES

SNAPSHOT CONSISTENCY:

Candidate and plan timestamps must match; mismatches render “Plan güncelleniyor”. Older network responses cannot replace a newer `data_timestamp`.

NAVIGATION CACHE:
YES

STALE-WHILE-REVALIDATE:
YES

AUTO REFRESH:
YES

AUTO REFRESH INTERVAL:

25 seconds while market is open; 5 minutes while closed.

BACKGROUND POLLING:

Paused while `document.visibilityState != visible`.

FOREGROUND REVALIDATION:

Immediate deduplicated snapshot-status check on visibility, focus and online events.

MANUAL REFRESH BEHAVIOR:

Revalidates persisted snapshot/status only; it never triggers Radar, plan, Adaptive, outcome or ML computation.

REQUEST DEDUP:
YES

REQUEST ABORT / STALE RESPONSE PROTECTION:
YES

RETRY:
YES

ETAG / 304:
NO
Reason:

Snapshot-status is a small metadata payload and snapshot identity already prevents full reloads. Adding proxy-sensitive conditional-response behavior was not justified for this payload.

COLD RADAR LOAD:
5392 ms (controlled production Chromium, usable candidate content)

WARM RADAR RETURN:
682 ms (production browser history; cached content is non-blocking)

SYMBOL WARM OPEN:
432 ms (cached Radar hero)

FILTER RESPONSE:
<150 ms

SORT RESPONSE:
<150 ms

TAB RESPONSE:
173 ms production browser measurement; visual pressed state remains immediate

SNAPSHOT UPDATE:
PASS

FALSE “İŞLEM UYGUN DEĞİL” INTERMEDIATE:
0

NAVIGATION FINANCIAL RECALCULATION:
0

UI POLLING FINANCIAL RECALCULATION:
0

INITIAL REQUEST COUNT:
5 critical Radar reads (summary, universe, candidates fallback, opportunities, snapshot status)

WARM RETURN REQUEST COUNT:
5 background revalidations; 0 blocking reads

SNAPSHOT STATUS CHECK COUNT:
1 initial plus one per active interval/focus event, deduplicated

FULL SNAPSHOT RELOAD COUNT:
1 initial; then 1 only when snapshot identity changes

DUPLICATE REQUEST COUNT:
0

BACKEND TESTS:
244 PASS

BACKEND COVERAGE:
90.31%

COVERAGE GATE:
PASS (>=90%)

RUFF:
PASS

MYPY:
PASS (strict)

FRONTEND TESTS:
19 PASS

TYPESCRIPT:
PASS

ESLINT:
PASS

BUILD:
PASS

PLAYWRIGHT MOCK:
14 PASS, 2 production-opt-in skipped

PLAYWRIGHT PRODUCTION:
2 PASS

PRODUCTION ACCEPTANCE:
PASS — Radar, Tracking, History, Analysis, System, five real persisted-plan symbols, warm back navigation and chart verified.

PR BODY UPDATED:
YES

FINANCIAL SEMANTICS UNCHANGED:
YES

TRADING_MODE:
paper

LIVE_TRADING:
false

ML MODE:
shadow

SHADOW DECISION EFFECT:
NONE

WORKING TREE CLEAN:
YES

PUSH:
YES

COMMITS:

`aa09129` feat: serve persisted snapshot truth without read-time recalculation

`6167b0d` feat: add snapshot-aware dashboard cache and live refresh

`test: verify live dashboard responsiveness` (acceptance evidence commit)

KNOWN LIMITATIONS:

Legacy scan reports predate embedded plan snapshots; only exact persisted signal-id matches expose those old plans. Other legacy rows correctly remain “Plan güncelleniyor” until the next worker snapshot. `App.tsx` and `legacy.css` technical debt remains intentionally out of scope.

NEXT RECOMMENDATION:

Observe a full open-market session and retain snapshot-status/opportunity p50/p95 plus client cache counters; do not change financial policy.
