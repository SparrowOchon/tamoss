# API Reference

TAMOSS implements the BBC TAMS v8.2 API. The upstream specification is the core
contract for sources, flows, flow segments, tags, storage backends, webhooks,
objects, and deletion workflows.

- Upstream specification: <https://github.com/bbc/tams/tree/8.2>
- Local interactive docs: <https://api.tamoss.localtest.me/docs>

## Capability Map

| Capability | Contract surface | Explanation |
| --- | --- | --- |
| Flow Profiles | `/service/profiles`, `profile_id` on Flows | [Flow Profiles](../concepts/flow-profiles.md) |
| Flow lifecycle status | `status` on Flows and Flow list filters | Upstream OpenAPI specification |
| Initialisation Objects | `init_segments`, `init_object_id`, nested `init_object` | Upstream OpenAPI specification |
| Deterministic listings | Endpoint-specific `sort_by`, `reverse_order`, and paging headers | Upstream OpenAPI specification |
| Collection membership | Ordered optional-role collections and `collected_by_ids` filters | Upstream OpenAPI specification |
| Storage selection | Presigned selection plus storage tag value and existence filters | [Storage Backends](../concepts/storage-backends.md) |
| Service metadata | `/service` | BBC TAMS service identity and capabilities |
| Storage backend catalogue | `/service/storage-backends` | Registered TAMS storage backend metadata |
| Segment request events | `flows/segments_requested` webhook event | [TAMOSS Extension Events](#tamoss-extension-events) |

The upstream OpenAPI document is authoritative for request and response fields.
Capability pages explain TAMOSS persistence and lifecycle choices without
duplicating that schema.

## Product Health Endpoints

These endpoints are TAMOSS operational endpoints, not BBC TAMS resources:

| Endpoint | Purpose |
| --- | --- |
| `/healthz` | Process health. |
| `/readyz` | Readiness for serving traffic. |

## TAMOSS Extension Events

`flows/segments_requested` is a TAMOSS webhook event outside the BBC TAMS event
set. The runtime `/openapi.json` lists it under `x-tamoss-extension-events` on
the webhook `events` schema and documents its payload under `webhooks` with
`x-tamoss-extension: true`. Registrations that list only BBC events never
receive it.

The event is queued when a `GET` or `HEAD /flows/{flowId}/segments` request
with a finite `timerange` whose start and end differ, on its first page and
without `object_id`, covers a span with no registered Segment. Read-only Flows
never queue it because no Segment can be registered into them. Inclusive ends
are normalised, so `[a_b]` also asks for the instant `b`. The `event` body
carries `flow_id`, the requested `timerange`, `missing_timeranges` listing every
unindexed span in order, and `truncated`, which is `true` when more than 10000
spans were found and the list stops at the last one shown. Every such request
queues one event per subscribed webhook whose `flow_ids` and `source_ids`
selectors admit the Flow, so scope registrations with those selectors.

## Authentication

The API accepts the operator-generated token as a bearer token:

```bash
curl -k -H "Authorization: Bearer $TAMOSS_TOKEN" \
  https://api.tamoss.localtest.me/service
```

OAuth2/OIDC bearer tokens are accepted when the selected profile or external
configuration enables OAuth validation.

## Presigned URLs

Presigned URLs are temporary credentials. Do not paste complete URLs into
public issues, logs, or documentation.
