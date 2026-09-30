from __future__ import annotations

import pytest

from tests.support.fixtures import load_yaml_fixture
from tests.support.paths import REPO_ROOT, load_python_module


def _load_preprocess_module():
    return load_python_module(
        "preprocess_openapi",
        REPO_ROOT / "src/scripts/preprocess_openapi.py",
    )


def test_reference_rewriting_handles_parsed_yaml_values() -> None:
    module = _load_preprocess_module()
    openapi = load_yaml_fixture("preprocess_openapi/reference_rewriting.yaml")

    module.rewrite_external_refs_for_public_contract(openapi)

    schema = openapi["paths"]["/flows"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    examples = openapi["paths"]["/flows"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["examples"]
    assert schema["$ref"] == "vendor/bbc-tams/api/schemas/flow.yaml"
    assert (
        examples["quoted"]["$ref"] == "vendor/bbc-tams/api/examples/flows.yaml#/quoted"
    )
    assert examples["plain"]["$ref"] == "vendor/bbc-tams/api/examples/flows.yaml#/plain"


def test_external_example_rewriting() -> None:
    module = _load_preprocess_module()
    openapi = load_yaml_fixture("preprocess_openapi/external_example_rewriting.yaml")

    module.rewrite_external_refs_for_public_contract(openapi)

    external_value = openapi["paths"]["/flows"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["examples"]["flow"]["externalValue"]
    assert external_value == "vendor/bbc-tams/api/examples/flows.json"


def test_targeted_description_corrections() -> None:
    module = _load_preprocess_module()
    openapi = load_yaml_fixture(
        "preprocess_openapi/targeted_description_corrections.yaml"
    )

    module.apply_public_contract_text_corrections(openapi)

    parameter = openapi["paths"]["/webhooks/{webhookId}"]["parameters"][0]
    delete_request_id = openapi["components"]["schemas"]["FlowDeleteRequest"][
        "properties"
    ]["id"]
    delete_description = openapi["paths"]["/flow-delete-requests"]["get"]["description"]
    filter_description = openapi["components"]["schemas"]["FlowDeleteRequest"][
        "properties"
    ]["filter"]["description"]
    assert parameter["description"] == (
        "A Universally Unique Identifier (UUID) as defined in RFC9562"
    )
    assert delete_request_id["description"] == "ID of the deletion request"
    assert delete_description == "List ongoing flow deletion requests."
    assert filter_description == "A comma-separated value"


def test_model_contract_embedding_rewrites_external_schema_refs() -> None:
    module = _load_preprocess_module()
    openapi = {
        "components": {},
        "paths": {
            "/sources/{sourceId}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": module.BBC_SCHEMA_REF_PREFIX
                                        + "source.json"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    module.embed_external_schema_refs_for_contract(
        openapi,
        schema_root=REPO_ROOT / "src/vendor/bbc-tams/api/schemas",
    )

    schema = openapi["paths"]["/sources/{sourceId}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    components = openapi["components"]["schemas"]
    assert schema["$ref"] == "#/components/schemas/Source"
    assert components["Source"]["properties"]["id"]["$ref"] == (
        "#/components/schemas/Uuid"
    )
    assert "Uuid" in components


def _load_extensions_module():
    return load_python_module(
        "openapi_extensions",
        REPO_ROOT / "src/scripts/openapi_extensions.py",
    )


def _embedded_webhook_spec() -> dict:
    return {
        "components": {
            "schemas": {
                "Uuid": {"type": "string"},
                "Timerange": {"type": "string"},
                "Webhook": {
                    "properties": {
                        "events": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["flows/created", "flows/segments_added"],
                            },
                        }
                    }
                },
            }
        },
        "webhooks": {"flows/created": {"post": {}}},
    }


def test_model_contract_extensions_add_the_segments_requested_event_once() -> None:
    module = _load_extensions_module()
    openapi = _embedded_webhook_spec()

    module.apply_tamoss_model_contract_extensions(openapi)
    module.apply_tamoss_model_contract_extensions(openapi)

    items = openapi["components"]["schemas"]["Webhook"]["properties"]["events"]["items"]
    assert items["enum"] == [
        "flows/created",
        "flows/segments_added",
        "flows/segments_requested",
    ]
    assert items["x-tamoss-extension-events"] == ["flows/segments_requested"]
    assert list(openapi["webhooks"]) == ["flows/created", "flows/segments_requested"]


def test_model_contract_extensions_document_the_segments_requested_webhook() -> None:
    module = _load_extensions_module()
    openapi = _embedded_webhook_spec()

    module.apply_tamoss_model_contract_extensions(openapi)

    entry = openapi["webhooks"]["flows/segments_requested"]
    schema = entry["post"]["requestBody"]["content"]["application/json"]["schema"]
    event = schema["properties"]["event"]
    assert entry["x-tamoss-extension"] is True
    assert entry["post"]["security"] == [{}]
    assert schema["required"] == ["event_timestamp", "event_type", "event"]
    assert schema["properties"]["event_type"]["const"] == "flows/segments_requested"
    assert event["required"] == [
        "flow_id",
        "timerange",
        "missing_timeranges",
        "truncated",
    ]
    assert event["properties"]["flow_id"] == {"$ref": "#/components/schemas/Uuid"}
    assert event["properties"]["missing_timeranges"]["items"] == {
        "$ref": "#/components/schemas/Timerange"
    }
    assert entry["post"]["responses"]["200"]["description"] == (
        "Webhook received successfully"
    )
    assert openapi["webhooks"]["flows/created"] == {"post": {}}


def test_model_contract_extensions_fail_when_the_events_enum_is_missing() -> None:
    module = _load_extensions_module()
    openapi = _embedded_webhook_spec()
    openapi["components"]["schemas"]["Webhook"]["properties"]["events"]["items"] = {
        "$ref": "#/components/schemas/EventType"
    }

    with pytest.raises(ValueError, match="events enum"):
        module.apply_tamoss_model_contract_extensions(openapi)
