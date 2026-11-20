# FOMU1026 — export Metsights record ids (run on prod)

SSH to the API server (path may be `/var/www/supershyft-api`), then:

```bash
cd /var/www/supershyft-api
git pull   # if script not on server yet, or paste scripts/export_fomu_bioai_record_ids.py
python scripts/export_fomu_bioai_record_ids.py --engagement-id 1253
```

Outputs:

- `docs/exports/fomu_bioai_primary_record_ids.csv` — full row per participant (Bio AI generated on primary)
- `docs/exports/fomu_bioai_metsights_record_ids_only.csv` — single column for Metsights ops

To restrict to the fallback-thyroid push cohort (same 1.1 / 8.0 / 2.0 fingerprint):

```bash
python scripts/export_fomu_bioai_record_ids.py --engagement-id 1253 --fallback-only
```

Copy CSV off the server with `scp`:

```bash
scp ubuntu@13.207.124.130:/var/www/supershyft-api/docs/exports/fomu_bioai_metsights_record_ids_only.csv .
```