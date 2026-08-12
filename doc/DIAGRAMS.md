# Diagrams

**The authoritative architecture diagrams live in the root [README](../README.md)**,
as Mermaid blocks that GitHub renders. They are versioned with the code, so they can be
corrected in the same commit as the change that dated them — which is exactly what the
PNGs below could not do.

## Superseded PNGs

The `.png` files in this folder were generated on 2026-07-08 and are **known to be
wrong** as of 2026-08-12. Kept for provenance only. Do not use them in a submission,
a pitch, or a code review.

| File | Problem |
|---|---|
| `high_level_architecture (3).png`, `(4).png` | Show an **Orchestrator Agent as a deployed Cloud Run service**. It is a library imported by the API Gateway; Cloud Build builds five images and none is an orchestrator. Also **omit the Escalation Service** entirely, which is deployed and is the human-in-the-loop path |
| `agent_sequence_flow.png`, `(1).png` | Same orchestrator-as-a-service error in the call sequence |
| `low_level_component_design (1).png` | Predates the payments, support, API-key and analytics packages under `shared/` |
| `deployment_diagram.png` | Predates Cloud Monitoring, the payment secrets, and the reporting agent's move to the `cg-runtime` identity |
| `erd_data_model.png` | Predates the entitlement counters (`reports_granted` / `reports_consumed` / `entitlement_source` / `entitlement_expires_at`) and tenant `status` |
| `build_timeline.png` | Historical, harmless |

## Why they went stale

Nothing in the pipeline could tell us they had. A PNG is opaque to code review: it can
contradict the system it documents indefinitely and no test, linter or diff will
mention it. The same failure mode produced the weekly-report outage described in the
README — a thing that looked right, was never checked, and quietly wasn't.

Mermaid in Markdown fixes the mechanism, not just this instance. The diagram source
sits in the same diff as the code, so a reviewer changing the architecture sees the
diagram that claims otherwise.

## Regenerating

Paste any Mermaid block from the README into <https://mermaid.live> to export PNG or
SVG — useful for slides or a Devpost submission, where Mermaid is not rendered. Treat
those exports as disposable build artifacts: regenerate them from the README rather
than editing and committing them, or you have recreated the problem above.
