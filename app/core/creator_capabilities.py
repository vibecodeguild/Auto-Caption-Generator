from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.core.creator_production import ARTIFACT_SCHEMA_VERSION, canonical_hash, validate_artifact
from app.core.file_utils import sha256_file


CSS_TRANSITIONS = (
    "push-slide",
    "vertical-push",
    "elastic-push",
    "squeeze",
    "circle-iris",
    "diamond-iris",
    "diagonal-split",
    "3d-card-flip",
    "zoom-through",
    "zoom-out",
    "crossfade",
    "blur-crossfade",
    "focus-pull",
    "color-dip",
    "staggered-blocks",
    "horizontal-blinds",
    "vertical-blinds",
    "light-leak",
    "overexposure-burn",
    "film-burn",
    "glitch",
    "chromatic-aberration",
    "ripple",
    "vhs-tape",
    "shutter",
    "clock-wipe",
    "grid-dissolve",
    "gravity-drop",
    "morph-circle",
    "blur-through",
    "directional-blur",
    "page-burn",
)
BLOCKED_CSS_CONCEPTS = {
    "star-iris": "The pinned native catalog says polygon interpolation is broken.",
    "tilt-shift": "The pinned native catalog says selective CSS blur is unavailable.",
    "lens-flare": "The pinned native catalog says the result is a visible shape rather than an optical flare.",
    "hinge/door": "The pinned native catalog says the effect distorts too quickly.",
}
DOCUMENTED_SHADER_ROUTES = (
    "whip-pan",
    "cinematic-zoom",
    "gravitational-lens",
    "sdf-iris",
    "cross-warp-morph",
    "domain-warp",
    "shader-light-leak",
    "thermal-distortion",
    "shader-glitch",
    "chromatic-split",
    "ridged-burn",
    "ripple-waves",
    "swirl-vortex",
)
SHADER_ALIASES = {
    "shader-light-leak": "light-leak",
    "shader-glitch": "glitch",
}
PLV_TRANSITION_TEMPLATES = (
    "crossfade",
    "blur-crossfade",
    "push-slide",
    "zoom-through",
    "squeeze",
)
EXPECTED_RULE_COUNT = 48
EXPECTED_BLUEPRINT_COUNT = 22
COMMON_GSAP_SUPPORT_PATHS = (
    "adapters/gsap.md",
    "adapters/gsap-transforms-and-perf.md",
    "adapters/gsap-easing-and-stagger.md",
    "adapters/gsap-timeline-and-labels.md",
)


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Required capability source is missing: {path.name}")
    return path.read_text(encoding="utf-8")


def _tree_hash(root: Path) -> str:
    """Hash ordered relative-path/NUL/lowercase-file-SHA256/newline rows."""

    rows = bytearray()
    for source in sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    ):
        relative = source.relative_to(root).as_posix()
        rows.extend(relative.encode("utf-8"))
        rows.extend(b"\0")
        rows.extend(sha256_file(source).lower().encode("ascii"))
        rows.extend(b"\n")
    return hashlib.sha256(rows).hexdigest()


def _source_entry(
    capability_id: str,
    *,
    category: str,
    scope: str,
    relative_path: str,
    source_hash: str,
    section_anchor: str | None = None,
    availability: str = "source-enabled",
    reason: str | None = None,
) -> dict:
    entry = {
        "id": capability_id,
        "category": category,
        "scope": scope,
        "source": {
            "relativePath": relative_path,
            "sha256": source_hash,
            "sectionAnchor": section_anchor,
        },
        "inventoryState": "inventoried",
        "sourceAvailability": availability,
        "adaptationEligibility": "adaptable" if availability == "source-enabled" else "not-adaptable",
        "implementationMaturity": "source-only",
        "technicalAdmission": "blocked" if availability == "globally-blocked" else "unassessed",
        "productionSelection": "not-selectable",
        "channelPreference": "allowed",
        "aliases": [],
        "requirements": [],
        "knownIncompatibilities": [],
        "linkedImplementationIds": [],
    }
    if reason:
        entry["statusReason"] = reason
    return entry


