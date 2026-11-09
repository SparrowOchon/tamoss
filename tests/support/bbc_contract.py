"""Validate HTTP payloads against the vendored BBC contract, with the webhook
events enum extended by the TAMOSS extension events so registrations that echo
them stay valid."""

import json
from functools import cache

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.support.paths import BBC_API_SPEC_PATH

TAMOSS_EXTENSION_EVENTS = ("flows/segments_missing", "flows/flow_missing")


@cache
def bbc_spec() -> dict:
    return yaml.safe_load(BBC_API_SPEC_PATH.read_text())


def _with_tamoss_extension_events(name: str, content: dict) -> dict:
    if name != "webhook.json":
        return content
    enum = content["properties"]["events"]["items"]["enum"]
    enum.extend(event for event in TAMOSS_EXTENSION_EVENTS if event not in enum)
    return content


@cache
def bbc_registry() -> Registry:
    resources = [(BBC_API_SPEC_PATH.as_uri(), bbc_spec())]
    resources.extend(
        (
            path.as_uri(),
            _with_tamoss_extension_events(path.name, json.loads(path.read_text())),
        )
        for path in sorted((BBC_API_SPEC_PATH.parent / "schemas").glob("*.json"))
    )
    return Registry().with_resources(
        (uri, Resource.from_contents(content, default_specification=DRAFT202012))
        for uri, content in resources
    )


def bbc_validator(reference: str) -> Draft202012Validator:
    uri = (
        BBC_API_SPEC_PATH.as_uri() + reference
        if reference.startswith("#")
        else (BBC_API_SPEC_PATH.parent / "schemas" / reference).as_uri()
    )
    return Draft202012Validator({"$ref": uri}, registry=bbc_registry())


@cache
def response_validator(path: str, method: str, status: int) -> Draft202012Validator:
    escaped_path = path.replace("~", "~0").replace("/", "~1")
    return bbc_validator(
        f"#/paths/{escaped_path}/{method.lower()}/responses/{status}"
        "/content/application~1json/schema"
    )


def response_contract(path: str, method: str, status: int) -> dict:
    response = bbc_spec()["paths"][path][method.lower()]["responses"][str(status)]
    if "$ref" in response:
        return (
            bbc_registry()
            .resolver(BBC_API_SPEC_PATH.as_uri())
            .lookup(response["$ref"])
            .contents
        )
    return response
