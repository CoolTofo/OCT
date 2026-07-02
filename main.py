import uuid
import os
import sys
import asyncio
from typing import List
from threading import Lock
from fastapi import FastAPI

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from app import bootstrap
from app.logging_config import configure_access_logging
from app import providers as provider_utils
from app import provider_responses
from app import media_processing
from app import image_generation
from app import online_image_service
from app import holo_runtime
from app import provider_runtime
from app import runtime_config
from app import env_config
from app import history_store
from app.task_queue import TaskQueue
from app.paths import (
    API_ENV_FILE,
    API_PROVIDERS_FILE,
    ASSETS_DIR,
    DATA_DIR,
    GLOBAL_CONFIG_FILE,
    HISTORY_FILE,
    OUTPUT_DIR,
    RUNNINGHUB_WORKFLOWS_FILE,
    STATIC_DIR,
    WORKFLOW_DIR,
    WORKFLOW_PATH,
    ensure_runtime_dirs,
)
from app.realtime import ConnectionManager
from app.routes import history as history_routes
from app.routes import queue as queue_routes
from app.routes import system as system_routes
from app.routes import update as update_routes
from app.routes import comfyui_workflows as comfy_workflow_routes
from app.routes import chat as chat_routes
from app.routes import comfyui_instances as comfy_instance_routes
from app.routes import config as config_routes
from app.routes import canvas as canvas_routes
from app.routes import canvas_image_tasks as canvas_image_task_routes
from app.routes import conversations as conversation_routes
from app.routes import creative_tools as creative_tool_routes
from app.routes import dreamina_cli as dreamina_cli_routes
from app.routes import media as media_routes
from app.routes import modelscope_angle as modelscope_angle_routes
from app.routes import modelscope_image as modelscope_image_routes
from app.routes import ai_sites as ai_site_routes
from app.routes import online_image as online_image_routes
from app.routes import prompt_templates as prompt_template_routes
from app.routes import provider_models as provider_model_routes
from app.routes import runninghub as runninghub_routes
from app.routes import local_generate as local_generate_routes
from app.routes import video_generation as video_generation_routes
from app.routes import websocket_stats as websocket_stats_routes
from app.comfyui import workflows as comfy_workflows
from app.comfyui import instances as comfy_instances
from app.comfyui import api_prompt as comfy_api_prompt
from app.comfyui import backends as comfy_backends
from app.comfyui import runtime as comfy_runtime
from app import canvas_store
from app import media_store
from app.validation import friendly_validation_error, modelscope_size, selected_model
from app.runninghub import runtime as rh_runtime

configure_access_logging()

app = FastAPI()
app.include_router(history_routes.router)
app.include_router(system_routes.router)
app.include_router(update_routes.router)

safe_user_id = canvas_store.safe_user_id
user_dir = canvas_store.user_dir
conversation_path = canvas_store.conversation_path
now_ms = canvas_store.now_ms
save_conversation = canvas_store.save_conversation
new_conversation = canvas_store.new_conversation
load_conversation = canvas_store.load_conversation
list_conversations = canvas_store.list_conversations
save_canvas = canvas_store.save_canvas
load_canvas = canvas_store.load_canvas
display_title = canvas_store.display_title

app.include_router(conversation_routes.create_router({
    "safe_user_id": safe_user_id,
    "list_conversations": list_conversations,
    "new_conversation": new_conversation,
    "load_conversation": load_conversation,
    "conversation_path": conversation_path,
}))

is_comfy_link = comfy_api_prompt.is_comfy_link
is_comfy_reroute_node = comfy_api_prompt.is_reroute_node
first_comfy_link_input = comfy_api_prompt.first_link_input
resolve_comfy_reroute_link = comfy_api_prompt.resolve_reroute_link
strip_comfy_reroute_nodes = comfy_api_prompt.strip_reroute_nodes
comfy_node_class = comfy_api_prompt.node_class
normalize_comfy_class_name = comfy_api_prompt.normalize_class_name
coerce_comfy_bool = comfy_api_prompt.coerce_bool
is_comfy_api_helper_node = comfy_api_prompt.is_api_helper_node
resolve_comfy_api_helper_value = comfy_api_prompt.resolve_api_helper_value
fold_comfy_api_helper_nodes = comfy_api_prompt.fold_api_helper_nodes
repair_flux_latent_resolution_steps = comfy_api_prompt.repair_flux_latent_resolution_steps
repair_body_ratio_mapper_api_values = comfy_api_prompt.repair_body_ratio_mapper_api_values
validate_body_ratio_mapper_api_values = comfy_api_prompt.validate_body_ratio_mapper_api_values

