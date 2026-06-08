"""Pydantic schemas for RunningHub routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RunningHubField(BaseModel):
    id: str = ""
    label: str = ""
    nodeId: str = ""
    nodeTitle: str = ""
    classType: str = ""
    fieldName: str = ""
    type: str = "text"
    default: Any = ""
    required: bool = False
    accept: str = ""
    options: List[str] = []


class RunningHubWorkflowPayload(BaseModel):
    id: str = ""
    title: str = "RunningHub Workflow"
    workflowId: str = ""
    accessPassword: str = ""
    defaultRetainSeconds: int = 0
    fields: List[RunningHubField] = []
    options: Dict[str, Any] = {}


class RunningHubTaskRequest(BaseModel):
    provider_id: str = "runninghub"
    workflow_id: str = ""
    workflowId: str = ""
    workflow_local_id: str = ""
    access_password: str = ""
    accessPassword: str = ""
    node_info_list: List[Dict[str, Any]] = []
    nodeInfoList: List[Dict[str, Any]] = []
    fields: List[RunningHubField] = []
    values: Dict[str, Any] = {}
    addMetadata: Optional[bool] = None
    randomSeed: Optional[bool] = None
    webhookUrl: str = ""
    instanceType: str = ""
    usePersonalQueue: Optional[bool] = None
    retainSeconds: Optional[int] = None
    options: Dict[str, Any] = {}


class RunningHubWorkflowConvertRequest(BaseModel):
    provider_id: str = "runninghub"
    workflow_id: str = ""
    workflowId: str = ""
    workflow: Any = None
    api_workflow: Any = None
    profile: str = "auto"
    output_mode: str = "external"
    main_output_id: str = "312"

