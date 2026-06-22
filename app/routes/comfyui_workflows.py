import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from app.comfyui import api_prompt as comfy_api_prompt
from app.comfyui import workflows as comfy_workflows
from app.comfyui.schemas import (
    ComfyWorkflowExportRequest,
    WorkflowConfig,
    WorkflowRunRequest,
    WorkflowUploadRequest,
)
from app.paths import WORKFLOW_DIR
from app.schemas import GenerateRequest


def create_router(generate_callable) -> APIRouter:
    router = APIRouter()

    @router.get("/api/comfyui/export/workflows")
    def list_comfy_export_workflows():
        workflow_dir = comfy_workflows.comfy_export_workflow_dir()
        tool_ready = os.path.exists(os.path.join(comfy_workflows.COMFY_EXPORT_TOOL_DIR, "comfy_api_workflow_converter.py"))
        if not os.path.isdir(workflow_dir):
            return {
                "tool_dir": comfy_workflows.COMFY_EXPORT_TOOL_DIR,
                "workflow_dir": workflow_dir,
                "tool_ready": tool_ready,
                "workflows": [],
            }
        items = []
        for fn in os.listdir(workflow_dir):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(workflow_dir, fn)
            if not os.path.isfile(path):
                continue
            try:
                data = comfy_workflows.read_json_file(path)
            except Exception:
                continue
            if not comfy_workflows.is_full_comfy_workflow(data):
                continue
            stat = os.stat(path)
            items.append({
                "name": fn,
                "path": path,
                "title": os.path.splitext(fn)[0],
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "nodes": len(data.get("nodes") or []),
                "links": len(data.get("links") or []),
            })
        items.sort(key=lambda item: item["mtime"], reverse=True)
        return {
            "tool_dir": comfy_workflows.COMFY_EXPORT_TOOL_DIR,
            "workflow_dir": workflow_dir,
            "tool_ready": tool_ready,
            "workflows": items,
        }

    @router.post("/api/comfyui/export/convert")
    def convert_comfy_export_workflow(payload: ComfyWorkflowExportRequest):
        converter = comfy_workflows.load_comfy_export_converter()
        os.makedirs(comfy_workflows.COMFY_EXPORT_REPORT_DIR, exist_ok=True)
        custom_dir = os.path.join(WORKFLOW_DIR, comfy_workflows.CUSTOM_WORKFLOW_FOLDER)
        os.makedirs(custom_dir, exist_ok=True)

        temp_paths: List[str] = []
        try:
            if payload.workflow:
                if not comfy_workflows.is_full_comfy_workflow(payload.workflow):
                    raise HTTPException(status_code=400, detail="workflow must be a full ComfyUI workflow JSON with nodes")
                source_title = payload.name or "ComfyUI_api_fixed"
                source_path = os.path.join(comfy_workflows.COMFY_EXPORT_REPORT_DIR, f"_input_{uuid.uuid4().hex}.workflow.json")
                comfy_workflows.write_json_file(source_path, payload.workflow)
                temp_paths.append(source_path)
                workflow_data = payload.workflow
            else:
                source_path = comfy_workflows.safe_comfy_export_path(payload.workflow_path)
                workflow_data = comfy_workflows.read_json_file(source_path)
                if not comfy_workflows.is_full_comfy_workflow(workflow_data):
                    raise HTTPException(status_code=400, detail="Selected file is not a full ComfyUI workflow JSON")
                source_title = os.path.splitext(os.path.basename(source_path))[0]

            profile = comfy_workflows.detect_comfy_export_profile(workflow_data, payload.profile)
            output_mode = (payload.output_mode or "all").lower()
            if output_mode not in {"all", "main"}:
                raise HTTPException(status_code=400, detail="output_mode must be all or main")

            out_filename = comfy_workflows.safe_custom_workflow_filename(payload.name, f"{source_title}_api_fixed")
            stored_name = f"{comfy_workflows.CUSTOM_WORKFLOW_FOLDER}/{out_filename}"
            api_output = comfy_workflows.workflow_path_from_name(stored_name)
            report_base = os.path.splitext(out_filename)[0]
            workflow_output = os.path.join(comfy_workflows.COMFY_EXPORT_REPORT_DIR, f"{report_base}.workflow.json")
            mapping_output = os.path.join(comfy_workflows.COMFY_EXPORT_REPORT_DIR, f"{report_base}.mapping.json")

            api_input_path = None
            if payload.api_input is not None:
                if not comfy_workflows.is_api_prompt_workflow(payload.api_input):
                    raise HTTPException(status_code=400, detail="api_input must be a native ComfyUI Export(API) JSON")
                api_input_path = os.path.join(comfy_workflows.COMFY_EXPORT_REPORT_DIR, f"_api_input_{uuid.uuid4().hex}.json")
                comfy_workflows.write_json_file(api_input_path, payload.api_input)
                temp_paths.append(api_input_path)

            args = SimpleNamespace(
                input=Path(source_path),
                api_input=Path(api_input_path) if api_input_path else None,
                workflow_output=Path(workflow_output),
                api_output=Path(api_output),
                mapping_output=Path(mapping_output),
                main_output_id=str(payload.main_output_id or "312"),
                output_mode=output_mode,
                profile=profile,
            )
            mapping = converter.convert(args)
            api_prompt = comfy_workflows.read_json_file(api_output)
            body_ratio_fixes = comfy_api_prompt.repair_body_ratio_mapper_api_values(api_prompt)
            flux_resolution_fixes = comfy_api_prompt.repair_flux_latent_resolution_steps(api_prompt)
            if body_ratio_fixes or flux_resolution_fixes:
                comfy_workflows.write_json_file(api_output, api_prompt)
                post_convert_repair = mapping.setdefault("post_convert_api_repair", {})
                if body_ratio_fixes:
                    post_convert_repair["body_ratio_mapper"] = body_ratio_fixes
                if flux_resolution_fixes:
                    post_convert_repair["flux_latent_resolution_steps"] = flux_resolution_fixes
                comfy_workflows.write_json_file(mapping_output, mapping)
            body_ratio_issues = comfy_api_prompt.validate_body_ratio_mapper_api_values(api_prompt)
            if body_ratio_issues:
                raise HTTPException(status_code=400, detail=f"BodyRatioMapper API values are invalid after conversion: {body_ratio_issues}")
            fields = comfy_workflows.lock_essential_comfy_fields(comfy_workflows.extract_api_prompt_fields(api_prompt))
            config = {
                "title": os.path.splitext(out_filename)[0],
                "fields": fields,
                "mini_cards": {},
            }
            config, _ = comfy_workflows.repair_comfy_workflow_config(api_prompt, config)
            if payload.save_config:
                comfy_workflows.write_json_file(comfy_workflows.workflow_config_path(stored_name), config)
            return {
                "ok": True,
                "workflow": {
                    "name": stored_name,
                    "title": config["title"],
                    "field_count": len(fields),
                },
                "profile": profile,
                "output_mode": output_mode,
                "api_output": api_output,
                "workflow_output": workflow_output,
                "mapping_output": mapping_output,
                "mapping": mapping,
                "config": config,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            for path in temp_paths:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

    @router.get("/api/workflows")
    def list_workflows():
        if not os.path.isdir(WORKFLOW_DIR):
            return {"workflows": []}
        items = []
        for root, dirs, files in os.walk(WORKFLOW_DIR):
            if os.path.abspath(root) == os.path.abspath(WORKFLOW_DIR):
                dirs[:] = [
                    d
                    for d in dirs
                    if d in {comfy_workflows.CUSTOM_WORKFLOW_FOLDER, comfy_workflows.LEGACY_CUSTOM_WORKFLOW_FOLDER}
                ]
            for fn in sorted(files):
                if not fn.endswith(".json") or fn.endswith(".config.json"):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), WORKFLOW_DIR).replace("\\", "/")
                if not comfy_workflows.WORKFLOW_NAME_RE.match(rel):
                    continue
                if comfy_workflows.is_builtin_workflow(rel):
                    continue
                cfg = {}
                cfg_path = comfy_workflows.workflow_config_path(rel)
                if os.path.exists(cfg_path):
                    try:
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            cfg = json.load(f) or {}
                    except Exception:
                        cfg = {}
                items.append({
                    "name": rel,
                    "title": cfg.get("title") or fn.replace(".json", ""),
                    "builtin": False,
                    "field_count": len(cfg.get("fields") or []),
                })
        items.sort(key=lambda item: (0 if item["name"].startswith(f"{comfy_workflows.CUSTOM_WORKFLOW_FOLDER}/") else 1, item["title"]))
        return {"workflows": items}

    @router.get("/api/workflows/{name:path}")
    def get_workflow(name: str):
        if not comfy_workflows.WORKFLOW_NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="Invalid workflow name")
        workflow_path = comfy_workflows.workflow_path_from_name(name)
        if not os.path.exists(workflow_path):
            raise HTTPException(status_code=404, detail="Workflow not found")
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
        cfg = {"title": name.replace(".json", ""), "fields": []}
        cfg_path = comfy_workflows.workflow_config_path(name)
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or cfg
            except Exception:
                pass
        if not comfy_workflows.is_builtin_workflow(name):
            cfg, changed = comfy_workflows.repair_comfy_workflow_config(workflow, cfg)
            if changed and os.path.exists(workflow_path):
                try:
                    comfy_workflows.write_json_file(cfg_path, cfg)
                except Exception:
                    pass
        return {"name": name, "workflow": workflow, "config": cfg, "builtin": comfy_workflows.is_builtin_workflow(name)}

    @router.post("/api/workflows")
    def upload_workflow(payload: WorkflowUploadRequest):
        name = os.path.basename(payload.name.strip())
        if not name.endswith(".json"):
            name = name + ".json"
        if not comfy_workflows.WORKFLOW_NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="Invalid workflow name. Use letters, numbers, Chinese characters, underscore, hyphen, or dot.")
        if not isinstance(payload.workflow, dict) or not payload.workflow:
            raise HTTPException(status_code=400, detail="Workflow JSON is empty.")
        sample = next(iter(payload.workflow.values()), None)
        if not isinstance(sample, dict) or "class_type" not in sample:
            raise HTTPException(status_code=400, detail="Invalid ComfyUI API workflow JSON: nodes must include class_type.")
        custom_dir = os.path.join(WORKFLOW_DIR, comfy_workflows.CUSTOM_WORKFLOW_FOLDER)
        os.makedirs(custom_dir, exist_ok=True)
        stored_name = f"{comfy_workflows.CUSTOM_WORKFLOW_FOLDER}/{name}"
        path = comfy_workflows.workflow_path_from_name(stored_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload.workflow, f, ensure_ascii=False, indent=2)
        return {"name": stored_name}

    @router.put("/api/workflows/{name:path}/config")
    def save_workflow_config(name: str, payload: WorkflowConfig):
        if not comfy_workflows.WORKFLOW_NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="Invalid workflow name")
        workflow_path = comfy_workflows.workflow_path_from_name(name)
        if not os.path.exists(workflow_path):
            raise HTTPException(status_code=404, detail="Workflow not found")
        cfg_path = comfy_workflows.workflow_config_path(name)
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
        config = payload.dict()
        if not comfy_workflows.is_builtin_workflow(name):
            config, _ = comfy_workflows.repair_comfy_workflow_config(workflow, config)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return {"config": config}

    @router.delete("/api/workflows/{name:path}")
    def delete_workflow(name: str):
        if not comfy_workflows.WORKFLOW_NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="Invalid workflow name")
        if comfy_workflows.is_builtin_workflow(name):
            raise HTTPException(status_code=400, detail="Built-in workflows cannot be deleted.")
        workflow_path = comfy_workflows.workflow_path_from_name(name)
        cfg_path = comfy_workflows.workflow_config_path(name)
        if not os.path.exists(workflow_path):
            raise HTTPException(status_code=404, detail="Workflow not found")
        os.remove(workflow_path)
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
        return {"ok": True}

    @router.post("/api/workflows/{name:path}/run")
    def run_workflow(name: str, payload: WorkflowRunRequest):
        if not comfy_workflows.WORKFLOW_NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="Invalid workflow name")
        if not os.path.exists(comfy_workflows.workflow_path_from_name(name)):
            raise HTTPException(status_code=404, detail="Workflow not found")
        params: Dict[str, Dict[str, Any]] = {}
        for field in payload.config.fields:
            if not field.node or not field.input:
                continue
            if field.id in payload.fields:
                value = payload.fields[field.id]
                field_type = str(field.type or "").lower()
                if field_type in {"text", "textarea", "string"} and value in (None, "") and field.default not in (None, ""):
                    value = field.default
                elif field.type in ("number", "slider"):
                    try:
                        value = float(value) if (field.step and field.step < 1) else int(float(value))
                    except Exception:
                        pass
                elif field.type == "boolean":
                    value = bool(value)
                elif field.type == "dropdown":
                    if isinstance(value, str):
                        s = value.strip()
                        try:
                            if s and ("." in s or "e" in s.lower()):
                                value = float(s)
                            elif s and s.lstrip("-").isdigit():
                                value = int(s)
                        except (ValueError, TypeError):
                            pass
                params.setdefault(field.node, {})[field.input] = value
        req = GenerateRequest(
            prompt="",
            workflow_json=name,
            params=params,
            type="workflow-test",
            client_id=payload.client_id or str(uuid.uuid4()),
        )
        return generate_callable(req)

    return router