output_url_for = media_store.output_url_for
output_path_for = media_store.output_path_for
output_file_from_url = media_store.output_file_from_url
content_type_for_path = media_store.content_type_for_path
upload_path_to_public_storage = media_store.upload_path_to_public_storage

workflow_path_from_name = comfy_workflows.workflow_path_from_name
workflow_config_path = comfy_workflows.workflow_config_path
is_builtin_workflow = comfy_workflows.is_builtin_workflow
motion_transfer_workflow_fields = comfy_workflows.motion_transfer_workflow_fields
comfy_export_workflow_dir = comfy_workflows.comfy_export_workflow_dir
read_json_file = comfy_workflows.read_json_file
write_json_file = comfy_workflows.write_json_file
infer_workflow_field_type = comfy_workflows.infer_workflow_field_type
comfy_field_stable_key = comfy_workflows.comfy_field_stable_key
is_essential_comfy_field = comfy_workflows.is_essential_comfy_field

bootstrap.setup_cors(app)
bootstrap.setup_no_cache_for_ui_assets(app)
bootstrap.setup_validation_error_handler(app, friendly_validation_error)

# --- WebSocket State Manager ---
manager = ConnectionManager()
app.include_router(canvas_routes.create_router(manager))
GLOBAL_LOOP = None

def set_global_loop(loop):
    global GLOBAL_LOOP
    GLOBAL_LOOP = loop

app.include_router(websocket_stats_routes.create_router({
    "manager": manager,
    "set_global_loop": set_global_loop,
    "get_running_loop": asyncio.get_running_loop,
}))

# --- Configuration ---

CLIENT_ID = str(uuid.uuid4())
LOCAL_TASK_QUEUE = TaskQueue()
app.include_router(queue_routes.create_router(LOCAL_TASK_QUEUE))
GLOBAL_CONFIG_LOCK = Lock()
LOAD_LOCK = Lock()

SUPPORTED_PROVIDER_PROTOCOLS = provider_utils.SUPPORTED_PROVIDER_PROTOCOLS

env_config.ensure_runtime_config_files(API_ENV_FILE, DATA_DIR)
env_config.load_env_file(API_ENV_FILE)

COMFYUI_INSTANCES = [s.strip() for s in os.getenv("COMFYUI_INSTANCES", "127.0.0.1:8188").split(",") if s.strip()]
COMFYUI_ADDRESS = COMFYUI_INSTANCES[0]

globals().update(runtime_config.load_settings())

def reload_env_globals():
    """Refresh module globals from environment after API settings change."""
    globals().update(runtime_config.load_settings())
    if "configure_provider_runtime" in globals():
        configure_provider_runtime()
    if "configure_image_generation" in globals():
        configure_image_generation()

def configure_provider_runtime():
    provider_runtime.configure({
        "MODELSCOPE_CHAT_BASE_URL": MODELSCOPE_CHAT_BASE_URL,
        "MODELSCOPE_IMAGE_MODELS": MODELSCOPE_IMAGE_MODELS,
        "MODELSCOPE_CHAT_MODELS": MODELSCOPE_CHAT_MODELS,
        "MODELSCOPE_VIDEO_MODELS": MODELSCOPE_VIDEO_MODELS,
        "MODELSCOPE_DEFAULT_IMAGE_MODELS": MODELSCOPE_DEFAULT_IMAGE_MODELS,
        "MODELSCOPE_DEFAULT_CHAT_MODELS": MODELSCOPE_DEFAULT_CHAT_MODELS,
        "MODELSCOPE_DEFAULT_LORAS": MODELSCOPE_DEFAULT_LORAS,
        "MODELSCOPE_DEFAULTS_VERSION": MODELSCOPE_DEFAULTS_VERSION,
        "HOLO_DEFAULT_IMAGE_MODELS": HOLO_DEFAULT_IMAGE_MODELS,
        "HOLO_DEFAULT_VIDEO_MODELS": HOLO_DEFAULT_VIDEO_MODELS,
        "SEEDANCE_DEFAULT_BASE_URL": SEEDANCE_DEFAULT_BASE_URL,
        "SEEDANCE_DEFAULT_VIDEO_MODELS": SEEDANCE_DEFAULT_VIDEO_MODELS,
        "VOLC_VISUAL_DEFAULT_BASE_URL": VOLC_VISUAL_DEFAULT_BASE_URL,
        "VOLC_VISUAL_MOTION_MODEL": VOLC_VISUAL_MOTION_MODEL,
        "RUNNINGHUB_DEFAULT_BASE_URL": RUNNINGHUB_DEFAULT_BASE_URL,
        "AI_BASE_URL": AI_BASE_URL,
        "AI_API_KEY": AI_API_KEY,
        "CHAT_MODEL": CHAT_MODEL,
        "MODELSCOPE_API_KEY": MODELSCOPE_API_KEY,
        "API_PROVIDERS_FILE": API_PROVIDERS_FILE,
        "API_ENV_FILE": API_ENV_FILE,
        "DATA_DIR": DATA_DIR,
        "GLOBAL_CONFIG_LOCK": GLOBAL_CONFIG_LOCK,
        "selected_model": selected_model,
        "provider_key_env": provider_utils.provider_key_env,
    })

