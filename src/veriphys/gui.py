"""Small desktop interface for checking physics answers with VeriPhys."""

from __future__ import annotations

import argparse
import json
import os
import queue
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .check_answer import AnswerCheckResult, check_answer

try:  # Tkinter is part of most Python distributions, but may be omitted.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - depends on the host Python build.
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = ttk = None  # type: ignore[assignment]


DEFAULT_PROBLEM = "A body has mass m and force F. Given F = m*a, check a = F/m."
DEFAULT_ANSWER = "a = F/m"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def result_as_json(result: AnswerCheckResult) -> str:
    """Serialize one result for the GUI and the Save report action."""

    return json.dumps(asdict(result), ensure_ascii=False, indent=2)


def result_summary(result: AnswerCheckResult) -> str:
    """Return a compact human-readable result for the summary tab."""

    lines = [
        f"状态: {result.status.upper()}",
        f"流水线: {'IR' if result.pipeline == 'ir' else 'Direct'}",
        f"Lean 验证: {'通过' if result.lean_verified else '未通过/未运行'}",
    ]
    if result.proof_contract_verified:
        lines.append("IR proof contract: 通过")
    if result.answer_expression:
        lines.append(f"形式化答案: {result.answer_expression}")
    if result.repair_attempts:
        lines.append(f"修复次数: {result.repair_attempts}")
    if result.error:
        lines.extend(("", "错误或诊断:", result.error))
    return "\n".join(lines)


def _pretty_json(value: object | None) -> str:
    if value is None:
        return "（无）"
    return json.dumps(value, ensure_ascii=False, indent=2)


