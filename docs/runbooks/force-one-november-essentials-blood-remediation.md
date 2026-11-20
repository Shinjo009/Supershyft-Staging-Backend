# Force one November — METSIGHTS_ESSENTIALS blood re-push

Engagement: **Force one November** (`engagement_id=1253`, code `FOMU1026`).

## Context

Participants use assessment package `METSIGHTS_ESSENTIALS` (`package_id=1`). Before the
`METSIGHTS_ESSENTIALS` blood-draft fix, `draft_blood_parameters_from_report` rejected that
package code. Blood-parameters were pushed using **internal average fallbacks** only (e.g. T3
`1.1`, T4 `8.0`, TSH `2.0`), so Bio AI `thyroid_health` often showed **risk_score_scaled = 0**.

After deploying the code fix, **new** blood loads draft real Healthians values. Existing Bio AI
reports still reflect the old Metsights data until blood is re-pushed and reports regenerated.

## Preconditions

1. Code with `METSIGHTS_ESSENTIALS` in `_METSIGHTS_BLOOD_PACKAGE_CODES` is deployed to production.
2. Metsights allows updating `blood-parameters` on affected records (Bio AI not locked, or
   records reset per Metsights ops policy). SuperShyft skips push when
   `is_bioai_report_generated` is true.

## Remediation steps

1. **Deploy** the API release containing the ESSENTIALS blood-draft fix.
2. **Coordinate with Metsights** if reports are locked: unlock or reset Bio AI for the ~132
   participants with full blood reports who received fallback pushes (Nov 2026 window).
3. **Re-draft and re-push** blood for engagement `1253`:
   - Preferred: run the existing **regenerate Bio AI** job/cron
     (`regenerate_bioai_reports`) scoped to this engagement, which calls
     `redraft_blood_questionnaire_responses` and re-pushes Metsights categories.
   - Alternative: admin **Regenerate Bio AI** per participant from the engagement console.
4. **Verify integration sync logs** (`integration_sync_logs`, provider `metsights`):
   - POST `.../blood-parameters/` `request_payload` should show participant-specific
     `triiodothyronine`, `thyroxine`, `tsh_value` (not the uniform `1.1` / `8.0` / `2.0`).
   - Confirm `bio_ai_reports` fetch succeeds after push.
5. **Verify Bio AI JSON** in `individual_health_report.reports`:
   - `thyroid_health` `risk_score_scaled` should vary across users (not all `0`).
6. **Spot-check** questionnaire answers for primary Metsights instances
   (`METSIGHTS_ESSENTIALS`, `assessment_type_code=1`): thyroid answers should match Healthians
   grouped `blood_parameters` on `participant_blood_bookings`.

## Read-only SQL checks (examples)

```sql
-- Fallback fingerprint still present in recent pushes?
SELECT count(*) FROM integration_sync_logs
WHERE engagement_id = 1253
  AND request_payload ? 'triiodothyronine'
  AND request_payload->>'triiodothyronine' = '1.1'
  AND request_payload->>'thyroxine' = '8.0'
  AND request_payload->>'tsh_value' = '2.0';

-- Thyroid score distribution in stored Bio AI
-- (adjust JSON path if report shape differs)
```

## Out of scope

- Renaming `assessment_packages.package_code` from `METSIGHTS_ESSENTIALS` to `METSIGHTS_BASIC`
  on production (not required after this fix).