def _indexed_rules(skill_root: Path) -> tuple[list[dict], list[dict]]:
    index_path = skill_root / "rules-index.md"
    index_text = _read_text(index_path)
    references = re.findall(r"rules/([a-z0-9-]+)\.md", index_text)
    if not references:
        raise ValueError("The pinned rules index contains no rule references.")
    files = {path.stem: path for path in (skill_root / "rules").glob("*.md")}
    unique_references = set(references)
    if unique_references != set(files):
        missing = sorted(unique_references - set(files))
        unindexed = sorted(set(files) - unique_references)
        raise ValueError(f"Rule index/file mismatch; missing={missing}, unindexed={unindexed}")
    if len(files) != EXPECTED_RULE_COUNT:
        raise ValueError(f"Pinned rule inventory changed: expected {EXPECTED_RULE_COUNT}, found {len(files)}.")
    categories: dict[str, set[str]] = {rule_id: set() for rule_id in unique_references}
    current_heading = ""
    for line in index_text.splitlines():
        if line.startswith("##"):
            current_heading = re.sub(r"^#+\s*", "", line).strip()
        for rule_id in re.findall(r"rules/([a-z0-9-]+)\.md", line):
            if current_heading:
                categories[rule_id].add(current_heading)
    entries = []
    resources = []
    for rule_id, path in sorted(files.items()):
        relative = f"rules/{path.name}"
        digest = sha256_file(path)
        entry = _source_entry(
            f"hf-rule:{rule_id}",
            category="native-source-recipe",
            scope="atomic-operation",
            relative_path=relative,
            source_hash=digest,
        )
        entry["indexCategories"] = sorted(categories[rule_id])
        entries.append(entry)
        resources.append({"id": f"hf-rule-source:{rule_id}", "relativePath": relative, "sha256": digest})
    return entries, resources


def _indexed_blueprints(skill_root: Path) -> tuple[list[dict], list[dict]]:
    index_path = skill_root / "blueprints-index.md"
    index_text = _read_text(index_path)
    references = re.findall(r'<blueprint\s+id="([a-z0-9-]+)"', index_text)
    if len(references) != len(set(references)):
        raise ValueError("The pinned blueprint index contains duplicate canonical IDs.")
    files = {path.stem: path for path in (skill_root / "blueprints").glob("*.md")}
    if set(references) != set(files):
        missing = sorted(set(references) - set(files))
        unindexed = sorted(set(files) - set(references))
        raise ValueError(f"Blueprint index/file mismatch; missing={missing}, unindexed={unindexed}")
    if len(files) != EXPECTED_BLUEPRINT_COUNT:
        raise ValueError(
            f"Pinned blueprint inventory changed: expected {EXPECTED_BLUEPRINT_COUNT}, found {len(files)}."
        )
    entries = []
    resources = []
    for blueprint_id, path in sorted(files.items()):
        relative = f"blueprints/{path.name}"
        digest = sha256_file(path)
        entries.append(
            _source_entry(
                f"hf-blueprint:{blueprint_id}",
                category="native-source-recipe",
                scope="blueprint-macro",
                relative_path=relative,
                source_hash=digest,
            )
        )
        resources.append(
            {"id": f"hf-blueprint-source:{blueprint_id}", "relativePath": relative, "sha256": digest}
        )
    return entries, resources


def _support_resources(skill_root: Path) -> list[dict]:
    resources = [
        {
            "id": "hf-contract:animation",
            "relativePath": "SKILL.md",
            "sha256": sha256_file(skill_root / "SKILL.md"),
            "surface": "contract",
        }
    ]
    for relative_root in ("adapters", "techniques", "examples"):
        root = skill_root / relative_root
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(skill_root).as_posix()
            resource_id = (
                f"hf-example:{path.stem}"
                if relative_root == "examples"
                else f"hf-support:{relative.lower()}"
            )
            resources.append(
                {
                    "id": resource_id,
                    "relativePath": relative,
                    "sha256": sha256_file(path),
                    "surface": relative_root,
                }
            )
    return resources


