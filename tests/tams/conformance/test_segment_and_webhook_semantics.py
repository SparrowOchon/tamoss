from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from tamoss.application import webhooks as webhooking
from tamoss.application.contexts import segments as segments_context
from tamoss.domain.model import WebhookDeliveryRecord

from tests.tams.support import (
    create_video_flow,
    flow_collection_item,
    multi_flow_payload,
    register_segment,
    video_flow_payload,
    webhook_payload,
)

pytestmark = [pytest.mark.tams_conformance, pytest.mark.tams_semantics]


def test_segment_reads_emit_effective_object_timerange_only_when_requested(
    client: TestClient,
) -> None:
    flow_id, _, _ = create_video_flow(client)
    equal_object_id = register_segment(client, flow_id)
    different_object_id = register_segment(
        client,
        flow_id,
        timerange="[20:0_30:0)",
        object_timerange="[100:0_110:0)",
    )

    omitted = client.get(f"/flows/{flow_id}/segments")
    false = client.get(
        f"/flows/{flow_id}/segments",
        params={"include_object_timerange": "false"},
    )
    included = client.get(
        f"/flows/{flow_id}/segments",
        params={"include_object_timerange": "true"},
    )

    assert omitted.status_code == 200
    assert false.status_code == 200
    assert included.status_code == 200
    assert all("object_timerange" not in item for item in omitted.json())
    assert all("object_timerange" not in item for item in false.json())
    timeranges = {
        item["object_id"]: item["object_timerange"] for item in included.json()
    }
    assert timeranges == {
        equal_object_id: "[0:0_10:0)",
        different_object_id: "[100:0_110:0)",
    }


def test_segments_sort_exclusive_range_before_adjacent_point_and_reverse(
    client: TestClient,
) -> None:
    flow_id, _, _ = create_video_flow(client)
    range_object_id = register_segment(
        client,
        flow_id,
        timerange="[1:0_2:0)",
    )
    point_object_id = register_segment(
        client,
        flow_id,
        timerange="[2:0]",
    )

    forward = client.get(f"/flows/{flow_id}/segments")
    reverse = client.get(
        f"/flows/{flow_id}/segments",
        params={"reverse_order": "true"},
    )

    assert forward.status_code == 200
    assert reverse.status_code == 200
    assert [item["object_id"] for item in forward.json()] == [
        range_object_id,
        point_object_id,
    ]
    assert [item["object_id"] for item in reverse.json()] == [
        point_object_id,
        range_object_id,
    ]
    assert forward.headers["x-paging-reverse-order"] == "false"
    assert reverse.headers["x-paging-reverse-order"] == "true"