configure_provider_runtime()
provider_runtime_context = provider_runtime.provider_runtime_context
model_list_from_values = provider_runtime.model_list_from_values
provider_endpoint_url = provider_runtime.provider_endpoint_url
normalize_provider = provider_runtime.normalize_provider
load_api_providers = provider_runtime.load_api_providers
save_api_providers = provider_runtime.save_api_providers
public_provider = provider_runtime.public_provider
get_primary_provider_id = provider_runtime.get_primary_provider_id
get_api_provider = provider_runtime.get_api_provider
get_api_provider_exact = provider_runtime.get_api_provider_exact
update_env_values = provider_runtime.update_env_values

BACKEND_LOCAL_LOAD = {addr: 0 for addr in COMFYUI_INSTANCES}

def discover_local_comfyui_instances() -> List[str]:
    return comfy_instances.discover_local_instances(COMFYUI_INSTANCES)

def get_active_comfyui_instances() -> List[str]:
    return comfy_instances.active_instances(COMFYUI_INSTANCES, BACKEND_LOCAL_LOAD, LOAD_LOCK)


def save_comfyui_instance_config(instances: List[str]) -> List[str]:
    cleaned = comfy_instances.validate_instances(instances)
    update_env_values({"COMFYUI_INSTANCES": ",".join(cleaned)})
    global COMFYUI_INSTANCES, COMFYUI_ADDRESS, BACKEND_LOCAL_LOAD
    COMFYUI_INSTANCES = cleaned
    COMFYUI_ADDRESS = cleaned[0]
    BACKEND_LOCAL_LOAD = comfy_instances.reset_backend_load(cleaned, BACKEND_LOCAL_LOAD)
    return COMFYUI_INSTANCES


def get_config_route_context():
    return {
        "AI_BASE_URL": AI_BASE_URL,
        "AI_API_KEY": AI_API_KEY,
        "CHAT_MODEL": CHAT_MODEL,
        "IMAGE_MODEL": IMAGE_MODEL,
        "CHAT_MODELS": CHAT_MODELS,
        "IMAGE_MODELS": IMAGE_MODELS,
        "VIDEO_MODELS": VIDEO_MODELS,
        "COMFYUI_INSTANCES": COMFYUI_INSTANCES,
        "MODELSCOPE_CHAT_MODELS": MODELSCOPE_CHAT_MODELS,
        "MODELSCOPE_API_KEY": MODELSCOPE_API_KEY,
        "GLOBAL_CONFIG_FILE": GLOBAL_CONFIG_FILE,
    }

app.include_router(config_routes.create_router(
    get_context=get_config_route_context,
    load_api_providers=load_api_providers,
    public_provider=public_provider,
    normalize_provider=normalize_provider,
    provider_key_env=provider_utils.provider_key_env,
    save_api_providers=save_api_providers,
    update_env_values=update_env_values,
    reload_env_globals=reload_env_globals,
    discover_local_comfyui_instances=discover_local_comfyui_instances,
))

ensure_runtime_dirs()

bootstrap.setup_static_files(app, static_dir=STATIC_DIR, output_dir=OUTPUT_DIR, assets_dir=ASSETS_DIR)