def _attach_required_resources(
    *,
    skill_root: Path,
    entries: list[dict],
    source_resources: list[dict],
    support_resources: list[dict],
) -> None:
    all_resources = [*source_resources, *support_resources]
    resource_ids_by_source: dict[tuple[str, str], list[str]] = {}
    for resource in all_resources:
        resource_ids_by_source.setdefault(
            (resource["relativePath"], resource["sha256"]), []
        ).append(resource["id"])
    resource_ids_by_path = {
        resource["relativePath"]: resource["id"] for resource in all_resources
    }
    rule_ids_by_name = {
        entry["id"].removeprefix("hf-rule:"): next(
            resource["id"]
            for resource in source_resources
            if resource["relativePath"] == entry["source"]["relativePath"]
            and resource["sha256"] == entry["source"]["sha256"]
        )
        for entry in entries
        if entry["id"].startswith("hf-rule:")
    }
    example_ids_by_name = {
        Path(resource["relativePath"]).stem: resource["id"]
        for resource in support_resources
        if resource["surface"] == "examples"
    }
    common_ids = ["hf-contract:animation"]
    common_ids.extend(
        resource_ids_by_path[path]
        for path in COMMON_GSAP_SUPPORT_PATHS
        if path in resource_ids_by_path
    )

    for entry in entries:
        required = list(common_ids)
        required.extend(
            resource_ids_by_source.get(
                (entry["source"]["relativePath"], entry["source"]["sha256"]), []
            )
        )
        source_path = skill_root / entry["source"]["relativePath"]
        if source_path.is_file() and source_path.suffix.lower() == ".md":
            source_text = source_path.read_text(encoding="utf-8")
            for rule_id, resource_id in rule_ids_by_name.items():
                if f"`{rule_id}`" in source_text or f"rules/{rule_id}.md" in source_text:
                    required.append(resource_id)
            for example_id, resource_id in example_ids_by_name.items():
                if re.search(
                    rf"(?<![a-z0-9-]){re.escape(example_id)}(?![a-z0-9-])",
                    source_text,
                    flags=re.IGNORECASE,
                ):
                    required.append(resource_id)
        entry["requiredResourceIds"] = list(dict.fromkeys(required))


def required_capability_resource_ids(catalog: dict, capability_id: str) -> list[str]:
    matching = [entry for entry in catalog["capabilities"] if entry["id"] == capability_id]
    if not matching:
        raise ValueError(f"Unknown capability: {capability_id}")
    required = matching[0].get("requiredResourceIds")
    if not isinstance(required, list) or not required:
        raise RuntimeError(
            f"Capability has no complete frozen instruction dependency set: {capability_id}"
        )
    available = {
        resource["id"]
        for resource in [*catalog["sourceResources"], *catalog["supportResources"]]
    }
    missing = sorted(set(required) - available)
    if missing:
        raise RuntimeError(
            "Capability instruction dependencies are unavailable: " + ", ".join(missing)
        )
    return list(dict.fromkeys(str(resource_id) for resource_id in required))


def direct_capability_source_resource(catalog: dict, capability_id: str) -> dict:
    """Return the exact frozen recipe resource that defines a capability."""

    matching = [entry for entry in catalog["capabilities"] if entry["id"] == capability_id]
    if not matching:
        raise ValueError(f"Unknown capability: {capability_id}")
    source = matching[0]["source"]
    resources = [
        resource
        for resource in catalog["sourceResources"]
        if resource["relativePath"] == source["relativePath"]
        and resource["sha256"] == source["sha256"]
    ]
    if len(resources) != 1:
        raise RuntimeError(
            f"Capability does not have one exact frozen recipe source: {capability_id}"
        )
    return resources[0]