def test_segment_webhooks_emit_effective_object_timerange_only_when_requested(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    flow_id, _, _ = create_video_flow(client)
    webhook_ids: dict[str, UUID] = {}
    for mode, option in (("omitted", None), ("false", False), ("true", True)):
        body = webhook_payload(events=["flows/segments_added"])
        if option is not None:
            body["include_object_timerange"] = option
        created = client.post("/service/webhooks", json=body)
        assert created.status_code == 201
        webhook_ids[mode] = UUID(created.json()["id"])

    equal_object_id = register_segment(client, flow_id)
    different_object_id = register_segment(
        client,
        flow_id,
        timerange="[20:0_30:0)",
        object_timerange="[100:0_110:0)",
    )

    deliveries = tamoss_app.state.tamoss_use_cases.repository.list_webhook_deliveries()
    segments_by_webhook = {
        webhook_id: {
            delivery.payload["event"]["segments"][0]["object_id"]: delivery.payload[
                "event"
            ]["segments"][0]
            for delivery in deliveries
            if delivery.webhook_id == webhook_id
        }
        for webhook_id in webhook_ids.values()
    }
    for mode in ("omitted", "false"):
        assert all(
            "object_timerange" not in segment
            for segment in segments_by_webhook[webhook_ids[mode]].values()
        )
    assert {
        object_id: segment["object_timerange"]
        for object_id, segment in segments_by_webhook[webhook_ids["true"]].items()
    } == {
        equal_object_id: "[0:0_10:0)",
        different_object_id: "[100:0_110:0)",
    }


def test_flow_collection_webhook_selector_distinguishes_omitted_empty_and_parent(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    child_flow_id, _, _ = create_video_flow(client)
    top_level_flow_id, _, _ = create_video_flow(client)
    parent_flow_id = uuid4()
    parent_source_id = uuid4()
    parent = client.put(
        f"/flows/{parent_flow_id}",
        json=multi_flow_payload(parent_flow_id, parent_source_id),
    )
    assert parent.status_code == 201
    collection = client.put(
        f"/flows/{parent_flow_id}/flow_collection",
        json=[flow_collection_item(child_flow_id)],
    )
    assert collection.status_code == 204

    webhook_ids = _register_collection_selector_webhooks(
        client,
        events=["flows/updated"],
        selector_name="flow_collected_by_ids",
        parent_id=parent_flow_id,
    )

    child_update = client.put(f"/flows/{child_flow_id}/label", json="child")
    top_level_update = client.put(f"/flows/{top_level_flow_id}/label", json="top-level")
    assert child_update.status_code == 204
    assert top_level_update.status_code == 204

    event_ids = _event_resource_ids_by_webhook(
        tamoss_app,
        resource_name="flow",
    )
    assert event_ids[webhook_ids["omitted"]] == {
        str(child_flow_id),
        str(top_level_flow_id),
    }
    assert event_ids[webhook_ids["empty"]] == {str(top_level_flow_id)}
    assert event_ids[webhook_ids["parent"]] == {str(child_flow_id)}


def test_source_collection_webhook_selector_distinguishes_omitted_empty_and_parent(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    child_flow_id = uuid4()
    child_source_id = uuid4()
    top_level_flow_id = uuid4()
    top_level_source_id = uuid4()
    parent_flow_id = uuid4()
    parent_source_id = uuid4()
    for flow_id, source_id, payload_factory in (
        (child_flow_id, child_source_id, video_flow_payload),
        (top_level_flow_id, top_level_source_id, video_flow_payload),
        (parent_flow_id, parent_source_id, multi_flow_payload),
    ):
        created = client.put(
            f"/flows/{flow_id}",
            json=payload_factory(flow_id, source_id),
        )
        assert created.status_code == 201
    collection = client.put(
        f"/flows/{parent_flow_id}/flow_collection",
        json=[flow_collection_item(child_flow_id)],
    )
    assert collection.status_code == 204

    webhook_ids = _register_collection_selector_webhooks(
        client,
        events=["sources/updated"],
        selector_name="source_collected_by_ids",
        parent_id=parent_source_id,
    )

    child_update = client.put(f"/sources/{child_source_id}/label", json="child")
    top_level_update = client.put(
        f"/sources/{top_level_source_id}/label", json="top-level"
    )
    assert child_update.status_code == 204
    assert top_level_update.status_code == 204

    event_ids = _event_resource_ids_by_webhook(
        tamoss_app,
        resource_name="source",
    )
    assert event_ids[webhook_ids["omitted"]] == {
        str(child_source_id),
        str(top_level_source_id),
    }
    assert event_ids[webhook_ids["empty"]] == {str(top_level_source_id)}
    assert event_ids[webhook_ids["parent"]] == {str(child_source_id)}


def test_flow_deletion_uses_pre_delete_collection_selector_context(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    child_flow_id, _, _ = create_video_flow(client)
    top_level_flow_id, _, _ = create_video_flow(client)
    parent_flow_id = uuid4()
    parent_source_id = uuid4()
    parent = client.put(
        f"/flows/{parent_flow_id}",
        json=multi_flow_payload(parent_flow_id, parent_source_id),
    )
    assert parent.status_code == 201
    collection = client.put(
        f"/flows/{parent_flow_id}/flow_collection",
        json=[flow_collection_item(child_flow_id)],
    )
    assert collection.status_code == 204
    register_segment(client, child_flow_id)

    webhook_ids = _register_collection_selector_webhooks(
        client,
        events=["flows/deleted"],
        selector_name="flow_collected_by_ids",
        parent_id=parent_flow_id,
    )

    assert client.delete(f"/flows/{child_flow_id}").status_code == 202
    assert (
        tamoss_app.state.tamoss_use_cases.deletion.process_pending_delete_requests()
        == 1
    )
    assert client.delete(f"/flows/{top_level_flow_id}").status_code == 204

    event_ids = _deleted_event_resource_ids_by_webhook(
        tamoss_app,
        id_name="flow_id",
    )
    assert event_ids[webhook_ids["omitted"]] == {
        str(child_flow_id),
        str(top_level_flow_id),
    }
    assert event_ids[webhook_ids["empty"]] == {str(top_level_flow_id)}
    assert event_ids[webhook_ids["parent"]] == {str(child_flow_id)}


def test_source_deletion_uses_context_from_its_deleted_flow(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    child_flow_id, child_source_id, _ = create_video_flow(client)
    top_level_flow_id, top_level_source_id, _ = create_video_flow(client)
    parent_flow_id = uuid4()
    parent_source_id = uuid4()
    parent = client.put(
        f"/flows/{parent_flow_id}",
        json=multi_flow_payload(parent_flow_id, parent_source_id),
    )
    assert parent.status_code == 201
    collection = client.put(
        f"/flows/{parent_flow_id}/flow_collection",
        json=[flow_collection_item(child_flow_id)],
    )
    assert collection.status_code == 204

    webhook_ids = _register_collection_selector_webhooks(
        client,
        events=["sources/deleted"],
        selector_name="source_collected_by_ids",
        parent_id=parent_source_id,
    )

    assert client.delete(f"/flows/{child_flow_id}").status_code == 204
    assert client.delete(f"/flows/{top_level_flow_id}").status_code == 204
    assert client.get(f"/sources/{child_source_id}").status_code == 404
    assert client.get(f"/sources/{top_level_source_id}").status_code == 404

    event_ids = _deleted_event_resource_ids_by_webhook(
        tamoss_app,
        id_name="source_id",
    )
    assert event_ids[webhook_ids["omitted"]] == {
        str(child_source_id),
        str(top_level_source_id),
    }
    assert event_ids[webhook_ids["empty"]] == {str(top_level_source_id)}
    assert event_ids[webhook_ids["parent"]] == {str(child_source_id)}


@pytest.mark.tamoss_extension
def test_partially_indexed_listing_queues_one_event_listing_every_missing_span(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id = _flow_with_gap(client)

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    assert [segment["timerange"] for segment in listed.json()] == [
        "[0:0_10:0)",
        "[20:0_30:0)",
    ]
    assert _segments_requested_events(tamoss_app) == [
        {
            "flow_id": str(flow_id),
            "timerange": "[0:0_40:0)",
            "missing_timeranges": ["[10:0_20:0)", "[30:0_40:0)"],
            "truncated": False,
        }
    ]


@pytest.mark.tamoss_extension
def test_listing_with_nothing_indexed_reports_the_whole_range_missing(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id, _, _ = create_video_flow(client)

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    assert listed.json() == []
    assert [
        event["missing_timeranges"] for event in _segments_requested_events(tamoss_app)
    ] == [["[0:0_40:0)"]]


@pytest.mark.tamoss_extension
def test_segment_request_event_reports_only_the_requested_range(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id, _, _ = create_video_flow(client)
    register_segment(client, flow_id, timerange="[0:0_25:0)")
    register_segment(client, flow_id, timerange="[60:0_70:0)")

    for timerange in ("[30:0_50:0)", "[20:0_40:0)", "[80:0_90:0)"):
        listed = client.get(
            f"/flows/{flow_id}/segments", params={"timerange": timerange}
        )
        assert listed.status_code == 200, timerange

    assert [
        (event["timerange"], event["missing_timeranges"])
        for event in _segments_requested_events(tamoss_app)
    ] == [
        ("[30:0_50:0)", ["[30:0_50:0)"]),
        ("[20:0_40:0)", ["[25:0_40:0)"]),
        ("[80:0_90:0)", ["[80:0_90:0)"]),
    ]


@pytest.mark.tamoss_extension
def test_head_listing_queues_the_event_like_get(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id = _flow_with_gap(client)

    probed = client.head(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert probed.status_code == 200
    assert probed.content == b""
    assert [
        event["missing_timeranges"] for event in _segments_requested_events(tamoss_app)
    ] == [["[10:0_20:0)", "[30:0_40:0)"]]


@pytest.mark.tamoss_extension
def test_every_uncovered_listing_queues_its_own_event(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id = _flow_with_gap(client)
    before = REGISTRY.get_sample_value("tamoss_segment_request_events_total") or 0.0

    for _ in range(2):
        listed = client.get(
            f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
        )
        assert listed.status_code == 200

    assert len(_segments_requested_events(tamoss_app)) == 2
    assert REGISTRY.get_sample_value("tamoss_segment_request_events_total") == (
        before + 2
    )


@pytest.mark.tamoss_extension
def test_fully_covered_listing_queues_no_event(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id = _flow_with_gap(client)

    for timerange in ("[0:0_10:0)", "[2:0_8:0)", "[20:0_30:0)"):
        listed = client.get(
            f"/flows/{flow_id}/segments", params={"timerange": timerange}
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    assert _segments_requested_events(tamoss_app) == []


@pytest.mark.tamoss_extension
def test_object_id_open_ended_point_empty_and_second_page_listings_queue_no_event(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id, _, _ = create_video_flow(client)
    object_id = register_segment(client, flow_id, timerange="[0:0_10:0)")
    register_segment(client, flow_id, timerange="[20:0_30:0)")

    for params in (
        {},
        {"timerange": "[0:0_40:0)", "object_id": object_id},
        {"timerange": "[0:0_"},
        {"timerange": "_40:0)"},
        {"timerange": "[15:0]"},
        {"timerange": "()"},
        {"timerange": "[0:0_40:0)", "limit": "1", "page": "1"},
    ):
        listed = client.get(f"/flows/{flow_id}/segments", params=params)
        assert listed.status_code == 200, params
        assert _segments_requested_events(tamoss_app) == [], params


@pytest.mark.tamoss_extension
def test_listing_for_an_unknown_flow_queues_no_event(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)

    listed = client.get(
        f"/flows/{uuid4()}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    assert listed.json() == []
    assert _segments_requested_events(tamoss_app) == []


@pytest.mark.tamoss_extension
def test_listing_without_a_subscriber_queues_nothing(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    created = client.post(
        "/service/webhooks", json=webhook_payload(events=["flows/segments_added"])
    )
    assert created.status_code == 201
    flow_id = _flow_with_gap(client)
    repository = tamoss_app.state.tamoss_use_cases.repository
    deliveries_before = len(repository.list_webhook_deliveries())

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    assert len(repository.list_webhook_deliveries()) == deliveries_before
    assert _segments_requested_events(tamoss_app) == []


@pytest.mark.tamoss_extension
def test_flow_ids_and_source_ids_selectors_scope_segment_request_events(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    flow_id, source_id, _ = create_video_flow(client)
    register_segment(client, flow_id, timerange="[0:0_10:0)")
    matching_flow = _subscribe_to_segment_requests(
        client, url="https://flow.example.test/webhook", flow_ids=[str(flow_id)]
    )
    matching_source = _subscribe_to_segment_requests(
        client, url="https://source.example.test/webhook", source_ids=[str(source_id)]
    )
    _subscribe_to_segment_requests(
        client, url="https://other-flow.example.test/webhook", flow_ids=[str(uuid4())]
    )
    _subscribe_to_segment_requests(
        client,
        url="https://other-source.example.test/webhook",
        source_ids=[str(uuid4())],
    )
    before = REGISTRY.get_sample_value("tamoss_segment_request_events_total") or 0.0

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_20:0)"}
    )

    assert listed.status_code == 200
    assert _deleted_event_resource_ids_by_webhook(tamoss_app, id_name="flow_id") == {
        matching_flow: {str(flow_id)},
        matching_source: {str(flow_id)},
    }
    assert REGISTRY.get_sample_value("tamoss_segment_request_events_total") == (
        before + 1
    )


@pytest.mark.tamoss_extension
def test_segment_request_event_uses_the_shared_envelope_and_starts_the_webhook(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    webhook_id = _subscribe_to_segment_requests(
        client, api_key_name="x-api-key", api_key_value="secret-value"
    )
    flow_id = _flow_with_gap(client)

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    (delivery,) = _segments_requested_deliveries(tamoss_app)
    assert set(delivery.payload) == {"event_timestamp", "event_type", "event"}
    assert delivery.payload["event_type"] == "flows/segments_requested"
    assert delivery.status == "pending"
    assert delivery.webhook_snapshot["api_key_value_ref"] == "webhook.api_key_value"
    assert "api_key_value" not in delivery.webhook_snapshot
    assert client.get(f"/service/webhooks/{webhook_id}").json()["status"] == "started"


@pytest.mark.tamoss_extension
def test_segment_request_event_flags_truncation_past_the_gap_limit(
    tamoss_app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(segments_context, "SEGMENT_REQUEST_GAP_LIMIT", 1)
    _subscribe_to_segment_requests(client)
    flow_id, _, _ = create_video_flow(client)
    for timerange in ("[0:0_1:0)", "[2:0_3:0)", "[4:0_5:0)"):
        register_segment(client, flow_id, timerange=timerange)

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_10:0)"}
    )

    assert listed.status_code == 200
    assert _segments_requested_events(tamoss_app) == [
        {
            "flow_id": str(flow_id),
            "timerange": "[0:0_10:0)",
            "missing_timeranges": ["[1:0_2:0)"],
            "truncated": True,
        }
    ]


@pytest.mark.tamoss_extension
def test_read_only_flow_listing_queues_no_event(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id = _flow_with_gap(client)
    assert client.put(f"/flows/{flow_id}/read_only", json=True).status_code == 204

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert _segments_requested_events(tamoss_app) == []


@pytest.mark.tamoss_extension
def test_listing_succeeds_when_publishing_the_event_raises(
    tamoss_app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(**_kwargs: object) -> list[object]:
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(webhooking, "publish_segments_requested", explode)
    _subscribe_to_segment_requests(client)
    flow_id = _flow_with_gap(client)

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert _segments_requested_events(tamoss_app) == []


@pytest.mark.tamoss_extension
def test_segment_request_reporting_adds_no_response_headers(
    tamoss_app: FastAPI,
    client: TestClient,
) -> None:
    _subscribe_to_segment_requests(client)
    flow_id = _flow_with_gap(client)

    listed = client.get(
        f"/flows/{flow_id}/segments", params={"timerange": "[0:0_40:0)"}
    )

    assert listed.status_code == 200
    assert not [name for name in listed.headers if name.lower().startswith("x-tamoss-")]
    assert listed.headers["x-paging-timerange"] == "[0:0_30:0)"
    assert listed.headers["x-paging-count"] == "2"
    assert len(_segments_requested_events(tamoss_app)) == 1


def _register_collection_selector_webhooks(
    client: TestClient,
    *,
    events: list[str],
    selector_name: str,
    parent_id: UUID,
) -> dict[str, UUID]:
    selectors: tuple[tuple[str, list[str] | None], ...] = (
        ("omitted", None),
        ("empty", []),
        ("parent", [str(parent_id)]),
    )
    webhook_ids: dict[str, UUID] = {}
    for mode, selector in selectors:
        body = webhook_payload(
            url=f"https://{mode}.example.test/webhook",
            events=events,
        )
        if selector is not None:
            body[selector_name] = selector
        created = client.post("/service/webhooks", json=body)
        assert created.status_code == 201
        payload = created.json()
        if selector is None:
            assert selector_name not in payload
        else:
            assert payload[selector_name] == selector
        webhook_id = UUID(payload["id"])
        stored = client.get(f"/service/webhooks/{webhook_id}")
        assert stored.status_code == 200
        if selector is None:
            assert selector_name not in stored.json()
        else:
            assert stored.json()[selector_name] == selector
        webhook_ids[mode] = webhook_id
    return webhook_ids


def _event_resource_ids_by_webhook(
    tamoss_app: FastAPI,
    *,
    resource_name: str,
) -> dict[UUID, set[str]]:
    deliveries = tamoss_app.state.tamoss_use_cases.repository.list_webhook_deliveries()
    return {
        webhook_id: {
            delivery.payload["event"][resource_name]["id"]
            for delivery in deliveries
            if delivery.webhook_id == webhook_id
        }
        for webhook_id in {delivery.webhook_id for delivery in deliveries}
    }


def _deleted_event_resource_ids_by_webhook(
    tamoss_app: FastAPI,
    *,
    id_name: str,
) -> dict[UUID, set[str]]:
    deliveries = tamoss_app.state.tamoss_use_cases.repository.list_webhook_deliveries()
    return {
        webhook_id: {
            delivery.payload["event"][id_name]
            for delivery in deliveries
            if delivery.webhook_id == webhook_id
        }
        for webhook_id in {delivery.webhook_id for delivery in deliveries}
    }


def _subscribe_to_segment_requests(client: TestClient, **overrides: object) -> UUID:
    created = client.post(
        "/service/webhooks",
        json=webhook_payload(events=["flows/segments_requested"], **overrides),
    )
    assert created.status_code == 201
    return UUID(created.json()["id"])


def _flow_with_gap(client: TestClient) -> UUID:
    flow_id, _, _ = create_video_flow(client)
    register_segment(client, flow_id, timerange="[0:0_10:0)")
    register_segment(client, flow_id, timerange="[20:0_30:0)")
    return flow_id


def _segments_requested_deliveries(tamoss_app: FastAPI) -> list[WebhookDeliveryRecord]:
    deliveries = tamoss_app.state.tamoss_use_cases.repository.list_webhook_deliveries()
    return [
        delivery
        for delivery in deliveries
        if delivery.event_type == "flows/segments_requested"
    ]


def _segments_requested_events(tamoss_app: FastAPI) -> list[dict[str, object]]:
    return [
        delivery.payload["event"]
        for delivery in _segments_requested_deliveries(tamoss_app)
    ]
