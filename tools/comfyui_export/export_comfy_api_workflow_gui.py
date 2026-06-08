#!/usr/bin/env python3
"""Tkinter GUI for exporting repaired ComfyUI API workflows."""

from __future__ import annotations

import json
import os
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace
from typing import Any

import comfy_api_workflow_converter as converter
import export_comfy_api_workflow as export_tool


APP_TITLE = "ComfyUI API 工作流导出工具"
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / "workflows" / "comfyui_full"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "comfyui_exports"


class ExportApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("920x620")
        self.minsize(820, 560)

        self.workflow_paths: list[Path] = []
        self.last_outputs: dict[str, Path] | None = None

        self.workflow_var = tk.StringVar()
        self.api_input_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.name_var = tk.StringVar()
        self.profile_var = tk.StringVar(value="auto")
        self.output_mode_var = tk.StringVar(value="all")
        self.main_output_var = tk.StringVar(value=export_tool.DEFAULT_MAIN_OUTPUT_ID)
        self.status_var = tk.StringVar(value="Ready")

        self._build_style()
        self._build_ui()
        self.refresh_workflows()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.configure("TFrame", padding=0)
        style.configure("Section.TLabelframe", padding=12)
        style.configure("Primary.TButton", padding=(16, 8))
        style.configure("Tool.TButton", padding=(10, 5))
        style.configure("Status.TLabel", padding=(8, 4))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 17, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="刷新", style="Tool.TButton", command=self.refresh_workflows).grid(row=0, column=1, padx=(8, 0))

        workflow_box = ttk.LabelFrame(root, text="工作流", style="Section.TLabelframe")
        workflow_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        workflow_box.columnconfigure(1, weight=1)

        ttk.Label(workflow_box, text="完整工作流").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        self.workflow_combo = ttk.Combobox(workflow_box, textvariable=self.workflow_var, state="normal")
        self.workflow_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.workflow_combo.bind("<<ComboboxSelected>>", self.on_workflow_selected)
        ttk.Button(workflow_box, text="浏览", style="Tool.TButton", command=self.browse_workflow).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(workflow_box, text="原生 API").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(workflow_box, textvariable=self.api_input_var).grid(row=1, column=1, sticky="ew", pady=4)
        api_buttons = ttk.Frame(workflow_box)
        api_buttons.grid(row=1, column=2, sticky="e", padx=(8, 0), pady=4)
        ttk.Button(api_buttons, text="浏览", style="Tool.TButton", command=self.browse_api_input).pack(side=tk.LEFT)
        ttk.Button(api_buttons, text="清空", style="Tool.TButton", command=lambda: self.api_input_var.set("")).pack(side=tk.LEFT, padx=(6, 0))

        output_box = ttk.LabelFrame(root, text="输出", style="Section.TLabelframe")
        output_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        output_box.columnconfigure(1, weight=1)

        ttk.Label(output_box, text="输出文件夹").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(output_box, textvariable=self.output_dir_var).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(output_box, text="浏览", style="Tool.TButton", command=self.browse_output_dir).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(output_box, text="文件名").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(output_box, textvariable=self.name_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(output_box, text="自动", style="Tool.TButton", command=self.set_auto_name).grid(row=1, column=2, padx=(8, 0), pady=4)

        options = ttk.Frame(output_box)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        options.columnconfigure(7, weight=1)
        ttk.Label(options, text="配置").grid(row=0, column=0, sticky="w")
        ttk.Combobox(options, textvariable=self.profile_var, values=["auto", "motiontransfer", "generic"], state="readonly", width=16).grid(row=0, column=1, padx=(8, 18))
        ttk.Label(options, text="模式").grid(row=0, column=2, sticky="w")
        ttk.Combobox(options, textvariable=self.output_mode_var, values=["all", "main"], state="readonly", width=10).grid(row=0, column=3, padx=(8, 18))
        ttk.Label(options, text="主输出ID").grid(row=0, column=4, sticky="w")
        ttk.Entry(options, textvariable=self.main_output_var, width=10).grid(row=0, column=5, padx=(8, 18))
        ttk.Button(options, text="导出", style="Primary.TButton", command=self.start_export).grid(row=0, column=6, sticky="e")
        ttk.Button(options, text="打开文件夹", style="Tool.TButton", command=self.open_output_folder).grid(row=0, column=7, sticky="e", padx=(8, 0))

        log_box = ttk.LabelFrame(root, text="结果", style="Section.TLabelframe")
        log_box.grid(row=3, column=0, sticky="nsew")
        log_box.rowconfigure(0, weight=1)
        log_box.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_box, wrap="word", height=12, font=("Consolas", 10), borderwidth=0)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_box, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        status = ttk.Label(root, textvariable=self.status_var, style="Status.TLabel")
        status.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def refresh_workflows(self) -> None:
        self.workflow_paths = export_tool.find_workflows(WORKFLOW_DIR)
        values = [path.name for path in self.workflow_paths]
        self.workflow_combo.configure(values=values)
        if values and not self.workflow_var.get():
            self.workflow_var.set(values[0])
            self.set_auto_name()
        self.log(f"已加载 {len(values)} 个工作流：{WORKFLOW_DIR}")

    def on_workflow_selected(self, _event: object | None = None) -> None:
        self.set_auto_name()

    def selected_workflow_path(self) -> Path | None:
        raw = self.workflow_var.get().strip()
        if not raw:
            return None
        for path in self.workflow_paths:
            if raw == path.name or raw == str(path):
                return path
        path = Path(raw.strip('"'))
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        return path

    def set_auto_name(self) -> None:
        path = self.selected_workflow_path()
        if path:
            self.name_var.set(f"{path.stem}_api_fixed")

    def browse_workflow(self) -> None:
        path = filedialog.askopenfilename(
            title="选择完整 ComfyUI 工作流",
            initialdir=str(WORKFLOW_DIR if WORKFLOW_DIR.exists() else REPO_ROOT),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            chosen = Path(path)
            self.workflow_var.set(str(chosen))
            self.set_auto_name()

    def browse_api_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择原生 Export(API) JSON",
            initialdir=str(export_tool.default_desktop()),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.api_input_var.set(path)

    def browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出文件夹", initialdir=self.output_dir_var.get() or str(DEFAULT_OUTPUT_DIR))
        if path:
            self.output_dir_var.set(path)

    def start_export(self) -> None:
        if hasattr(self, "_worker") and self._worker.is_alive():
            messagebox.showinfo(APP_TITLE, "正在导出，请稍等。")
            return
        request = {
            "workflow_path": self.selected_workflow_path(),
            "api_input": self.api_input_var.get().strip().strip('"'),
            "output_dir": self.output_dir_var.get().strip().strip('"'),
            "output_name": self.name_var.get().strip(),
            "profile": self.profile_var.get(),
            "output_mode": self.output_mode_var.get(),
            "main_output_id": self.main_output_var.get().strip() or export_tool.DEFAULT_MAIN_OUTPUT_ID,
        }
        self.status_var.set("正在导出...")
        self.log_text.delete("1.0", tk.END)
        self._worker = threading.Thread(target=self.run_export, args=(request,), daemon=True)
        self._worker.start()

    def run_export(self, request: dict[str, Any]) -> None:
        try:
            workflow_path = request["workflow_path"]
            if not workflow_path:
                raise ValueError("请先选择完整 ComfyUI 工作流。")
            workflow_path = workflow_path.resolve()
            if not workflow_path.exists():
                raise FileNotFoundError(f"Workflow not found: {workflow_path}")
            workflow_data = export_tool.validate_workflow(workflow_path)

            api_input = request["api_input"]
            api_path = Path(api_input).resolve() if api_input else None
            if api_path:
                if not api_path.exists():
                    raise FileNotFoundError(f"Export(API) file not found: {api_path}")
                export_tool.validate_api_prompt(api_path)

            output_dir = Path(request["output_dir"] or DEFAULT_OUTPUT_DIR).resolve()
            output_name = request["output_name"] or f"{workflow_path.stem}_api_fixed"
            profile = export_tool.detect_profile(workflow_data, request["profile"])
            outputs = export_tool.make_outputs(output_dir, output_name)

            args = SimpleNamespace(
                input=workflow_path,
                api_input=api_path,
                workflow_output=outputs["workflow"],
                api_output=outputs["api"],
                mapping_output=outputs["mapping"],
                main_output_id=request["main_output_id"],
                output_mode=request["output_mode"],
                profile=profile,
            )
            mapping = converter.convert(args)
            self.last_outputs = outputs
            self.after(0, self.show_success, mapping, outputs, profile)
        except Exception as exc:
            details = traceback.format_exc()
            self.after(0, self.show_error, exc, details)

    def show_success(self, mapping: dict[str, Any], outputs: dict[str, Path], profile: str) -> None:
        validation = mapping.get("validation", {})
        switches = mapping.get("runtime_switches", {})
        converted = mapping.get("flatten_set_get", {}).get("converted", [])
        frontend_switches = mapping.get("frontend_switches", {}).get("converted", [])
        compatible_nodes = mapping.get("compatible_custom_nodes", {}).get("converted", [])
        reroutes = mapping.get("strip_reroute_nodes", {})
        overlay = mapping.get("api_value_overlay", {})
        changed = sum(len(item.get("inputs", [])) for item in overlay.get("updated", []))

        lines = [
            "导出完成。",
            "",
            f"API 文件:       {outputs['api']}",
            f"检查工作流:     {outputs['workflow']}",
            f"修复报告:       {outputs['mapping']}",
            "",
            f"配置:           {profile}",
            f"节点数:         {validation.get('nodes')}",
            f"连线数:         {validation.get('links')}",
            f"坏链接:         {validation.get('bad_links')}",
            f"Reroute 清理:   {reroutes.get('removed', 0)} 个",
            f"兼容节点替换:   {len(compatible_nodes)} 个",
            f"Set/Get 修复:   {len(converted)} 组",
            f"前端开关转换:   {len(frontend_switches)} 个",
            f"保留参数:       {changed} 个",
        ]
        if switches:
            lines.append(f"运行期开关:     {', '.join(switches)}")
        skipped = overlay.get("skipped", [])
        if skipped:
            lines.append(f"跳过参数:       {len(skipped)} 个；详见修复报告")
        self.log("\n".join(lines))
        self.status_var.set("完成")
        if validation.get("bad_links"):
            messagebox.showwarning(APP_TITLE, "导出完成，但检测到坏链接。请查看修复报告。")
        else:
            messagebox.showinfo(APP_TITLE, "导出完成。")

    def show_error(self, exc: Exception, details: str) -> None:
        self.log(f"导出失败：\n{exc}\n\n{details}")
        self.status_var.set("失败")
        messagebox.showerror(APP_TITLE, str(exc))

    def open_output_folder(self) -> None:
        folder = self.last_outputs["api"].parent if self.last_outputs else Path(self.output_dir_var.get() or DEFAULT_OUTPUT_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def log(self, text: str) -> None:
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)


def main() -> None:
    app = ExportApp()
    app.mainloop()


if __name__ == "__main__":
    main()
