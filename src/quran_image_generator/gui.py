"""Small tkinter front end over the existing application services."""

from __future__ import annotations

import random
import sys
import tkinter as tk
import webbrowser
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any

from .content import QuranDataClient
from .generator import build_generator, open_output
from .gui_state import (
    README_URL,
    CatalogSnapshot,
    FormValidationError,
    PreviewArtifact,
    PreviewSnapshot,
    PreviewWorkflow,
    RevisionGate,
    SavedArtifact,
    SingleWorker,
    StalePreviewError,
    WorkerResult,
    build_generation_request,
    matching_translation_resource,
    normalize_translation_entries,
    translation_entry_label,
    translation_label,
)
from .models import Chapter, TranslationResource
from .publishing import (
    InstagramPublisher,
    PublishTarget,
    resolve_instagram_credentials,
)
from .settings import (
    SETTING_SPEC_BY_KEY,
    SETTING_SPECS,
    Settings,
    SettingSpec,
    SettingsValidationError,
    load_settings,
    save_settings,
    settings_from_mapping,
    settings_help_text,
    settings_to_mapping,
)

_RENDERER_SETUP_MESSAGE = (
    "Image rendering is unavailable. Install Wand and ImageMagick, then restart. "
    "Configuration and Help remain available."
)


def _create_preview_workflow(
    settings: Settings,
    content_client: Any,
    *,
    generator_builder: Callable[..., Any] = build_generator,
) -> tuple[PreviewWorkflow | None, str | None]:
    """Build renderer-backed services while keeping setup failures display-safe."""

    try:
        generator = generator_builder(settings, content_client=content_client)
    except (ImportError, OSError):
        return None, _RENDERER_SETUP_MESSAGE
    return PreviewWorkflow(generator, content_client), None