def get_media_route_context():
    return {
        "PUBLIC_UPLOAD_ENDPOINT": PUBLIC_UPLOAD_ENDPOINT,
        "MOTION_TRANSFER_PUBLIC_BASE_URL": MOTION_TRANSFER_PUBLIC_BASE_URL,
    }


app.include_router(media_routes.create_router(
    get_comfyui_instances=lambda: COMFYUI_INSTANCES,
    get_active_comfyui_instances=get_active_comfyui_instances,
    get_public_context=get_media_route_context,
))

def get_best_backend(required_images: List[str] = None):
    return comfy_backends.select_best_backend(
        get_active_comfyui_instances(),
        BACKEND_LOCAL_LOAD,
        LOAD_LOCK,
        required_images,
    )

# --- Helpers ---

comfy_runtime.configure({
    "output_path_for": output_path_for,
    "output_url_for": output_url_for,
})
download_image = comfy_runtime.download_image
comfy_output_extension = comfy_runtime.comfy_output_extension
is_video_output_item = comfy_runtime.is_video_output_item
download_comfy_output = comfy_runtime.download_comfy_output
get_comfy_history = comfy_runtime.get_comfy_history
describe_comfy_failure = comfy_runtime.describe_comfy_failure

def save_to_history(record):
    history_store.save_record(HISTORY_FILE, record)

unwrap_apimart_response = provider_responses.unwrap_apimart_response
text_from_chat_response = provider_responses.text_from_chat_response
text_delta_from_chat_chunk = provider_responses.text_delta_from_chat_chunk
sse_event = provider_responses.sse_event
extract_images = provider_responses.extract_images
extract_image = provider_responses.extract_image
extract_task_id = provider_responses.extract_task_id
images_api_unsupported = provider_responses.images_api_unsupported
video_output_urls = provider_responses.video_output_urls

resolve_chat_provider = provider_runtime.resolve_chat_provider
api_headers = provider_runtime.api_headers
provider_protocol = provider_runtime.provider_protocol
provider_holo_hint = provider_runtime.provider_holo_hint
provider_seedance_hint = provider_runtime.provider_seedance_hint
provider_volc_visual_hint = provider_runtime.provider_volc_visual_hint
provider_runninghub_hint = provider_runtime.provider_runninghub_hint
is_apimart_provider = provider_runtime.is_apimart_provider
is_gemini_provider = provider_runtime.is_gemini_provider
is_holo_provider = provider_runtime.is_holo_provider
is_seedance_provider = provider_runtime.is_seedance_provider
is_volc_visual_provider = provider_runtime.is_volc_visual_provider
is_runninghub_provider = provider_runtime.is_runninghub_provider

# HOLO provider runtime lives in app.holo_runtime.

