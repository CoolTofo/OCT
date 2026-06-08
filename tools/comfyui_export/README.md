# OCT ComfyUI API Workflow Export Tool

This folder is bundled with OCT_Box so ComfyUI workflow conversion does not
depend on files under the user's Documents folder.

The ComfyUI settings page calls `comfy_api_workflow_converter.py` through the
local OCT server. Converted API workflows are saved to:

```text
OCT/workflows/custom
```

Optional conversion reports are saved to:

```text
OCT/data/comfyui_exports
```

Put full ComfyUI workflow JSON files in this optional local folder if you want
them to appear in the settings page list:

```text
OCT/workflows/comfyui_full
```

You can also upload a full workflow JSON directly from the settings page and
convert it without saving the source workflow first.
