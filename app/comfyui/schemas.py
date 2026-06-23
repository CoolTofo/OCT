from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class WorkflowField(BaseModel):
    id: str
    node: str = ""
    input: str = ""
    name: str = ""
    nodeTitle: str = ""
    classType: str = ""
    type: str = "text"
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    options: List[str] = []
    random_enabled: bool = False
    locked: bool = False


class WorkflowConfig(BaseModel):
    title: str = ""
    fields: List[WorkflowField] = []
    mini_cards: Dict[str, Any] = {}


class WorkflowUploadRequest(BaseModel):
    name: str
    workflow: Dict[str, Any]


class WorkflowRunRequest(BaseModel):
    fields: Dict[str, Any] = {}
    config: WorkflowConfig
    client_id: str = ""


class ComfyInstancesPayload(BaseModel):
    instances: List[str] = []


class ComfyWorkflowExportRequest(BaseModel):
    workflow_path: str = ""
    workflow: Optional[Dict[str, Any]] = None
    api_input: Optional[Dict[str, Any]] = None
    name: str = ""
    profile: str = "auto"
    output_mode: str = "main"
    main_output_id: str = "auto"
    save_config: bool = True
