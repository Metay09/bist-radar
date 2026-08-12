# Provider integration and onboarding

The ingestion boundary is strictly: provider → raw adapter → schema validation → exact symbol mapping → UTC timestamp normalization → canonical Decimal conversion → quality validation → deduplication/revision audit → persistence → analysis. Vendor fields never enter financial logic.

## Canonical decisions

Prices and volume cross the vendor boundary as `Decimal` created from strings (floats use `repr` first). PostgreSQL persistence uses fixed precision numerics. Provider timestamps must be timezone-aware and are stored in UTC; `source_timestamp` and `received_timestamp` are separate. Europe/Istanbul is the BIST presentation timezone. Naive timestamps and fuzzy symbol matching are rejected.

Unofficial/mock data carries `RESEARCH_ONLY`, `UNVERIFIED_SOURCE`, and `CALENDAR_UNVERIFIED`. An official calendar adapter is required before strict production signals. Raw payload archive is disabled by default, retention-limited when enabled, and must never store authorization headers.

## Adding a licensed vendor

1. Confirm license and API documentation; configure credentials only through secret environment variables (`API_KEY`, token, or username/password). Never expose them via logs, events, DB payloads, or API responses.
2. Implement the canonical provider contract and declare every capability. Unsupported operations must raise `PROVIDER_CAPABILITY_UNAVAILABLE`.
3. Add exact vendor-symbol mappings, timezone semantics, data mode, rate limits, adjusted/unadjusted meaning, dataset version, and calendar capability.
4. Pass the shared conformance suite: canonical Decimal bars, sorted UTC timestamps, unique identities, error/timeout/rate-limit mapping, empty/invalid payload handling, and exact symbol mapping.
5. Run import `--dry-run` to parse, normalize, validate and report quality without writes. Inspect quarantine and revision reports.
6. Import a licensed sample, cross-check against an independent source, verify deterministic dataset hash and replay reproducibility.
7. Explicitly approve production mode. Fixture or unverified providers are forbidden there.

## Production onboarding checklist

- [ ] License confirmed
- [ ] API documentation confirmed
- [ ] REALTIME/DELAYED/EOD mode known
- [ ] Exact symbol mapping confirmed
- [ ] Timezone and source timestamp semantics confirmed
- [ ] Rate limits and Retry-After behavior confirmed
- [ ] Historical ordering/revision semantics confirmed
- [ ] Adjusted/unadjusted policy known
- [ ] Conformance suite PASS
- [ ] Quality and latency test PASS
- [ ] Cross-provider sample PASS
- [ ] Secrets configured outside Git
- [ ] Official calendar status confirmed
- [ ] Production flag explicitly enabled

Raw revisions retain old/new canonical values and receipt time. Duplicate identities never create another bar; conflicting values create `DATA_REVISION` instead of silently overwriting. Invalid payloads are quarantined and cannot reach analysis.
