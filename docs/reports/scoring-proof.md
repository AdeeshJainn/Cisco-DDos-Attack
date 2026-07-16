# Argus scoring proof

Fresh seeds: `9200` through `9201` (2 per profile).

| Profile | Cases | GT incidents | Decision | Decision+reason | Attack recall | Origin | File:line | False acts | Detect p50 | Resolution p50 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| quiet_day | 2 | 0 | 100.0% | 100.0% | — | — | — | 0 | — | — |
| match_night | 2 | 4 | 100.0% | 100.0% | 100.0% | 100.0% | — | 0 | 8s | 91s |
| cascade_night | 2 | 2 | 100.0% | 100.0% | — | 100.0% | 100.0% | 0 | — | 91s |
| combo_night | 2 | 8 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 8s | 91s |