class QuranImageGeneratorApp:
    """One deliberately plain, resizable desktop window."""

    _TAB_ORDER = (
        "Passage & Output",
        "Canvas",
        "Quran",
        "Translations",
        "Verse Numbers & Spacing",
    )

    def __init__(
        self,
        root: tk.Tk,
        config_path: Path | None = None,
        *,
        content_client: Any | None = None,
    ) -> None:
        self.root = root
        self.root.title("Quran Image Generator")
        self.root.geometry("1120x760")
        self.root.minsize(900, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self._closing = False
        self._catalog_after_id: str | None = None
        self._poll_after_id: str | None = None
        self._loading_form = True
        self._resize_after_id: str | None = None
        self._preview_source_image: tk.PhotoImage | None = None
        self._preview_display_image: tk.PhotoImage | None = None
        self._shown_preview_artifact: PreviewArtifact | None = None
        self._chapters: tuple[Chapter, ...] = ()
        self._chapter_by_label: dict[str, Chapter] = {}
        self._translation_resources: tuple[TranslationResource, ...] = ()
        self._translation_entries: list[Any] = []
        self._translation_font_dirty = False
        self._open_after_jobs: set[int] = set()
        self._locked_form_widgets: list[tuple[Any, str]] = []
        self._rng = random.Random()
        self._gate = RevisionGate()
        self._worker = SingleWorker()
        self._caption_studio: Any | None = None

        self._current_config_path = (
            Path.cwd() / "config.yaml"
            if config_path is None
            else config_path.expanduser().resolve(strict=False)
        )
        initial_message = "Ready. Load the Quran catalog to begin."
        configuration_error: str | None = None
        try:
            if config_path is None:
                self._settings = settings_from_mapping(
                    {}, source_path=self._current_config_path
                )
            else:
                self._settings = load_settings(config_path, create_output_dir=False)
        except SettingsValidationError as error:
            self._settings = settings_from_mapping(
                {}, source_path=self._current_config_path
            )
            configuration_error = (
                "The requested config could not be loaded; safe defaults are shown. "
                f"{error}"
            )
            initial_message = configuration_error

        self._workflow: PreviewWorkflow | None = None
        renderer_error: str | None = None
        if content_client is None:
            content_client = QuranDataClient()
        self._workflow, renderer_error = _create_preview_workflow(
            self._settings,
            content_client,
        )

        self._variables: dict[str, Any] = {}
        self._field_errors: dict[str, ttk.Label] = {}
        self._status_var = tk.StringVar(value=initial_message)
        self._chapter_var = tk.StringVar(value="")
        self._starting_verse_var = tk.StringVar(value="1")
        self._ending_verse_var = tk.StringVar(value="1")
        self._translation_font_var = tk.StringVar(value="")
        self._open_after_save_var = tk.BooleanVar(value=False)
        self._publish_target_var = tk.StringVar(value=PublishTarget.POST.value)
        self._passage_error_var = tk.StringVar(value="")
        self._build_variables()
        self._build_window()
        self._apply_settings(self._settings, mark_changed=False)
        self._install_traces()
        self._loading_form = False

        startup_notices = []
        if configuration_error is not None:
            startup_notices.append(configuration_error)
        if renderer_error is not None:
            startup_notices.append(renderer_error)
        if startup_notices:
            self._status_var.set(" ".join(startup_notices))
        if renderer_error is None and configuration_error is None:
            self._catalog_after_id = self.root.after(80, self._initial_catalog_refresh)
        self._update_actions()
        self._poll_after_id = self.root.after(100, self._poll_worker)

    def _initial_catalog_refresh(self) -> None:
        self._catalog_after_id = None
        self.refresh_catalog()

    def _build_variables(self) -> None:
        values = settings_to_mapping(
            self._settings,
            destination_path=self._current_config_path,
        )
        for spec in SETTING_SPECS:
            if spec.value_type == "translations":
                continue
            value = values[spec.key]
            if spec.value_type == "boolean":
                self._variables[spec.key] = tk.BooleanVar(value=bool(value))
            else:
                self._variables[spec.key] = tk.StringVar(value=str(value))

    def _build_window(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))

        controls = ttk.Frame(paned)
        preview = ttk.Frame(paned, padding=8)
        paned.add(controls, weight=3)
        paned.add(preview, weight=2)
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(controls)
        self._notebook = notebook
        notebook.grid(row=0, column=0, sticky="nsew")
        self._tab_frames: dict[str, ttk.Frame] = {}
        for category in self._TAB_ORDER:
            frame = ttk.Frame(notebook, padding=10)
            frame.columnconfigure(1, weight=1)
            notebook.add(frame, text=category)
            self._tab_frames[category] = frame
        help_frame = ttk.Frame(notebook, padding=10)
        notebook.add(help_frame, text="Help / About")

        self._next_row = {category: 0 for category in self._TAB_ORDER}
        self._build_passage_controls()
        self._build_translation_catalog_controls()
        for spec in SETTING_SPECS:
            if spec.key in {"translation languages", "generate random verses"}:
                continue
            self._build_setting_control(spec)
        self._build_help(help_frame)

        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=1)
        ttk.Label(preview, text="Preview", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self._preview_label = tk.Label(
            preview,
            text="Generate a preview to see the full-resolution PNG here.",
            background="#252525",
            foreground="#F0F0F0",
            anchor="center",
        )
        self._preview_label.grid(row=1, column=0, sticky="nsew")
        self._preview_label.bind("<Configure>", self._schedule_preview_resize)
        self._preview_info_var = tk.StringVar(value="No preview yet")
        ttk.Label(preview, textvariable=self._preview_info_var).grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )

        actions = ttk.Frame(self.root, padding=(8, 4, 8, 2))
        actions.grid(row=1, column=0, sticky="ew")
        self._refresh_button = ttk.Button(
            actions, text="Generate / Refresh", command=self.generate_preview
        )
        self._refresh_button.grid(row=0, column=0, padx=(0, 5))
        self._save_button = ttk.Button(
            actions, text="Save PNG…", command=self.save_preview
        )
        self._save_button.grid(row=0, column=1, padx=5)
        self._open_button = ttk.Button(
            actions, text="Open Saved", command=self.open_saved
        )
        self._open_button.grid(row=0, column=2, padx=5)
        ttk.Checkbutton(
            actions,
            text="Open after save",
            variable=self._open_after_save_var,
        ).grid(row=0, column=3, padx=(8, 5))
        ttk.Combobox(
            actions,
            textvariable=self._publish_target_var,
            values=(PublishTarget.POST.value, PublishTarget.STORY.value),
            state="readonly",
            width=7,
        ).grid(row=0, column=4, padx=(12, 3))
        self._publish_button = ttk.Button(
            actions, text="Publish…", command=self.publish_saved
        )
        self._publish_button.grid(row=0, column=5, padx=3)
        self._cancel_button = ttk.Button(
            actions, text="Cancel", command=self.cancel_operation
        )
        self._cancel_button.grid(row=0, column=6, padx=(12, 3))
        ttk.Button(actions, text="Close", command=self.close).grid(
            row=0, column=7, padx=(3, 0)
        )
        ttk.Button(
            actions, text="Caption Studio…", command=self.open_caption_studio
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))

        status = ttk.Label(
            self.root,
            textvariable=self._status_var,
            anchor="w",
            wraplength=1050,
            padding=(10, 4, 10, 8),
        )
        status.grid(row=2, column=0, sticky="ew")

    def _build_passage_controls(self) -> None:
        frame = self._tab_frames["Passage & Output"]
        passage = ttk.LabelFrame(frame, text="Passage", padding=8)
        passage.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        passage.columnconfigure(1, weight=1)
        ttk.Label(passage, text="Chapter").grid(row=0, column=0, sticky="w")
        self._chapter_combo = ttk.Combobox(
            passage,
            textvariable=self._chapter_var,
            state="readonly",
        )
        self._chapter_combo.grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0)
        )
        ttk.Label(passage, text="Starting verse").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Spinbox(
            passage,
            from_=1,
            to=999,
            textvariable=self._starting_verse_var,
            width=8,
        ).grid(row=1, column=1, sticky="w", padx=(8, 16), pady=(8, 0))
        ttk.Label(passage, text="Ending verse").grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Spinbox(
            passage,
            from_=1,
            to=999,
            textvariable=self._ending_verse_var,
            width=8,
        ).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Checkbutton(
            passage,
            text="Choose a short random passage",
            variable=self._variables["generate random verses"],
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Label(
            passage,
            textvariable=self._passage_error_var,
            foreground="#B00020",
            wraplength=500,
        ).grid(row=3, column=0, columnspan=4, sticky="w")
        config_actions = ttk.Frame(frame)
        config_actions.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 5))
        ttk.Button(config_actions, text="Load config…", command=self.load_config).grid(
            row=0, column=0, padx=(0, 5)
        )
        ttk.Button(config_actions, text="Save config…", command=self.save_config).grid(
            row=0, column=1
        )
        self._next_row["Passage & Output"] = 2

    def _build_translation_catalog_controls(self) -> None:
        frame = self._tab_frames["Translations"]
        translation_limit = int(
            SETTING_SPEC_BY_KEY["translation languages"].maximum or 3
        )
        frame.columnconfigure(4, weight=1)
        catalog = ttk.LabelFrame(frame, text="Exact translation resources", padding=8)
        catalog.grid(row=0, column=0, columnspan=6, sticky="nsew", pady=(0, 8))
        catalog.columnconfigure(0, weight=1)
        catalog.columnconfigure(2, weight=1)
        ttk.Label(
            catalog,
            text="Available catalog",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            catalog,
            text=f"Selected (ordered, maximum {translation_limit})",
        ).grid(row=0, column=2, sticky="w")
        available_frame = ttk.Frame(catalog)
        available_frame.grid(row=1, column=0, sticky="nsew", pady=(5, 5))
        available_frame.columnconfigure(0, weight=1)
        available_frame.rowconfigure(0, weight=1)
        self._translation_list = tk.Listbox(
            available_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            height=6,
        )
        scrollbar = ttk.Scrollbar(
            available_frame,
            orient=tk.VERTICAL,
            command=self._translation_list.yview,
        )
        horizontal_scrollbar = ttk.Scrollbar(
            available_frame,
            orient=tk.HORIZONTAL,
            command=self._translation_list.xview,
        )
        self._translation_list.configure(
            xscrollcommand=horizontal_scrollbar.set,
            yscrollcommand=scrollbar.set,
        )
        self._translation_list.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

        order_actions = ttk.Frame(catalog)
        order_actions.grid(row=1, column=1, padx=7, pady=5)
        ttk.Button(
            order_actions,
            text="Add →",
            command=self._add_selected_translations,
            width=10,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            order_actions,
            text="Remove",
            command=self._remove_selected_translations,
            width=10,
        ).grid(row=1, column=0, sticky="ew", pady=(5, 0))
        ttk.Button(
            order_actions,
            text="Move up",
            command=partial(self._move_selected_translation, -1),
            width=10,
        ).grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(
            order_actions,
            text="Move down",
            command=partial(self._move_selected_translation, 1),
            width=10,
        ).grid(row=3, column=0, sticky="ew", pady=(5, 0))

        selected_frame = ttk.Frame(catalog)
        selected_frame.grid(row=1, column=2, sticky="nsew", pady=(5, 5))
        selected_frame.columnconfigure(0, weight=1)
        selected_frame.rowconfigure(0, weight=1)
        self._selected_translation_list = tk.Listbox(
            selected_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            height=6,
        )
        selected_scrollbar = ttk.Scrollbar(
            selected_frame,
            orient=tk.VERTICAL,
            command=self._selected_translation_list.yview,
        )
        selected_horizontal_scrollbar = ttk.Scrollbar(
            selected_frame,
            orient=tk.HORIZONTAL,
            command=self._selected_translation_list.xview,
        )
        self._selected_translation_list.configure(
            xscrollcommand=selected_horizontal_scrollbar.set,
            yscrollcommand=selected_scrollbar.set,
        )
        self._selected_translation_list.grid(row=0, column=0, sticky="nsew")
        selected_scrollbar.grid(row=0, column=1, sticky="ns")
        selected_horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

        self._catalog_button = ttk.Button(
            catalog, text="Refresh QuranEnc catalog", command=self.refresh_catalog
        )
        self._catalog_button.grid(row=2, column=0, sticky="w")
        font_row = ttk.Frame(catalog)
        font_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        font_row.columnconfigure(1, weight=1)
        ttk.Label(font_row, text="Optional common font for selected resources").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(font_row, textvariable=self._translation_font_var).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(
            font_row,
            text="Browse…",
            command=lambda: self._browse_file(
                self._translation_font_var,
                (("Font files", "*.ttf *.otf"), ("All files", "*.*")),
            ),
        ).grid(row=0, column=2)
        error = ttk.Label(catalog, foreground="#B00020", wraplength=500)
        error.grid(row=4, column=0, columnspan=3, sticky="w")
        self._field_errors["translation languages"] = error
        self._translation_setting_index = 0

    def _build_setting_control(self, spec: SettingSpec) -> None:
        frame = self._tab_frames[spec.category]
        if spec.category == "Translations":
            index = self._translation_setting_index
            self._translation_setting_index += 1
            row = 1 + (index // 2) * 2
            column = (index % 2) * 3
        else:
            row = self._next_row[spec.category]
            self._next_row[spec.category] += 2
            column = 0
        ttk.Label(frame, text=spec.label).grid(
            row=row, column=column, sticky="w", padx=(0, 8), pady=(3, 0)
        )
        variable = self._variables[spec.key]
        if spec.value_type == "boolean":
            widget: Any = ttk.Checkbutton(frame, variable=variable)
        elif spec.value_type == "integer":
            widget = ttk.Spinbox(
                frame,
                from_=spec.minimum if spec.minimum is not None else -10000,
                to=spec.maximum if spec.maximum is not None else 10000,
                textvariable=variable,
                width=10,
            )
        else:
            widget = ttk.Entry(frame, textvariable=variable)
        widget.grid(row=row, column=column + 1, sticky="ew", pady=(3, 0))

        button: Any
        if spec.path_semantics == "directory":
            button = ttk.Button(
                frame,
                text="Browse…",
                command=partial(self._browse_directory, variable),
            )
        elif spec.path_semantics == "optional-file":
            button = ttk.Button(
                frame,
                text="Browse…",
                command=partial(
                    self._browse_file,
                    variable,
                    (
                        ("Images", "*.png *.jpg *.jpeg *.webp *.svg"),
                        ("All files", "*.*"),
                    ),
                ),
            )
        elif spec.path_semantics == "font-file":
            button = ttk.Button(
                frame,
                text="Browse…",
                command=partial(
                    self._browse_file,
                    variable,
                    (("Font files", "*.ttf *.otf"), ("All files", "*.*")),
                ),
            )
        elif spec.value_type == "color":
            button = ttk.Button(
                frame,
                text="Pick…",
                command=partial(self._choose_color, variable),
            )
        else:
            button = ttk.Label(frame, text="")
        button.grid(
            row=row,
            column=column + 2,
            sticky="w",
            padx=(6, 10 if spec.category == "Translations" else 0),
            pady=(3, 0),
        )
        error = ttk.Label(
            frame,
            foreground="#B00020",
            wraplength=230 if spec.category == "Translations" else 480,
        )
        error.grid(row=row + 1, column=column + 1, columnspan=2, sticky="w")
        self._field_errors[spec.key] = error

    def _build_help(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, wrap="word", padx=8, pady=8)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        introduction = (
            "Quran Image Generator\n\n"
            "Choose a chapter and verse range, then use Generate / Refresh. "
            "Random mode chooses one to five valid verses. The displayed image is "
            "scaled only for the window; Save PNG copies the exact full-resolution "
            "preview bytes. Save before Open or Publish.\n\n"
            "Content sources\n"
            "Arabic text and chapter metadata are bundled from the Tanzil Project, "
            "so Arabic-only generation works offline and needs no account or "
            "secrets. Optional translations come from QuranEnc and require network "
            "access. Exact keys identify a translation reliably.\n\n"
            "Common errors\n"
            "Check that the range fits the selected chapter, paths exist, text fits "
            "the canvas, ImageMagick is installed, and network access is available "
            "when translations are selected. Generated files use the Output directory unless you "
            "choose another path in the Save dialog. Instagram credentials likewise "
            "stay in QIG_INSTAGRAM_USERNAME and QIG_INSTAGRAM_PASSWORD.\n\n"
            "Settings reference\n\n"
        )
        text.insert("1.0", introduction + settings_help_text())
        text.configure(state="disabled")
        links = ttk.Frame(frame)
        links.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        readme = ttk.Label(
            links, text="Full README", foreground="#0057B8", cursor="hand2"
        )
        readme.grid(row=0, column=0, padx=(0, 16))
        readme.bind("<Button-1>", lambda _event: webbrowser.open(README_URL))

    def _install_traces(self) -> None:
        for key, variable in self._variables.items():
            variable.trace_add(
                "write",
                lambda *_args, selected_key=key: self._on_form_changed(selected_key),
            )
        for variable in (
            self._chapter_var,
            self._starting_verse_var,
            self._ending_verse_var,
        ):
            variable.trace_add("write", lambda *_args: self._on_passage_changed())
        self._translation_font_var.trace_add(
            "write", lambda *_args: self._on_translation_font_changed()
        )

    def _browse_directory(self, variable: Any) -> None:
        selected = filedialog.askdirectory(parent=self.root, mustexist=False)
        if selected:
            variable.set(selected)

    def _browse_file(self, variable: Any, filetypes: Any) -> None:
        selected = filedialog.askopenfilename(parent=self.root, filetypes=filetypes)
        if selected:
            variable.set(selected)

    def _choose_color(self, variable: Any) -> None:
        candidate = str(variable.get()).strip()
        initial = (
            candidate
            if len(candidate) == 7
            and candidate.startswith("#")
            and all(
                character in "0123456789abcdefABCDEF" for character in candidate[1:]
            )
            else "#000000"
        )
        try:
            _rgb, selected = colorchooser.askcolor(
                color=initial,
                parent=self.root,
            )
        except tk.TclError:
            self._status_var.set(
                "The color picker could not open. Enter a color as #RRGGBB."
            )
            return
        if selected:
            variable.set(selected.upper())

    def _on_form_changed(self, _key: str) -> None:
        if self._loading_form:
            return
        self._invalidate_preview()

    def _on_passage_changed(self) -> None:
        if not self._loading_form:
            self._invalidate_preview()

    def _on_translation_font_changed(self) -> None:
        if not self._loading_form:
            self._translation_font_dirty = True
            self._invalidate_preview()

    def _invalidate_preview(self) -> None:
        had_preview = self._gate.preview_is_current
        self._gate.mark_changed()
        active = self._gate.active
        if active is not None and active.kind in {"preview", "save"}:
            self._worker.cancel()
        if had_preview:
            self._status_var.set("Settings changed. Refresh the preview before saving.")
            self._preview_info_var.set("Preview is out of date")
        self._update_actions()

    def _selected_translation_entries(self) -> list[Any]:
        entries = [dict(entry) for entry in self._translation_entries]
        if not self._translation_font_dirty:
            return entries
        font = self._translation_font_var.get().strip()
        for entry in entries:
            if font:
                entry["font"] = font
            else:
                entry.pop("font", None)
        return entries

    def _materialize_translation_font(self) -> None:
        self._translation_entries = self._selected_translation_entries()
        self._translation_font_dirty = False

    def _refresh_selected_translation_list(self) -> None:
        self._selected_translation_list.delete(0, tk.END)
        for entry in self._translation_entries:
            self._selected_translation_list.insert(
                tk.END,
                translation_entry_label(entry, self._translation_resources),
            )

    def _add_selected_translations(self) -> None:
        self._materialize_translation_font()
        translation_limit = int(
            SETTING_SPEC_BY_KEY["translation languages"].maximum or 3
        )
        selected = tuple(int(index) for index in self._translation_list.curselection())
        existing_ids = {
            resource.resource_id
            for entry in self._translation_entries
            if (
                resource := matching_translation_resource(
                    entry, self._translation_resources
                )
            )
            is not None
        }
        added_indexes: list[int] = []
        for index in selected:
            resource = self._translation_resources[index]
            if resource.resource_id in existing_ids:
                continue
            if len(self._translation_entries) >= translation_limit:
                self._status_var.set(
                    f"Select at most {translation_limit} translation resources."
                )
                break
            entry: dict[str, Any] = {"key": resource.resource_id}
            font = self._translation_font_var.get().strip()
            if font:
                entry["font"] = font
            self._translation_entries.append(entry)
            existing_ids.add(resource.resource_id)
            added_indexes.append(len(self._translation_entries) - 1)
        if not added_indexes:
            return
        self._refresh_selected_translation_list()
        self._selected_translation_list.selection_clear(0, tk.END)
        for index in added_indexes:
            self._selected_translation_list.selection_set(index)
        self._invalidate_preview()

    def _remove_selected_translations(self) -> None:
        self._materialize_translation_font()
        selected = tuple(
            int(index) for index in self._selected_translation_list.curselection()
        )
        if not selected:
            return
        for index in reversed(selected):
            del self._translation_entries[index]
        self._refresh_selected_translation_list()
        self._invalidate_preview()

    def _move_selected_translation(self, offset: int) -> None:
        self._materialize_translation_font()
        selected = tuple(
            int(index) for index in self._selected_translation_list.curselection()
        )
        if len(selected) != 1:
            self._status_var.set("Select one ordered translation to move.")
            return
        current = selected[0]
        target = current + offset
        if target < 0 or target >= len(self._translation_entries):
            return
        self._translation_entries[current], self._translation_entries[target] = (
            self._translation_entries[target],
            self._translation_entries[current],
        )
        self._refresh_selected_translation_list()
        self._selected_translation_list.selection_set(target)
        self._invalidate_preview()

    def _collect_mapping(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in SETTING_SPECS:
            if spec.value_type == "translations":
                values[spec.key] = self._selected_translation_entries()
            else:
                values[spec.key] = self._variables[spec.key].get()
        return values

    def _clear_errors(self) -> None:
        self._passage_error_var.set("")
        for label in self._field_errors.values():
            label.configure(text="")

    def _validate_settings(self) -> Settings | None:
        self._clear_errors()
        try:
            return settings_from_mapping(
                self._collect_mapping(),
                source_path=self._current_config_path,
                create_output_dir=False,
            )
        except SettingsValidationError as error:
            grouped: dict[str, list[str]] = {}
            for issue in error.issues:
                field = issue.field.split("[", 1)[0]
                grouped.setdefault(field, []).append(issue.message)
            for field, messages in grouped.items():
                label = self._field_errors.get(field)
                if label is not None:
                    label.configure(text="; ".join(messages))
            self._status_var.set("Fix the highlighted settings before continuing.")
            return None

    def _apply_settings(self, settings: Settings, *, mark_changed: bool = True) -> None:
        mapping = settings_to_mapping(
            settings,
            destination_path=settings.source_path,
        )
        previous_loading = self._loading_form
        self._loading_form = True
        try:
            for spec in SETTING_SPECS:
                if spec.value_type == "translations":
                    continue
                self._variables[spec.key].set(mapping[spec.key])
            raw_entries = mapping["translation languages"]
            self._translation_entries = (
                list(raw_entries) if isinstance(raw_entries, list) else []
            )
            if self._translation_resources:
                self._translation_entries = normalize_translation_entries(
                    self._translation_entries,
                    self._translation_resources,
                )
            fonts = {
                str(entry.get("font", ""))
                for entry in self._translation_entries
                if isinstance(entry, dict) and entry.get("font")
            }
            self._translation_font_var.set(fonts.pop() if len(fonts) == 1 else "")
            self._translation_font_dirty = False
            self._refresh_selected_translation_list()
            self._settings = settings
        finally:
            self._loading_form = previous_loading
        if mark_changed:
            self._invalidate_preview()

    def load_config(self) -> None:
        if self._worker.busy:
            self._status_var.set("Cancel or finish the current operation first.")
            return
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Load configuration",
            filetypes=(("YAML files", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            settings = load_settings(selected, create_output_dir=False)
        except SettingsValidationError as error:
            self._status_var.set(str(error))
            return
        self._current_config_path = Path(selected).resolve()
        self._apply_settings(settings)
        self._status_var.set(f"Loaded configuration: {self._current_config_path}")

    def save_config(self) -> None:
        if self._worker.busy:
            self._status_var.set("Cancel or finish the current operation first.")
            return
        settings = self._validate_settings()
        if settings is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save configuration",
            initialdir=str(self._current_config_path.parent),
            initialfile=self._current_config_path.name,
            defaultextension=".yaml",
            filetypes=(("YAML files", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            saved_settings = save_settings(settings, selected)
        except (OSError, SettingsValidationError) as error:
            self._status_var.set(f"Could not save configuration: {error}")
            return
        self._current_config_path = Path(selected).resolve()
        self._apply_settings(saved_settings)
        self._status_var.set(f"Saved configuration: {self._current_config_path}")

    def refresh_catalog(self) -> None:
        if self._workflow is None or self._worker.busy:
            return
        token = self._gate.begin("catalog")
        self._worker.submit(token, self._workflow.load_catalogs)
        self._status_var.set("Loading bundled chapters and translation catalog…")
        self._update_actions()

    def generate_preview(self) -> None:
        if self._workflow is None or self._worker.busy:
            return
        settings = self._validate_settings()
        if settings is None:
            return
        chapter_value: object = self._chapter_var.get()
        selected_chapter = self._chapter_by_label.get(str(chapter_value))
        if selected_chapter is not None:
            chapter_value = selected_chapter.number
        try:
            request = build_generation_request(
                chapter_value,
                self._starting_verse_var.get(),
                self._ending_verse_var.get(),
                random_selection=bool(self._variables["generate random verses"].get()),
                chapters=self._chapters,
                rng=self._rng,
            )
        except FormValidationError as error:
            self._passage_error_var.set(
                "; ".join(f"{item.field}: {item.message}" for item in error.issues)
            )
            self._status_var.set("Fix the passage selection before continuing.")
            return
        token = self._gate.begin("preview")
        snapshot = PreviewSnapshot(token, request, settings)
        workflow = self._workflow
        self._worker.submit(
            token,
            lambda cancel_event: workflow.render_preview(snapshot, cancel_event),
        )
        self._status_var.set("Fetching content and rendering the preview…")
        self._update_actions()

    def save_preview(self) -> None:
        if self._workflow is None or self._worker.busy:
            return
        try:
            preview = self._gate.current_preview()
        except StalePreviewError as error:
            self._status_var.set(str(error))
            return
        suggested = preview.suggested_path
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save full-resolution PNG",
            initialdir=str(suggested.parent),
            initialfile=suggested.name,
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"),),
        )
        if not selected:
            return
        token = self._gate.begin("save")
        workflow = self._workflow
        destination = Path(selected)
        self._worker.submit(
            token,
            lambda cancel_event: workflow.save_preview(
                preview,
                destination,
                cancel_event,
            ),
        )
        if self._open_after_save_var.get():
            self._open_after_jobs.add(token.job_id)
        self._lock_form()
        self._status_var.set("Saving the exact preview bytes…")
        self._update_actions()

    def open_saved(self) -> None:
        try:
            saved = self._gate.current_saved()
            open_output(saved.path)
        except (OSError, StalePreviewError) as error:
            self._status_var.set(str(error))
        else:
            self._status_var.set(f"Opened saved image: {saved.path}")

    def publish_saved(self) -> None:
        if self._workflow is None or self._worker.busy:
            return
        try:
            preview = self._gate.current_preview()
            saved = self._gate.current_saved()
        except StalePreviewError as error:
            self._status_var.set(str(error))
            return
        target = PublishTarget(self._publish_target_var.get())
        if not messagebox.askyesno(
            "Confirm Instagram publishing",
            f"Publish this saved image as an Instagram {target.value}?\n\n{saved.path}",
            parent=self.root,
        ):
            return
        token = self._gate.begin("publish")
        workflow = self._workflow

        def operation(cancel_event: Any) -> Path:
            if cancel_event.is_set():
                raise StalePreviewError("Publishing was cancelled.")
            credentials = resolve_instagram_credentials(allow_prompt=False)
            if cancel_event.is_set():
                raise StalePreviewError("Publishing was cancelled.")
            publisher = InstagramPublisher(credentials)
            workflow.publish_saved(preview, saved, target, publisher)
            # Once the external publish begins it cannot be rolled back.  A late
            # cancellation request must not misreport a completed publish.
            cancel_event.clear()
            return saved.path

        self._worker.submit(token, operation)
        self._lock_form()
        self._status_var.set(f"Publishing saved image as an Instagram {target.value}…")
        self._update_actions()

    def cancel_operation(self) -> None:
        if self._worker.busy:
            self._worker.cancel()
            self._status_var.set("Cancelling after the current bounded step…")

    def _poll_worker(self) -> None:
        self._poll_after_id = None
        if self._closing:
            return
        for result in self._worker.poll():
            self._handle_worker_result(result)
        self._update_actions()
        self._poll_after_id = self.root.after(100, self._poll_worker)

    def _handle_worker_result(self, result: WorkerResult) -> None:
        should_open = result.token.job_id in self._open_after_jobs
        self._open_after_jobs.discard(result.token.job_id)
        if result.token.kind in {"save", "publish"}:
            self._unlock_form()
        if result.token.kind == "catalog":
            matched = self._gate.active == result.token
            self._gate.finish(result.token)
            if not matched:
                return
            if result.cancelled:
                self._status_var.set("Catalog loading cancelled.")
            elif result.message:
                self._status_var.set(result.message)
            elif isinstance(result.value, CatalogSnapshot):
                self._apply_catalog(result.value)
            return

        if result.token.kind == "preview":
            if result.cancelled:
                current = self._gate.finish(result.token)
                if current:
                    self._status_var.set("Preview cancelled.")
                return
            if result.message:
                current = self._gate.finish(result.token)
                if current:
                    self._status_var.set(result.message)
                return
            if isinstance(result.value, PreviewArtifact):
                candidate_is_current = (
                    self._gate.active == result.token
                    and result.token.revision == self._gate.revision
                    and result.value.revision == self._gate.revision
                )
                if not candidate_is_current:
                    self._gate.finish(result.token)
                    PreviewWorkflow.discard_preview(result.value)
                    return
                if not self._display_preview(result.value):
                    self._gate.finish(result.token)
                    PreviewWorkflow.discard_preview(result.value)
                    return
                if self._gate.accept_preview(result.token, result.value):
                    previous = self._shown_preview_artifact
                    if previous is not None and previous.path != result.value.path:
                        PreviewWorkflow.discard_preview(previous)
                    self._shown_preview_artifact = result.value
                    self._status_var.set(
                        "Preview ready. Save it when you are satisfied."
                    )
                else:
                    PreviewWorkflow.discard_preview(result.value)
            return

        current = self._gate.finish(result.token)
        if not current:
            return
        if result.cancelled:
            self._status_var.set("Operation cancelled.")
        elif result.message:
            self._status_var.set(result.message)
        elif result.token.kind == "save" and isinstance(result.value, SavedArtifact):
            try:
                self._gate.mark_saved(result.value)
            except StalePreviewError as error:
                self._status_var.set(str(error))
                return
            self._status_var.set(f"Saved full-resolution image: {result.value.path}")
            if should_open:
                try:
                    open_output(result.value.path)
                except OSError as error:
                    self._status_var.set(f"Saved image, but could not open it: {error}")
        elif result.token.kind == "publish":
            self._status_var.set(f"Published saved image: {result.value}")

    def _apply_catalog(self, snapshot: CatalogSnapshot) -> None:
        current_entries = self._selected_translation_entries()
        had_current_preview = self._gate.preview_is_current
        previous_loading = self._loading_form
        self._loading_form = True
        try:
            self._chapters = snapshot.chapters
            labels = tuple(
                f"{item.number} — {item.name_simple} ({item.verses_count} verses)"
                for item in self._chapters
            )
            self._chapter_by_label = dict(zip(labels, self._chapters, strict=True))
            self._chapter_combo.configure(values=labels)
            if labels and self._chapter_var.get() not in self._chapter_by_label:
                self._chapter_var.set(labels[0])

            self._translation_resources = tuple(
                sorted(
                    snapshot.translations.resources,
                    key=lambda item: (
                        item.language_name.casefold(),
                        item.name.casefold(),
                        item.resource_id.casefold(),
                    ),
                )
            )
            self._translation_list.delete(0, tk.END)
            for resource in self._translation_resources:
                self._translation_list.insert(tk.END, translation_label(resource))
            self._translation_entries = normalize_translation_entries(
                current_entries,
                self._translation_resources,
            )
            fonts = {
                str(entry.get("font", ""))
                for entry in self._translation_entries
                if entry.get("font")
            }
            self._translation_font_var.set(fonts.pop() if len(fonts) == 1 else "")
            self._translation_font_dirty = False
            self._refresh_selected_translation_list()
        finally:
            self._loading_form = previous_loading
        # A catalog refresh can change translation versions or resource identity.
        # Conservatively require a fresh preview even when visible keys survive.
        self._invalidate_preview()
        message = (
            f"Loaded {len(self._chapters)} chapters and "
            f"{len(self._translation_resources)} translations."
        )
        if had_current_preview:
            message += " Refresh the preview before saving."
        if snapshot.warning:
            message += f" {snapshot.warning}"
        self._status_var.set(message)

    def _schedule_preview_resize(self, _event: Any) -> None:
        if self._resize_after_id is not None:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(100, self._redisplay_current_preview)

    def _redisplay_current_preview(self) -> None:
        self._resize_after_id = None
        try:
            preview = self._gate.current_preview()
        except StalePreviewError:
            return
        self._display_preview(preview)

    def _display_preview(self, artifact: PreviewArtifact) -> bool:
        try:
            source = tk.PhotoImage(file=str(artifact.path))
            available_width = max(1, self._preview_label.winfo_width() - 20)
            available_height = max(1, self._preview_label.winfo_height() - 20)
            factor = max(
                1,
                (source.width() + available_width - 1) // available_width,
                (source.height() + available_height - 1) // available_height,
            )
            displayed = source.subsample(factor, factor) if factor > 1 else source
        except tk.TclError:
            self._status_var.set(
                "The PNG was rendered, but this Tk installation could not display it."
            )
            return False
        self._preview_source_image = source
        self._preview_display_image = displayed
        self._preview_label.configure(image=displayed, text="")
        self._preview_info_var.set(
            f"Full resolution: {artifact.settings.resolution.width} × "
            f"{artifact.settings.resolution.height} · display scale 1/{factor}"
        )
        return True

    def _update_actions(self) -> None:
        busy = self._worker.busy
        ready = self._workflow is not None and bool(self._chapters)
        self._refresh_button.configure(
            state=tk.NORMAL if ready and not busy else tk.DISABLED
        )
        self._catalog_button.configure(
            state=tk.NORMAL if self._workflow is not None and not busy else tk.DISABLED
        )
        self._save_button.configure(
            state=tk.NORMAL
            if self._gate.preview_is_current and not busy
            else tk.DISABLED
        )
        saved_ready = self._gate.saved_is_current and not busy
        self._open_button.configure(state=tk.NORMAL if saved_ready else tk.DISABLED)
        self._publish_button.configure(state=tk.NORMAL if saved_ready else tk.DISABLED)
        active = self._gate.active
        cancellable = busy and (active is None or active.kind != "publish")
        self._cancel_button.configure(state=tk.NORMAL if cancellable else tk.DISABLED)

    def _lock_form(self) -> None:
        if self._locked_form_widgets:
            return

        def visit(widget: Any) -> None:
            for child in widget.winfo_children():
                try:
                    state = str(child.cget("state"))
                    child.configure(state=tk.DISABLED)
                except tk.TclError:
                    pass
                else:
                    self._locked_form_widgets.append((child, state))
                visit(child)

        visit(self._notebook)

    def _unlock_form(self) -> None:
        for widget, state in self._locked_form_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        self._locked_form_widgets.clear()

    def open_caption_studio(self) -> None:
        from .caption_gui import CaptionStudio

        if self._caption_studio is not None and not self._caption_studio._closed:
            self._caption_studio.window.lift()
            return
        self._caption_studio = CaptionStudio(tk.Toplevel(self.root))

    def close(self) -> None:
        if self._closing:
            return
        studio = getattr(self, "_caption_studio", None)
        if studio is not None and not studio.close():
            return
        self._closing = True
        for after_id in (
            self._catalog_after_id,
            self._poll_after_id,
            self._resize_after_id,
        ):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._catalog_after_id = None
        self._poll_after_id = None
        self._resize_after_id = None
        self._worker.close()
        self._gate.close()
        if self._workflow is not None:
            self._workflow.close()
        self.root.destroy()


def launch(
    config_path: Path | None = None,
    *,
    captions: bool = False,
    request_path: Path | None = None,
) -> int:
    try:
        root = tk.Tk()
    except tk.TclError:
        print(
            "The desktop GUI could not open a display. Run it from a graphical "
            "Windows or Linux session; the CLI remains available for headless use.",
            file=sys.stderr,
        )
        return 2
    if captions:
        from .caption_gui import CaptionStudio

        try:
            CaptionStudio(root, request_path)
        except (ValueError, OSError) as error:
            print(f"Could not open caption request: {error}", file=sys.stderr)
            root.destroy()
            return 2
    else:
        QuranImageGeneratorApp(root, config_path)
    root.mainloop()
    return 0
