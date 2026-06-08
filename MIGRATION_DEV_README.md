# OCT migration development clean package

Created: 20260608_190131

This package is for moving to another computer while keeping the project runnable
and editable.

Included:
- Source/runtime files: main.py, app/, static/, tools/
- Embedded runtime: python/
- Offline dependency wheels: packages/
- Recovery archive: python.zip
- Docs: Doc/ and root help files
- Existing workflows and presets: workflows/, data/comfyui_exports/,
  data/runninghub_workflows.json, data/prompt_templates.json,
  data/asset_library.json, data/canvases/, assets/library/
- API settings and existing keys: API/.env, API/.env.example,
  data/api_providers.json
- Parent development helper files: _dev_root_files/

Cleaned:
- Generated input/output media under assets/input, assets/output,
  assets/preview, and output
- Conversation contents under data/conversations
- Python bytecode caches and temporary logs

Restore on the new computer:
1. Extract all OCT_migration_dev_20260608_190131_part*.zip files to the same folder.
2. Enter the extracted OCT_migration_dev_20260608_190131 folder.
3. Run PowerShell: ./restore-large-files.ps1
4. Double-click the launch script.
5. If dependencies are missing, run the install-dependencies script.

Warning: API/.env is included and may contain API keys. Do not upload this package
to public storage or share it with untrusted people.
