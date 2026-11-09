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
| Missing segment events | `flows/segments_missing` webhook event | [TAMOSS Extension Events](#tamoss-extension-events) |
| Missing flow events | `flows/flow_missing` webhook event | [TAMOSS Extension Events](#tamoss-extension-events) |

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

`flows/segments_missing` and `flows/flow_missing` are TAMOSS webhook events
outside the BBC TAMS event set. The runtime `/openapi.json` lists them under
`x-tamoss-extension-events` on the webhook `events` schema and documents their
payloads under `webhooks` with `x-tamoss-extension: true`. Registrations that
list only BBC events never receive them, and the events never change the
response of the request that queues them.

### flows/segments_missing

The event is queued when a `GET` or `HEAD /flows/{flowId}/segments` request
with a finite `timerange` whose start and end differ, on its first page and
without `object_id`, covers a span with no registered Segment. Read-only Flows
never queue it because no Segment can be registered into them. Inclusive ends
are normalised, so `[a_b]` also asks for the instant `b`. The `event` body
carries `flow_id`, the requested `timerange`, `missing_timeranges` listing
every unindexed span in order, `truncated`, which is `true` when more than
10000 spans were found and the list stops at the last one shown, and `flow`,
the requested Flow as stored, including its `tags` and `container_mapping`. The listing also queues the event when the Flow itself
does not exist: the response stays an empty listing, the whole requested
timerange is reported missing, and `flow` is omitted, so a missing `flow`
means the Flow is not in the store. Unknown Flows are only reported when the
requested id matches the BBC TAMS `uuid` pattern.

For an existing Flow, every such request queues one event per subscribed
webhook whose `flow_ids`, `source_ids` and collected-by selectors admit the
Flow, so scope registrations with those selectors. When the Flow does not
exist, only its requested id is known: a registration matches when its
`flow_ids` selector is omitted or contains the id and each of its other
selectors is omitted or an empty list, while a non-empty `source_ids` or
collected-by selector never matches an unknown Flow.

### flows/flow_missing

`flows/flow_missing` is queued when a `GET` or `HEAD /flows` listing filtered
only by `tag.{name}` or `tag_exists.{name}` parameters matches no Flows on its
first page, which tells a subscriber the store holds no Flow carrying the
requested tags. Clients that look up a multi-flow by a tag such as
`tag.SOURCE.id` use it to learn that the content is absent from the store
rather than merely unindexed, which `flows/segments_missing` reports once the
Flow is known. Listings that also narrow by any other filter, such as
`source_id`, `timerange`, `format`, `codec`, `label`, `profile_id`, `status`,
frame dimensions, `init_segments` or collection membership, never queue it
because an empty narrowed result no longer proves the tags are absent.
`sort_by`, `reverse_order` and `limit` do not suppress it. The `event` body
carries `tags`, the requested tag value filters by tag name with each value
list sorted, and `tag_exists`, the requested existence filters by tag name.

No Flow or Source is known when the event fires, so a registration matches
only when its `flow_ids` and `source_ids` selectors are omitted and each of
its collected-by selectors is omitted or an empty list.

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
