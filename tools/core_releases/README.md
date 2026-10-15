# Core release approvals (Stage P1.1)

Auditable authorization for Host Shell **core** path changes.

## Rules

1. `CORE_RELEASE=approved` alone is **rejected**.
2. Set `CORE_RELEASE_APPROVAL=<id>` where `<id>.json` lives in this directory.
3. The approval `base_sha` must equal the CI comparison base (`BASE_SHA`).
4. Approvals that authorize changes to protection machinery
   (`tools/core_protection.json`, the checker, Tool Protection workflow, or this
   directory) must **already exist on the comparison base** — they cannot be
   introduced in the same PR that weakens protection.

## Template

See `_TEMPLATE.json`. Copy to `<approval_id>.json` and fill fields. Do not commit
private keys or production secrets here.