def planning_capability_resource_ids(
    catalog: dict,
    channel_profile: dict | None = None,
) -> list[str]:
    """List frozen recipe sources available for semantic planning."""

    from app.core.creator_production_menu import planning_capability_ids_for_profile

    planning_ids = set(planning_capability_ids_for_profile(catalog, channel_profile))
    if not planning_ids:
        return list(
            dict.fromkeys(str(resource["id"]) for resource in catalog["sourceResources"])
        )
    resource_ids: list[str] = []
    for capability in catalog["capabilities"]:
        if capability["id"] not in planning_ids:
            continue
        for resource_id in capability.get("requiredResourceIds") or []:
            resource_ids.append(str(resource_id))
        # Native recipes still need their direct source resource.
        relative = (capability.get("source") or {}).get("relativePath")
        digest = (capability.get("source") or {}).get("sha256")
        for resource in catalog["sourceResources"]:
            if resource.get("relativePath") == relative and resource.get("sha256") == digest:
                resource_ids.append(str(resource["id"]))
    return list(dict.fromkeys(resource_ids))


def _transition_sources(skill_root: Path, cli_path: Path) -> tuple[list[dict], list[dict], dict]:
    transition_root = skill_root / "transitions"
    catalog_path = transition_root / "catalog.md"
    overview_path = transition_root / "overview.md"
    registry_path = transition_root / "TRANSITION-REGISTRY.md"
    catalog_text = _read_text(catalog_path)
    overview_text = _read_text(overview_path)
    registry_text = _read_text(registry_path)
    cli_text = _read_text(cli_path)
    resources = []
    for path in sorted(transition_root.glob("*.md")):
        resources.append(
            {
                "id": f"hf-transition-source:{path.stem.lower()}",
                "relativePath": f"transitions/{path.name}",
                "sha256": sha256_file(path),
            }
        )

    normalized_catalog = catalog_text.lower()
    normalized_overview = overview_text.lower()

    def catalog_mentions(identifier: str) -> bool:
        alternatives = {
            identifier.lower(),
            identifier.lower().replace("-", " "),
            identifier.lower().replace("/", " "),
        }
        return any(value in normalized_catalog for value in alternatives)

    entries = []
    for transition_id in CSS_TRANSITIONS:
        if not catalog_mentions(transition_id):
            raise ValueError(f"Documented CSS transition is absent from the pinned catalog: {transition_id}")
        entries.append(
            _source_entry(
                f"hf-css:{transition_id}",
                category="native-source-recipe",
                scope="atomic-operation",
                relative_path="transitions/catalog.md",
                source_hash=sha256_file(catalog_path),
                section_anchor="css-transitions",
            )
        )
    for transition_id, reason in BLOCKED_CSS_CONCEPTS.items():
        if not catalog_mentions(transition_id):
            raise ValueError(f"Blocked CSS concept is absent from the pinned catalog: {transition_id}")
        entries.append(
            _source_entry(
                f"hf-css:{transition_id}",
                category="native-source-recipe",
                scope="atomic-operation",
                relative_path="transitions/catalog.md",
                source_hash=sha256_file(catalog_path),
                section_anchor="hard-rules-css",
                availability="globally-blocked",
                reason=reason,
            )
        )

    registry_payload_match = re.search(
        r"```json\s*(\{.*?\})\s*```", registry_text, flags=re.DOTALL | re.IGNORECASE
    )
    if not registry_payload_match:
        raise ValueError("The pinned workflow transition registry has no machine-readable JSON.")
    registry_payload = json.loads(registry_payload_match.group(1))
    template_names = tuple(item["name"] for item in registry_payload.get("transitions", []))
    if template_names != PLV_TRANSITION_TEMPLATES:
        raise ValueError(f"PLV transition template inventory changed: {template_names}")
    for template in registry_payload["transitions"]:
        entries.append(
            _source_entry(
                f"hf-plv-template:{template['name']}",
                category="workflow-specific-transition-source",
                scope="blueprint-macro",
                relative_path="transitions/TRANSITION-REGISTRY.md",
                source_hash=sha256_file(registry_path),
                section_anchor=f"/transitions/{template_names.index(template['name'])}",
            )
        )

    runtime_keys = tuple(sorted(set(re.findall(r'TRANSITIONS\["([a-z0-9-]+)"\]\s*=', cli_text))))
    if not runtime_keys:
        raise ValueError("No executable shader transition keys were found in the pinned HyperFrames CLI.")
    for route in DOCUMENTED_SHADER_ROUTES:
        if route.replace("shader-", "", 1).replace("-", " ") not in normalized_overview.replace("-", " "):
            raise ValueError(f"Documented shader route is absent from the pinned overview: {route}")
        runtime_key = SHADER_ALIASES.get(route, route)
        entry = _source_entry(
            f"hf-shader-doc:{route}",
            category="native-source-recipe",
            scope="atomic-operation",
            relative_path="transitions/overview.md",
            source_hash=sha256_file(overview_path),
            section_anchor="shader-transitions",
        )
        entry["runtimeMapping"] = {
            "runtimeCapabilityId": f"hf-shader-runtime:{runtime_key}",
            "runtimeKey": runtime_key,
            "mappingKind": "documented-alias" if route in SHADER_ALIASES else "exact-name",
            "verifiedPresent": runtime_key in runtime_keys,
        }
        entry["aliases"] = [runtime_key] if route != runtime_key else []
        entries.append(entry)

    cli_hash = sha256_file(cli_path)
    for runtime_key in runtime_keys:
        entry = _source_entry(
            f"hf-shader-runtime:{runtime_key}",
            category="installed-runtime-primitive",
            scope="atomic-operation",
            relative_path="hyperframes/dist/cli.js",
            source_hash=cli_hash,
            section_anchor=f'TRANSITIONS["{runtime_key}"]',
        )
        entry["adaptationEligibility"] = "not-adaptable"
        entry["implementationMaturity"] = "native-runtime-probed"
        entry["requirements"] = ["pinned-hyperframes-cli", "shader-capture-runtime"]
        entry["runtimeKey"] = runtime_key
        entry["executableProbe"] = {
            "status": "source-registered-unprobed",
            "registryKeyPresent": True,
        }
        entries.append(entry)

    transition_facts = {
        "cssDocumentedCount": len(CSS_TRANSITIONS),
        "cssGloballyBlockedCount": len(BLOCKED_CSS_CONCEPTS),
        "plvTemplateCount": len(template_names),
        "shaderDocumentedCount": len(DOCUMENTED_SHADER_ROUTES),
        "shaderRuntimeCount": len(runtime_keys),
        "shaderRuntimeKeys": list(runtime_keys),
        "unknownShaderFallbackDetected": bool(
            re.search(r"TRANSITIONS\[shaderName\]\s*\?\?\s*crossfade", cli_text)
        ),
    }
    return entries, resources, transition_facts