def video_api_root(provider):
    base_url = (provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if base_url.endswith("/v1") or base_url.endswith("/v2"):
        base_url = base_url.rsplit("/", 1)[0]
    return base_url

media_processing.configure({
    "ASSETS_DIR": ASSETS_DIR,
    "OUTPUT_DIR": OUTPUT_DIR,
    "VIDEO_POLL_TIMEOUT": VIDEO_POLL_TIMEOUT,
    "output_file_from_url": output_file_from_url,
    "output_path_for": output_path_for,
    "output_url_for": output_url_for,
    "content_type_for_path": content_type_for_path,
    "video_api_root": video_api_root,
    "api_headers": api_headers,
})
convert_output_to_jpg = media_processing.convert_output_to_jpg
reference_to_data_url = media_processing.reference_to_data_url
compress_data_url_image = media_processing.compress_data_url_image
modelscope_image_url = media_processing.modelscope_image_url
valid_video_image_input = media_processing.valid_video_image_input
valid_apimart_video_image_input = media_processing.valid_apimart_video_image_input
is_apimart_veo31_model = media_processing.is_apimart_veo31_model
apimart_veo31_model = media_processing.apimart_veo31_model
apimart_veo31_aspect = media_processing.apimart_veo31_aspect
apimart_veo31_resolution = media_processing.apimart_veo31_resolution
apimart_upload_file_payload = media_processing.apimart_upload_file_payload
invalid_video_image_preview = media_processing.invalid_video_image_preview
extract_apimart_asset_url = media_processing.extract_apimart_asset_url
apimart_upload_payload_from_bytes = media_processing.apimart_upload_payload_from_bytes
upload_image_for_apimart = media_processing.upload_image_for_apimart
save_ai_image_to_output = media_processing.save_ai_image_to_output
save_remote_video_to_output = media_processing.save_remote_video_to_output

holo_runtime.configure({
    "VIDEO_POLL_TIMEOUT": VIDEO_POLL_TIMEOUT,
    "IMAGE_POLL_INTERVAL": IMAGE_POLL_INTERVAL,
    "api_headers": api_headers,
    "reference_to_data_url": reference_to_data_url,
    "compress_data_url_image": compress_data_url_image,
    "extract_task_id": extract_task_id,
    "video_output_urls": video_output_urls,
    "save_remote_video_to_output": save_remote_video_to_output,
    "extract_image": extract_image,
    "save_ai_image_to_output": save_ai_image_to_output,
    "output_path_for": output_path_for,
    "output_url_for": output_url_for,
})
holo_api_url = holo_runtime.holo_api_url
holo_headers = holo_runtime.holo_headers
holo_reference_url = holo_runtime.holo_reference_url
build_holo_messages = holo_runtime.build_holo_messages
extract_holo_task_id = holo_runtime.extract_holo_task_id
holo_task_payload = holo_runtime.holo_task_payload
holo_task_status = holo_runtime.holo_task_status
is_holo_task_done = holo_runtime.is_holo_task_done
is_holo_task_failed = holo_runtime.is_holo_task_failed
holo_file_url_from_task = holo_runtime.holo_file_url_from_task
holo_result_ext = holo_runtime.holo_result_ext
parse_json_response_text = holo_runtime.parse_json_response_text
holo_upstream_error_detail = holo_runtime.holo_upstream_error_detail
is_retryable_holo_response = holo_runtime.is_retryable_holo_response
holo_request_with_retry = holo_runtime.holo_request_with_retry
wait_for_holo_task = holo_runtime.wait_for_holo_task
save_holo_file_to_output = holo_runtime.save_holo_file_to_output

def configure_image_generation():
    image_generation.configure({
        "AI_BASE_URL": AI_BASE_URL,
        "AI_REQUEST_TIMEOUT": AI_REQUEST_TIMEOUT,
        "IMAGE_POLL_INTERVAL": IMAGE_POLL_INTERVAL,
        "IMAGE_TASK_TIMEOUT": IMAGE_TASK_TIMEOUT,
        "APIMART_IMAGE_TASK_TIMEOUT": APIMART_IMAGE_TASK_TIMEOUT,
        "APIMART_IMAGE_POLL_INTERVAL": APIMART_IMAGE_POLL_INTERVAL,
        "APIMART_IMAGE_INITIAL_POLL_DELAY": APIMART_IMAGE_INITIAL_POLL_DELAY,
        "MODELSCOPE_API_KEY": MODELSCOPE_API_KEY,
        "MODELSCOPE_CHAT_BASE_URL": MODELSCOPE_CHAT_BASE_URL,
        "HOLO_DEFAULT_IMAGE_MODELS": HOLO_DEFAULT_IMAGE_MODELS,
        "HOLO_DEFAULT_VIDEO_MODELS": HOLO_DEFAULT_VIDEO_MODELS,
        "VIDEO_POLL_TIMEOUT": VIDEO_POLL_TIMEOUT,
        "get_api_provider": get_api_provider,
        "model_list_from_values": model_list_from_values,
        "provider_endpoint_url": provider_endpoint_url,
        "api_headers": api_headers,
        "selected_model": selected_model,
        "is_holo_provider": is_holo_provider,
        "is_gemini_provider": is_gemini_provider,
        "is_apimart_provider": is_apimart_provider,
        "images_api_unsupported": images_api_unsupported,
        "extract_image": extract_image,
        "extract_images": extract_images,
        "extract_task_id": extract_task_id,
        "modelscope_image_url": modelscope_image_url,
        "reference_to_data_url": reference_to_data_url,
        "valid_apimart_video_image_input": valid_apimart_video_image_input,
        "upload_image_for_apimart": upload_image_for_apimart,
        "save_ai_image_to_output": save_ai_image_to_output,
        "output_file_from_url": output_file_from_url,
        "content_type_for_path": content_type_for_path,
        "build_holo_messages": build_holo_messages,
        "holo_api_url": holo_api_url,
        "holo_request_with_retry": holo_request_with_retry,
        "holo_headers": holo_headers,
        "extract_holo_task_id": extract_holo_task_id,
        "wait_for_holo_task": wait_for_holo_task,
        "save_holo_file_to_output": save_holo_file_to_output,
    })

configure_image_generation()
is_t8api_provider = image_generation.is_t8api_provider
generate_t8api_images = image_generation.generate_t8api_images
generate_holo_images = image_generation.generate_holo_images
generate_ai_image = image_generation.generate_ai_image
upstream_message_from_record = image_generation.upstream_message_from_record

app.include_router(chat_routes.create_router({
    "safe_user_id": safe_user_id,
    "load_conversation": load_conversation,
    "new_conversation": new_conversation,
    "save_conversation": save_conversation,
    "display_title": display_title,
    "now_ms": now_ms,
    "selected_model": selected_model,
    "get_api_provider": get_api_provider,
    "is_apimart_provider": is_apimart_provider,
    "resolve_chat_provider": resolve_chat_provider,
    "generate_ai_image": generate_ai_image,
    "save_ai_image_to_output": save_ai_image_to_output,
    "reference_to_data_url": reference_to_data_url,
    "text_from_chat_response": text_from_chat_response,
    "text_delta_from_chat_chunk": text_delta_from_chat_chunk,
    "upstream_message_from_record": upstream_message_from_record,
    "unwrap_apimart_response": unwrap_apimart_response,
    "sse_event": sse_event,
    "IMAGE_MODEL": IMAGE_MODEL,
    "SYSTEM_PROMPT": SYSTEM_PROMPT,
    "MAX_HISTORY_MESSAGES": MAX_HISTORY_MESSAGES,
    "AI_REQUEST_TIMEOUT": AI_REQUEST_TIMEOUT,
}))

# --- Online Image Generation ---

app.include_router(provider_model_routes.create_router({
    "supported_protocols": SUPPORTED_PROVIDER_PROTOCOLS,
    "provider_key_env": provider_utils.provider_key_env,
    "provider_protocol": provider_protocol,
    "get_api_provider_exact": get_api_provider_exact,
    "runninghub_api_base_url": lambda provider: runninghub_api_base_url(provider),
    "holo_api_url": holo_api_url,
    "volc_visual_default_base_url": VOLC_VISUAL_DEFAULT_BASE_URL,
    "volc_visual_motion_model": VOLC_VISUAL_MOTION_MODEL,
    "seedance_default_video_models": SEEDANCE_DEFAULT_VIDEO_MODELS,
}))
online_image_service.configure({
    "IMAGE_MODEL": IMAGE_MODEL,
    "HOLO_DEFAULT_IMAGE_MODELS": HOLO_DEFAULT_IMAGE_MODELS,
    "get_api_provider": get_api_provider,
    "selected_model": selected_model,
    "is_holo_provider": is_holo_provider,
    "is_apimart_provider": is_apimart_provider,
    "is_t8api_provider": is_t8api_provider,
    "generate_holo_images": generate_holo_images,
    "generate_t8api_images": generate_t8api_images,
    "generate_ai_image": generate_ai_image,
    "save_ai_image_to_output": save_ai_image_to_output,
    "extract_task_id": extract_task_id,
    "save_to_history": save_to_history,
    "manager": manager,
    "get_global_loop": lambda: GLOBAL_LOOP,
})
build_online_image_result = online_image_service.build_online_image_result

app.include_router(online_image_routes.create_router({
    "build_online_image_result": build_online_image_result,
}))

app.include_router(prompt_template_routes.create_router({
    "DATA_DIR": DATA_DIR,
}))

app.include_router(ai_site_routes.create_router({
    "DATA_DIR": DATA_DIR,
}))

app.include_router(creative_tool_routes.create_router({
    "build_online_image_result": build_online_image_result,
    "save_to_history": save_to_history,
}))

app.include_router(canvas_image_task_routes.create_router({
    "build_online_image_result": build_online_image_result,
    "load_canvas": load_canvas,
    "save_canvas": save_canvas,
    "now_ms": now_ms,
    "manager": manager,
}))

# --- Canvas Video ---

# Shared video response parsing lives in app.provider_responses.

app.include_router(video_generation_routes.create_router({
    "AI_BASE_URL": AI_BASE_URL,
    "IMAGE_POLL_INTERVAL": IMAGE_POLL_INTERVAL,
    "VIDEO_POLL_TIMEOUT": VIDEO_POLL_TIMEOUT,
    "VOLC_VISUAL_DEFAULT_BASE_URL": VOLC_VISUAL_DEFAULT_BASE_URL,
    "VOLC_VISUAL_MOTION_MODEL": VOLC_VISUAL_MOTION_MODEL,
    "SEEDANCE_DEFAULT_BASE_URL": SEEDANCE_DEFAULT_BASE_URL,
    "SEEDANCE_DEFAULT_VIDEO_MODELS": SEEDANCE_DEFAULT_VIDEO_MODELS,
    "MOTION_TRANSFER_PUBLIC_BASE_URL": MOTION_TRANSFER_PUBLIC_BASE_URL,
    "PUBLIC_UPLOAD_ENDPOINT": PUBLIC_UPLOAD_ENDPOINT,
    "get_api_provider": get_api_provider,
    "provider_key_env": provider_utils.provider_key_env,
    "api_headers": api_headers,
    "selected_model": selected_model,
    "extract_task_id": extract_task_id,
    "video_output_urls": video_output_urls,
    "is_apimart_provider": is_apimart_provider,
    "is_seedance_provider": is_seedance_provider,
    "is_holo_provider": is_holo_provider,
    "is_volc_visual_provider": is_volc_visual_provider,
    "is_apimart_veo31_model": is_apimart_veo31_model,
    "apimart_veo31_model": apimart_veo31_model,
    "apimart_veo31_aspect": apimart_veo31_aspect,
    "apimart_veo31_resolution": apimart_veo31_resolution,
    "valid_apimart_video_image_input": valid_apimart_video_image_input,
    "invalid_video_image_preview": invalid_video_image_preview,
    "upload_image_for_apimart": upload_image_for_apimart,
    "reference_to_data_url": reference_to_data_url,
    "compress_data_url_image": compress_data_url_image,
    "output_file_from_url": output_file_from_url,
    "upload_path_to_public_storage": upload_path_to_public_storage,
    "save_remote_video_to_output": save_remote_video_to_output,
    "holo_api_url": holo_api_url,
    "holo_headers": holo_headers,
    "build_holo_messages": build_holo_messages,
    "holo_request_with_retry": holo_request_with_retry,
    "extract_holo_task_id": extract_holo_task_id,
    "wait_for_holo_task": wait_for_holo_task,
    "save_holo_file_to_output": save_holo_file_to_output,
    "save_to_history": save_to_history,
}))

app.include_router(dreamina_cli_routes.create_router({
    "save_to_history": save_to_history,
}))

rh_runtime.configure({
    "get_api_provider_exact": get_api_provider_exact,
    "provider_key_env": provider_utils.provider_key_env,
    "RUNNINGHUB_WORKFLOWS_FILE": RUNNINGHUB_WORKFLOWS_FILE,
    "DATA_DIR": DATA_DIR,
    "GLOBAL_CONFIG_LOCK": GLOBAL_CONFIG_LOCK,
    "now_ms": now_ms,
})
runninghub_base_url = rh_runtime.runninghub_base_url
runninghub_api_base_url = rh_runtime.runninghub_api_base_url
runninghub_upload_base_url = rh_runtime.runninghub_upload_base_url
runninghub_api_key = rh_runtime.runninghub_api_key
runninghub_headers = rh_runtime.runninghub_headers
load_runninghub_workflows = rh_runtime.load_runninghub_workflows
save_runninghub_workflows = rh_runtime.save_runninghub_workflows
runninghub_fields_from_workflow_json = rh_runtime.runninghub_fields_from_workflow_json
normalize_runninghub_workflow = rh_runtime.normalize_runninghub_workflow
convert_runninghub_frontend_workflow = rh_runtime.convert_runninghub_frontend_workflow

app.include_router(runninghub_routes.create_router({
    "load_workflows": load_runninghub_workflows,
    "save_workflows": save_runninghub_workflows,
    "normalize_workflow": normalize_runninghub_workflow,
    "fields_from_workflow_json": runninghub_fields_from_workflow_json,
    "convert_frontend_workflow": convert_runninghub_frontend_workflow,
    "get_api_provider_exact": get_api_provider_exact,
    "is_runninghub_provider": is_runninghub_provider,
    "runninghub_api_key": runninghub_api_key,
    "runninghub_base_url": runninghub_base_url,
    "runninghub_api_base_url": runninghub_api_base_url,
    "runninghub_upload_base_url": runninghub_upload_base_url,
    "runninghub_headers": runninghub_headers,
    "node_info_from_payload": runninghub_routes.node_info_from_payload,
    "save_to_history": save_to_history,
    "save_ai_image_to_output": save_ai_image_to_output,
    "save_remote_video_to_output": save_remote_video_to_output,
    "get_global_loop": lambda: GLOBAL_LOOP,
    "manager": manager,
    "now_ms": now_ms,
}))

app.include_router(modelscope_angle_routes.create_router({
    "get_modelscope_api_key": lambda: MODELSCOPE_API_KEY,
    "modelscope_image_url": modelscope_image_url,
    "modelscope_size": modelscope_size,
    "selected_model": selected_model,
    "output_path_for": output_path_for,
    "output_url_for": output_url_for,
    "save_to_history": save_to_history,
    "manager": manager,
    "get_global_loop": lambda: GLOBAL_LOOP,
}))

app.include_router(modelscope_image_routes.create_router({
    "get_modelscope_api_key": lambda: MODELSCOPE_API_KEY,
    "modelscope_image_url": modelscope_image_url,
    "modelscope_size": modelscope_size,
    "output_path_for": output_path_for,
    "output_url_for": output_url_for,
    "save_to_history": save_to_history,
    "manager": manager,
    "get_global_loop": lambda: GLOBAL_LOOP,
}))

# --- Local ComfyUI Image Generation ---
# API prompt repair and helper-node folding live in app.comfyui.api_prompt.

app.include_router(local_generate_routes.create_router({
    "LOCAL_TASK_QUEUE": LOCAL_TASK_QUEUE,
    "LOAD_LOCK": LOAD_LOCK,
    "BACKEND_LOCAL_LOAD": BACKEND_LOCAL_LOAD,
    "WORKFLOW_DIR": WORKFLOW_DIR,
    "WORKFLOW_PATH": WORKFLOW_PATH,
    "CLIENT_ID": CLIENT_ID,
    "COMFYUI_HISTORY_TIMEOUT": COMFYUI_HISTORY_TIMEOUT,
    "get_best_backend": get_best_backend,
    "content_type_for_path": content_type_for_path,
    "get_active_comfyui_instances": get_active_comfyui_instances,
    "repair_body_ratio_mapper_api_values": repair_body_ratio_mapper_api_values,
    "validate_body_ratio_mapper_api_values": validate_body_ratio_mapper_api_values,
    "repair_flux_latent_resolution_steps": repair_flux_latent_resolution_steps,
    "strip_comfy_reroute_nodes": strip_comfy_reroute_nodes,
    "fold_comfy_api_helper_nodes": fold_comfy_api_helper_nodes,
    "get_comfy_history": get_comfy_history,
    "download_comfy_output": download_comfy_output,
    "convert_output_to_jpg": convert_output_to_jpg,
    "describe_comfy_failure": describe_comfy_failure,
    "save_to_history": save_to_history,
    "manager": manager,
    "get_global_loop": lambda: GLOBAL_LOOP,
}))

app.include_router(comfy_instance_routes.create_router({
    "get_instances": lambda: COMFYUI_INSTANCES,
    "discover_local_instances": discover_local_comfyui_instances,
    "motion_transfer_fields": motion_transfer_workflow_fields,
    "save_instances": save_comfyui_instance_config,
}))
app.include_router(comfy_workflow_routes.create_router(local_generate_routes.generate))
if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Start OCT Studio local server")
    parser.add_argument("--port", type=int, default=None, help="HTTP port to listen on")
    args = parser.parse_args()
    requested_port = int(args.port or os.getenv("APP_PORT", "3010"))
    try:
        app_port = bootstrap.find_available_port(requested_port)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if app_port != requested_port:
        print(f"Port {requested_port} is unavailable; using {app_port} instead.")
    os.environ["APP_PORT"] = str(app_port)
    bootstrap.schedule_open_local_browser(app_port)
    uvicorn.run(app, host="0.0.0.0", port=app_port)
