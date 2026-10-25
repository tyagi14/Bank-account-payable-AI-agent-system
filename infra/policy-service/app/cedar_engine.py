"""Loads the Cedar policies, schema and entity attributes from the policies/ directory."""
import json
from dataclasses import dataclass
from pathlib import Path

import cedarpy

from app.lint import lint

NAMESPACE = "Custodian"


@dataclass(frozen=True)
class CedarBundle:
    policies: "cedarpy.PolicySet"
    schema: str
    ids: dict[str, str]  # cedar's positional id (policy0...) -> @id annotation
    entities: dict
    sources: dict[str, str]


def load(policy_dir: Path) -> CedarBundle:
    sources = {p.name: p.read_text() for p in sorted(policy_dir.glob("*.cedar"))}
    text = "\n".join(sources.values())
    schema = (policy_dir / "schema.cedarschema.json").read_text()
    validation = cedarpy.validate_policies(text, schema)
    if not validation.validation_passed:
        raise ValueError(f"policies fail schema validation: {[str(e) for e in validation.errors]}")
    if problems := lint(text):
        raise ValueError(f"policies are overly permissive: {problems}")
    parsed = json.loads(cedarpy.policies_to_json_str(text))["staticPolicies"]
    ids = {pid: (p.get("annotations") or {}).get("id", pid) for pid, p in parsed.items()}
    entities = json.loads((policy_dir / "entities.json").read_text())
    return CedarBundle(cedarpy.PolicySet.from_str(text), schema, ids, entities, sources)


def _uid(kind: str, ident: str) -> dict:
    return {"type": f"{NAMESPACE}::{kind}", "id": ident}


def build_entities(bundle: CedarBundle, principal: dict, resource: dict) -> list[dict]:
    """Principal/resource attributes come from server-side config (or the verified JWT role), never the caller."""
    levels = bundle.entities["classificationLevels"]
    if principal["type"] == "Agent":
        agent = bundle.entities["agents"].get(principal["id"])
        attrs = {"trustTier": agent["trustTier"], "clearance": agent["clearance"]} if agent else {"trustTier": "unknown", "clearance": -1}
    else:
        attrs = {"role": principal.get("role") or ""}
    resource_attrs = {}
    if resource["type"] == "DataAsset":
        asset = bundle.entities["dataAssets"].get(resource["id"])
        resource_attrs = {"classification": levels[asset["classification"]] if asset else 99}
    return [
        {"uid": _uid(principal["type"], principal["id"]), "attrs": attrs, "parents": []},
        {"uid": _uid(resource["type"], resource["id"]), "attrs": resource_attrs, "parents": []},
    ]


def authorize(bundle: CedarBundle, principal: dict, action: str, resource: dict, context: dict) -> tuple[bool, list[str], list[str]]:
    request = {
        "principal": _uid(principal["type"], principal["id"]),
        "action": _uid("Action", action),
        "resource": _uid(resource["type"], resource["id"]),
        "context": context,
    }
    result = cedarpy.is_authorized(request, bundle.policies, build_entities(bundle, principal, resource), schema=bundle.schema)
    reasons = [bundle.ids.get(r, r) for r in result.diagnostics.reasons]
    errors = [str(e) for e in result.diagnostics.errors]
    return result.decision == cedarpy.Decision.Allow, reasons, errors