class VeriPhysApp:
    """Tkinter front end. Model and Lean work runs outside the UI thread."""

    def __init__(self, root: Any, *, project_dir: str | Path = "lean") -> None:
        if tk is None or ttk is None:
            raise RuntimeError("当前 Python 没有安装 Tkinter，无法启动 GUI。")
        self.root = root
        self.project_dir = Path(project_dir)
        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_result: AnswerCheckResult | None = None
        self.busy = False

        root.title("VeriPhys — Lean Physics Checker")
        root.minsize(900, 680)
        root.geometry("1100x820")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        self._build_controls()
        self._build_results()
        self._set_text(self.problem_text, DEFAULT_PROBLEM)
        self.answer_var.set(DEFAULT_ANSWER)
        self._set_status("就绪", "#555555")
        self.root.after(100, self._poll_result_queue)

    def _build_controls(self) -> None:
        controls = ttk.Frame(self.root, padding=12)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="题目").grid(row=0, column=0, sticky="nw", padx=(0, 8))
        self.problem_text = tk.Text(controls, height=5, wrap="word")
        self.problem_text.grid(row=0, column=1, columnspan=5, sticky="ew", pady=(0, 8))

        ttk.Label(controls, text="候选答案").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.answer_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.answer_var).grid(
            row=1, column=1, columnspan=5, sticky="ew", pady=(0, 8)
        )

        ttk.Label(controls, text="流水线").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self.pipeline_var = tk.StringVar(value="IR")
        ttk.Combobox(
            controls,
            textvariable=self.pipeline_var,
            values=("Direct", "IR"),
            state="readonly",
            width=12,
        ).grid(row=2, column=1, sticky="w")

        ttk.Label(controls, text="模型").grid(row=2, column=2, sticky="e", padx=(18, 8))
        self.model_var = tk.StringVar(value=os.getenv("VERIPHYS_MODEL", "gpt-6-astra"))
        ttk.Entry(controls, textvariable=self.model_var, width=24).grid(row=2, column=3, sticky="w")

        ttk.Label(controls, text="最大修复次数").grid(row=2, column=4, sticky="e", padx=(18, 8))
        self.repairs_var = tk.IntVar(value=0)
        ttk.Spinbox(controls, from_=0, to=3, textvariable=self.repairs_var, width=5).grid(
            row=2, column=5, sticky="w"
        )

        actions = ttk.Frame(controls)
        actions.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(12, 0))
        self.check_button = ttk.Button(actions, text="检查答案", command=self.start_check)
        self.check_button.pack(side="left")
        self.save_button = ttk.Button(actions, text="保存 JSON 报告", command=self.save_report, state="disabled")
        self.save_button.pack(side="left", padx=(8, 0))
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(
            actions,
            textvariable=self.status_var,
            style="VeriPhysStatus.TLabel",
        )
        self.status_label.pack(side="left", padx=(16, 0))

    def _build_results(self) -> None:
        container = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        container.grid(row=1, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.result_widgets: dict[str, tk.Text] = {}
        for name, label in (
            ("summary", "结果"),
            ("ir", "Physics IR"),
            ("assumptions", "假设"),
            ("lean", "Lean 源码"),
            ("diagnostics", "诊断 / JSON"),
        ):
            frame = ttk.Frame(self.notebook)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            widget = tk.Text(frame, wrap="none", state="disabled", undo=False)
            widget.grid(row=0, column=0, sticky="nsew")
            yscroll = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
            yscroll.grid(row=0, column=1, sticky="ns")
            widget.configure(yscrollcommand=yscroll.set)
            self.notebook.add(frame, text=label)
            self.result_widgets[name] = widget

    @staticmethod
    def _set_text(widget: Any, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        # ttk labels do not honor foreground without a style.
        style_name = "VeriPhysStatus.TLabel"
        style = ttk.Style(self.root)
        style.configure(style_name, foreground=color)

    def start_check(self) -> None:
        if self.busy:
            return
        problem = self.problem_text.get("1.0", "end").strip()
        answer = self.answer_var.get().strip()
        if not problem or not answer:
            messagebox.showwarning("缺少输入", "请填写题目和候选答案。")
            return
        try:
            max_repairs = int(self.repairs_var.get())
        except (TypeError, ValueError):
            messagebox.showwarning("参数错误", "最大修复次数必须是 0 到 3。")
            return
        if max_repairs not in range(4):
            messagebox.showwarning("参数错误", "最大修复次数必须是 0 到 3。")
            return

        self.busy = True
        self.check_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self._set_status("正在请求模型并运行 Lean…", "#8a5a00")
        thread = threading.Thread(
            target=self._run_check,
            args=(problem, answer, self.pipeline_var.get() == "IR", self.model_var.get().strip(), max_repairs),
            daemon=True,
        )
        thread.start()

    def _run_check(
        self, problem: str, answer: str, use_ir: bool, model: str, max_repairs: int
    ) -> None:
        try:
            result = check_answer(
                problem,
                answer,
                project_dir=self.project_dir,
                model=model or None,
                use_ir=use_ir,
                max_repairs=max_repairs,
            )
            self.result_queue.put(("result", result))
        except Exception as exc:  # GUI must always return control to the user.
            self.result_queue.put(("error", exc))

    def _poll_result_queue(self) -> None:
        try:
            kind, payload = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_result_queue)
            return
        self.busy = False
        self.check_button.configure(state="normal")
        if kind == "error":
            self.last_result = None
            self._set_status("GUI 错误", "#a00000")
            self._set_text(self.result_widgets["summary"], f"GUI 运行错误:\n{payload}")
        else:
            self._show_result(payload)  # type: ignore[arg-type]
        self.root.after(100, self._poll_result_queue)

    def _show_result(self, result: AnswerCheckResult) -> None:
        self.last_result = result
        color = {"verified": "#137333", "rejected": "#a33a00", "error": "#a00000"}.get(
            result.status, "#555555"
        )
        self._set_status(result.status.upper(), color)
        self._set_text(self.result_widgets["summary"], result_summary(result))
        self._set_text(self.result_widgets["ir"], _pretty_json(result.physics_ir))
        self._set_text(self.result_widgets["assumptions"], _pretty_json(result.assumptions))
        self._set_text(self.result_widgets["lean"], result.lean_code or "（无 Lean 源码）")
        self._set_text(self.result_widgets["diagnostics"], result_as_json(result))
        self.save_button.configure(state="normal")
        self.notebook.select(0)

    def save_report(self) -> None:
        if self.last_result is None:
            return
        path = filedialog.asksaveasfilename(
            title="保存 VeriPhys 报告",
            defaultextension=".json",
            filetypes=(("JSON 文件", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            Path(path).write_text(result_as_json(self.last_result) + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
        else:
            self._set_status(f"已保存: {path}", "#137333")


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the VeriPhys desktop GUI")
    parser.add_argument("--project-dir", type=Path, default=REPOSITORY_ROOT / "lean")
    args = parser.parse_args()
    if tk is None:
        parser.error("当前 Python 没有安装 Tkinter。")
    root = tk.Tk()
    VeriPhysApp(root, project_dir=args.project_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
