# Test pyramid snapshot

_Generated: `2026-11-28T11:01:57.151Z`_
_Source workflow run id: `46137598945`_
_Head SHA: `d21dd71`_

## Counts by layer (`epic` / Allure `layer`)

| Layer | `epic` / `layer` | Cases | Passed | Failed | Broken | Skipped |
| --- | --- | --: | --: | --: | --: | --: |
| Unit (base) | `unit` | **270** | 270 | 0 | 0 | 0 |
| Integration (middle) | `api` / `integration` | **207** | 207 | 0 | 0 | 0 |
| UI / E2E (top) | `end-to-end` / `ui` | **117** | 117 | 0 | 0 | 0 |
| **Σ pyramid layers** | | **594** | | | | |

## Shares (pyramid layers only)

| Layer | Share of Σ layers |
| --- | ---: |
| Unit (base) | 45.5% |
| Integration (middle) | 34.8% |
| UI / E2E (top) | 19.7% |

```text
UI / E2E (top)         117              ████████████
Integration (middle)   207         █████████████████████
Unit (base)            270      ████████████████████████████
```

## Advisory (planning only)

- Pyramid layer shares sit within the **soft** planning band documented in `docs/testing/test-pyramid.md` (not a merge gate).

## Quality gates (non-blocking, advisory)

These checks **never fail the workflow**; they surface in GitHub **Annotations** (warnings) and in the **Job summary** when `pyramid-check` runs (Test Report workflow).

| Gate id | Status | Detail |
| --- | --- | --- |
| PYRAMID_UNIT_SHARE_LOW | ✓ ok | unit ≥ 45% of Σ layers (actual 45.5%) |
| PYRAMID_E2E_SHARE_HIGH | ✓ ok | UI/E2E ≤ 28% of Σ layers (actual 19.7%) |
| PYRAMID_UNKNOWN_EPIC | ✓ ok | other epic count: 0 |

_Blocking failures: none (reserved for a future strict mode)._

Canonical policy: [`docs/testing/test-pyramid.md`](../test-pyramid.md).