def inventory_hyperframes_capabilities(
    *,
    skill_root: Path,
    hyperframes_cli_path: Path,
    hyperframes_version: str,
    skill_package_version: str | None = None,
) -> dict:
    """Inventory pinned native source without granting it Production authority."""

    from app.core.creator_production_menu import scrub_retired_catalog_rows

    skill_root = skill_root.expanduser().resolve()
    cli_path = hyperframes_cli_path.expanduser().resolve()
    if not skill_root.is_dir():
        raise ValueError(f"HyperFrames animation skill root does not exist: {skill_root}")
    rules, rule_resources = _indexed_rules(skill_root)
    blueprints, blueprint_resources = _indexed_blueprints(skill_root)
    transitions, transition_resources, transition_facts = _transition_sources(skill_root, cli_path)
    support_resources = _support_resources(skill_root)
    entries = sorted([*rules, *blueprints, *transitions], key=lambda item: item["id"])
    resources = sorted(
        [*rule_resources, *blueprint_resources, *transition_resources],
        key=lambda item: item["id"],
    )
    _attach_required_resources(
        skill_root=skill_root,
        entries=entries,
        source_resources=resources,
        support_resources=support_resources,
    )
    if len({entry["id"] for entry in entries}) != len(entries):
        raise ValueError("Namespaced capability IDs are not unique.")
    all_resource_ids = [
        resource["id"] for resource in [*resources, *support_resources]
    ]
    if len(set(all_resource_ids)) != len(all_resource_ids):
        raise ValueError("Namespaced capability resource IDs are not unique.")
    catalog = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "id": "hyperframes-native-capabilities",
        "version": 1,
        "owner": "creator-video-production",
        "sourceIdentity": {
            "hyperframesVersion": hyperframes_version,
            "hyperframesCliSha256": sha256_file(cli_path),
            "skillPackageVersion": skill_package_version,
            "skillSha256": sha256_file(skill_root / "SKILL.md"),
            "rulesIndexSha256": sha256_file(skill_root / "rules-index.md"),
            "rulesTreeSha256": _tree_hash(skill_root / "rules"),
            "blueprintsIndexSha256": sha256_file(skill_root / "blueprints-index.md"),
            "blueprintsTreeSha256": _tree_hash(skill_root / "blueprints"),
            "transitionsTreeSha256": _tree_hash(skill_root / "transitions"),
        },
        "inventorySummary": {
            "ruleSourceCount": len(rules),
            "blueprintSourceCount": len(blueprints),
            **transition_facts,
            "supportResourceCount": len(support_resources),
            "totalCapabilityCount": len(entries),
            "sourceEnabledCount": sum(
                item["sourceAvailability"] == "source-enabled" for item in entries
            ),
            "productionSelectable": sum(
                item["productionSelection"] == "production-selectable" for item in entries
            ),
            "adaptationDebtCount": sum(
                item["sourceAvailability"] == "source-enabled"
                and item["productionSelection"] != "production-selectable"
                for item in entries
            ),
        },
        "capabilities": entries,
        "sourceResources": resources,
        "supportResources": support_resources,
        "selectionPolicy": {
            "nativeWorkflowRoutingEnabled": False,
            "automaticRecipeSelectionEnabled": False,
            "sourceOnlySelectable": False,
            "unknownCapabilityFallbackEnabled": False,
            "unknownTransitionFallbackEnabled": False,
        },
    }
    scrub_retired_catalog_rows(catalog)
    catalog["catalogHash"] = canonical_hash(
        {key: value for key, value in catalog.items() if key != "catalogHash"}
    )
    validate_artifact("capability-catalog", catalog)
    return catalog


def assert_capability_selectable(catalog: dict, capability_id: str) -> dict:
    validate_artifact("capability-catalog", catalog)
    entries = [entry for entry in catalog["capabilities"] if entry["id"] == capability_id]
    if not entries:
        raise ValueError(f"Unknown capability: {capability_id}")
    entry = entries[0]
    if entry["sourceAvailability"] != "source-enabled":
        raise RuntimeError(f"Capability source is unavailable: {capability_id}")
    if entry["productionSelection"] != "production-selectable":
        raise RuntimeError(f"Capability is not production-selectable: {capability_id}")
    if entry["technicalAdmission"] not in {"project-admitted", "library-admitted"}:
        raise RuntimeError(f"Capability is not technically admitted: {capability_id}")
    if entry["implementationMaturity"] not in {
        "native-runtime-probed",
        "compiled",
        "technically-proven",
        "delivery-proven",
    }:
        raise RuntimeError(f"Capability has no executable implementation: {capability_id}")
    return entry
