#!/usr/bin/env python3
"""Friendly exporter for repaired ComfyUI API workflows.

This wraps comfy_api_workflow_converter.py with defaults that are safer for
complex workflows using Set/Get nodes, bypassed branches, and runtime switches.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import comfy_api_workflow_converter as converter


OCT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW_DIR = OCT_ROOT / "workflows" / "comfyui_full"
DEFAULT_MAIN_OUTPUT_ID = "312"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def workflow_title(path: Path) -> str:
    return path.stem


def default_desktop() -> Path:
    return OCT_ROOT / "data" / "comfyui_exports"


def parse_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    text = raw.strip().strip('"')
    if not text:
        return None
    return Path(text).expanduser()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def find_workflows(workflow_dir: Path) -> list[Path]:
    if not workflow_dir.exists():
        return []
    candidates = []
    for path in workflow_dir.glob("*.json"):
        try:
            data = read_json(path)
        except Exception:
            continue
        if "nodes" in data and isinstance(data["nodes"], list):
            candidates.append(path)
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)


def choose_workflow(workflow_dir: Path) -> Path:
    workflows = find_workflows(workflow_dir)
    if not workflows:
        raise SystemExit(f"No ComfyUI workflow JSON files found in {workflow_dir}")

    print("\nSaved ComfyUI workflows:")
    for index, path in enumerate(workflows[:30], 1):
        print(f"  {index:2d}. {path.name}")

    while True:
        answer = input("\nChoose workflow number, or paste a workflow path: ").strip()
        if not answer:
            continue
        if answer.isdigit():
            selected = int(answer)
            if 1 <= selected <= min(len(workflows), 30):
                return workflows[selected - 1]
            print("Number out of range.")
            continue
        path = parse_path(answer)
        if path:
            path = resolve_path(path)
            if path.exists():
                return path
        print("Could not find that workflow path.")


def choose_api_input() -> Path | None:
    answer = input(
        "\nOptional: paste the native Export(API) JSON path to preserve current values,\n"
        "or press Enter to skip: "
    )
    path = parse_path(answer)
    if not path:
        return None
    path = resolve_path(path)
    if not path.exists():
        raise SystemExit(f"API input not found: {path}")
    return path


def validate_workflow(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if "nodes" not in data or not isinstance(data["nodes"], list):
        raise SystemExit(f"Input is not a full ComfyUI workflow with nodes: {path}")
    return data


def validate_api_prompt(path: Path) -> None:
    data = read_json(path)
    if "nodes" in data:
        raise SystemExit(f"API input should be an Export(API) prompt, not a full workflow: {path}")
    bad_nodes = [
        node_id
        for node_id, node in data.items()
        if not isinstance(node, dict) or "class_type" not in node or "inputs" not in node
    ]
    if bad_nodes:
        sample = ", ".join(map(str, bad_nodes[:5]))
        raise SystemExit(f"API input does not look like a ComfyUI API prompt. Bad node ids: {sample}")


def detect_profile(workflow_data: dict[str, Any], requested: str) -> str:
    if requested != "auto":
        return requested
    node_types = {node.get("type") for node in workflow_data.get("nodes", []) if isinstance(node, dict)}
    if {
        "WanVideoAnimateEmbeds",
        "WanVideoSamplerSettings",
        "BodyRatioMapperProportionTransfer",
    }.issubset(node_types):
        return "motiontransfer"
    return "generic"


def make_outputs(output_dir: Path, base_name: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "api": output_dir / f"{base_name}.json",
        "workflow": output_dir / f"{base_name}.workflow.json",
        "mapping": output_dir / f"{base_name}.mapping.json",
    }


def summarize(mapping: dict[str, Any], outputs: dict[str, Path]) -> None:
    validation = mapping.get("validation", {})
    switches = mapping.get("runtime_switches", {})
    overlay = mapping.get("api_value_overlay", {})
    converted = mapping.get("flatten_set_get", {}).get("converted", [])
    frontend_switches = mapping.get("frontend_switches", {}).get("converted", [])
    compatible_nodes = mapping.get("compatible_custom_nodes", {}).get("converted", [])
    reroutes = mapping.get("strip_reroute_nodes", {})

    print("\nDone. Exported repaired API workflow:")
    print(f"  API prompt:       {outputs['api']}")
    print(f"  Check workflow:   {outputs['workflow']}")
    print(f"  Report:           {outputs['mapping']}")
    print("\nSummary:")
    print(f"  Nodes:            {validation.get('nodes')}")
    print(f"  Links:            {validation.get('links')}")
    print(f"  Bad links:        {validation.get('bad_links')}")
    print(f"  Reroutes removed: {reroutes.get('removed', 0)}")
    if compatible_nodes:
        print(f"  Compat nodes:     {len(compatible_nodes)} replaced")
    print(f"  Set/Get flattened:{len(converted)}")
    if frontend_switches:
        print(f"  Frontend switches:{len(frontend_switches)} converted")
    if switches:
        print(f"  Runtime switches: {', '.join(switches)}")
    if overlay.get("updated"):
        changed = sum(len(item.get("inputs", [])) for item in overlay["updated"])
        print(f"  Preserved values: {changed}")
    if overlay.get("skipped"):
        print(f"  Skipped values:   {len(overlay['skipped'])} (see mapping report)")


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, help="Full ComfyUI workflow JSON, not Export(API).")
    parser.add_argument("--api-input", type=Path, help="Optional native Export(API) JSON whose scalar values should be preserved.")
    parser.add_argument("--output-dir", type=Path, default=default_desktop(), help="Directory for generated files.")
    parser.add_argument("--name", help="Output base name. Defaults to '<workflow-name>_api_fixed'.")
    parser.add_argument("--profile", choices=["auto", "motiontransfer", "generic"], default="auto")
    parser.add_argument("--output-mode", choices=["all", "main"], default="all", help="Use 'all' for complex workflows.")
    parser.add_argument("--main-output-id", default=DEFAULT_MAIN_OUTPUT_ID)
    parser.add_argument("--no-api-input", action="store_true", help="Do not ask for an optional Export(API) file in interactive mode.")
    return parser.parse_args()


def main() -> None:
    args = build_args()
    workflow_path = resolve_path(args.workflow) if args.workflow else choose_workflow(DEFAULT_WORKFLOW_DIR)
    workflow_data = validate_workflow(workflow_path)

    api_input = None
    if args.api_input:
        api_input = resolve_path(args.api_input)
    elif not args.workflow and not args.no_api_input:
        api_input = choose_api_input()
    if api_input:
        validate_api_prompt(api_input)

    profile = detect_profile(workflow_data, args.profile)
    base_name = args.name or f"{workflow_title(workflow_path)}_api_fixed"
    outputs = make_outputs(resolve_path(args.output_dir), base_name)

    convert_args = SimpleNamespace(
        input=workflow_path,
        api_input=api_input,
        workflow_output=outputs["workflow"],
        api_output=outputs["api"],
        mapping_output=outputs["mapping"],
        main_output_id=args.main_output_id,
        output_mode=args.output_mode,
        profile=profile,
    )
    mapping = converter.convert(convert_args)
    summarize(mapping, outputs)


if __name__ == "__main__":
    main()
