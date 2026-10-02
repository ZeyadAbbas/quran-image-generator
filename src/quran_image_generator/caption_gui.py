"""General native caption/layer editor over the same public rendering contract."""

from __future__ import annotations

import copy
import json
import queue
import tempfile
import threading
import tkinter as tk
from dataclasses import asdict
from functools import partial
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any

from PIL import Image, ImageDraw, ImageTk

from .api import execute_request
from .batching import BatchProgress
from .bindings import TranslationSource, export_bindings, import_bindings
from .caption_editor import (
    ASSET_ROLES,
    LAYER_ROLES,
    STYLE_FIELDS,
    CaptionDocument,
    compose_caption,
    parse_style_value,
)
from .gui_state import JobToken, SingleWorker
from .profiles import export_profile, import_profile
from .references import ReferenceError, SourceSpan
from .snapshots import SnapshotStore, prepare_quranenc_snapshot

ROLE_LABELS = {
    "arabic": "Arabic caption",
    "translation": "Translation caption",
    "arabic_title": "Arabic title",
    "latin_title": "Latin title",
    "logo": "Branding / logo",
    "decorations": "Quotation and number font",
}
CHOICES = {
    "direction": ("rtl", "ltr"),
    "fit": ("wrap", "shrink"),
    "baseline_anchor": ("first", "last"),
    "alignment": ("left", "center", "right"),
    "numeral_system": ("latin", "arabic_indic"),
}
STYLE_HELP = {
    "anchor": "x, y from 0 to 1; text baseline position",
    "region": "left, top, right, bottom from 0 to 1",
    "shadow_offset": "horizontal, vertical offset in reference pixels",
    "font_size": "Sizes scale from a 576-pixel-wide canvas; fractions are allowed",
    "horizontal_scale": "Stretch the complete shaped line; Arabic stays connected",
    "suffix_scale": "Size of the small verse-end number relative to the verse",
    "suffix_offset": "Vertical adjustment of the verse number",
    "quote_open": "Opening glyph; use a separate decoration font when needed",
    "quote_close": "Closing glyph; source Quran text stays unchanged",
    "sha256": "Optional required font fingerprint; updated when selecting an asset",
}


class CaptionStudio:
    """A program-wide editor; no external consumer or creator preset is needed."""

    def __init__(
        self, window: tk.Tk | tk.Toplevel, request_path: Path | None = None
    ) -> None:
        self.window = window
        window.title("Quran Image Generator — Caption Studio")
        window.geometry("1320x850")
        window.minsize(1000, 700)
        window.protocol("WM_DELETE_WINDOW", self._guard(self.close))
        self.document = (
            CaptionDocument.load(request_path) if request_path else CaptionDocument()
        )
        self._worker = SingleWorker()
        self._temporary = tempfile.TemporaryDirectory(prefix="qig-caption-studio-")
        self._revision = 0
        self._job = 0
        self._closed = False
        self._shutdown = threading.Event()
        self._loading = True
        self._response: dict[str, Any] | None = None
        self._response_revision = -1
        self._saved_revision = 0
        self._cue_index = 0
        self._layer = "arabic"
        self._asset_role = "arabic"
        self._photo: ImageTk.PhotoImage | None = None
        self._poll_id: str | None = None
        self._binding_dirty = False
        self._progress: queue.SimpleQueue[tuple[int, int, BatchProgress]] = (
            queue.SimpleQueue()
        )
        self._vars: dict[str, Any] = {}
        self._styles: dict[str, Any] = {}
        self._status = tk.StringVar(
            window, "Ready. Add captions, customize layers, then preview."
        )
        self._build()
        self._fill()
        self._loading = False
        self._poll_id = window.after(100, self._poll)

    def _var(self, name: str, default: Any = "", *, boolean: bool = False) -> Any:
        var = (
            tk.BooleanVar(self.window, default)
            if boolean
            else tk.StringVar(self.window, str(default))
        )
        var.trace_add("write", self._changed)
        if name.startswith("source_") or name in (
            "binding_revision",
            "reviewer",
            "edited",
            "binding_approved",
        ):
            var.trace_add("write", partial(self._binding_field_changed, name))
        if name.startswith("asset_") or name in (
            "width",
            "height",
            "titles",
            "quotations",
            "verse_numbers",
        ):
            var.trace_add("write", self._style_changed)
        self._vars[name] = var
        return var

    def _changed(self, *_args: Any) -> None:
        if not self._loading:
            self._revision += 1
            self._save_png.configure(state="disabled")
            self._preview.configure(
                image="", text="Refresh preview for current settings"
            )
            self._status.set(
                "Settings changed. Refresh the preview before saving a PNG."
            )

    def _style_changed(self, *_args: Any) -> None:
        if not self._loading:
            self._loading = True
            self._vars["profile_approval"].set("needs_review")
            self._loading = False

    def _guard(self, function: Any) -> Any:
        def run(*args: Any) -> None:
            try:
                function(*args)
            except (
                ReferenceError,
                ValueError,
                OSError,
                KeyError,
                tk.TclError,
            ) as error:
                self._status.set(str(error))
                messagebox.showerror("Caption settings", str(error), parent=self.window)

        return run

    def _entry(
        self,
        parent: Any,
        row: int,
        label: str,
        name: str,
        default: Any = "",
        *,
        choices: tuple[str, ...] = (),
    ) -> Any:
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=5, pady=4
        )
        var = self._var(name, default)
        control = (
            ttk.Combobox(parent, textvariable=var, values=choices)
            if choices
            else ttk.Entry(parent, textvariable=var)
        )
        control.grid(row=row, column=1, sticky="ew", padx=5, pady=4)
        return control

    def _button(self, parent: Any, label: str, command: Any, **pack: Any) -> ttk.Button:
        button = ttk.Button(parent, text=label, command=self._guard(command))
        button.pack(side="left", padx=3, pady=3, **pack)
        return button

    def _build(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self.window, padding=6)
        toolbar.grid(row=0, column=0, sticky="ew")
        for index, (label, command) in enumerate(
            (
                ("New", self.new),
                ("Open request…", self.open_request),
                ("Save request…", self.save_request),
                ("Check setup", lambda: self._start("preflight")),
                ("Check fit", lambda: self._start("layout")),
                ("Preview", lambda: self._start("preview")),
                ("Export layers", lambda: self._start("export")),
            )
        ):
            ttk.Button(toolbar, text=label, command=self._guard(command)).grid(
                row=index // 4, column=index % 4, padx=3, pady=3, sticky="ew"
            )
        self._save_png = ttk.Button(
            toolbar, text="Save combined PNG…", command=self._guard(self.save_png)
        )
        self._save_png.grid(row=1, column=3, padx=3, pady=3, sticky="ew")
        self._save_png.configure(state="disabled")
        ttk.Button(toolbar, text="Cancel", command=self._worker.cancel).grid(
            row=0, column=4, padx=3
        )
        paned = ttk.Panedwindow(self.window, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew", padx=6)
        self._tabs = ttk.Notebook(paned)
        paned.add(self._tabs, weight=3)
        self._frames: dict[str, ttk.Frame] = {}
        for title in (
            "Captions",
            "Layers",
            "Fonts & Branding",
            "Translations",
            "Canvas & Export",
            "Help",
        ):
            page = ttk.Frame(self._tabs)
            self._tabs.add(page, text=title)
            if title == "Layers":
                frame = ttk.Frame(page, padding=8)
                frame.pack(fill="both", expand=True)
            else:
                frame = self._scroll_page(page)
            frame.columnconfigure(1, weight=1)
            self._frames[title] = frame
        preview = ttk.Frame(paned, padding=8)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        paned.add(preview, weight=2)
        self._preview = ttk.Label(
            preview, text="Transparent caption preview", anchor="center"
        )
        self._preview.grid(row=0, column=0, sticky="nsew")
        self._preview.bind("<Configure>", lambda _e: self._show_preview())
        self._diagnostics = tk.Text(preview, height=10, wrap="word", state="disabled")
        self._diagnostics.grid(row=1, column=0, sticky="ew", pady=5)
        ttk.Label(
            self.window, textvariable=self._status, wraplength=1250, padding=8
        ).grid(row=2, column=0, sticky="ew")
        self._build_cues()
        self._build_layers()
        self._build_assets()
        self._build_translations()
        self._build_canvas()
        help_text = (
            "Caption Studio is available to every user of Quran Image Generator.\n\n"
            "1. Add whole verses, partial word ranges, or separate basmala. Duplicate a caption to represent a repeat. "
            "Use the up/down controls to keep captions and ranges in the intended order.\n\n"
            "2. Choose a layer and customize its font size, position, region, wrapping, alignment, opacity, color, "
            "outline, shadow, quotation glyphs and small verse numbers. Coordinates use 0–1 fractions of the canvas; "
            "sizes scale from a 576-pixel reference width. Title and branding layers can be reused independently.\n\n"
            "3. Select local fonts, a PNG logo or a symbol-font glyph. Each file has a verified fingerprint, license "
            "and attribution. Missing or changed assets fail visibly; no substitute logo is invented.\n\n"
            "4. Import or author phrase translations. Bind each caption to its exact ordered Arabic ranges. "
            "Keep the source wording, edited wording and review status distinct. Required unreviewed English fails; "
            "review mode permits an Arabic-only preview. A whole-verse download is source material, not a phrase binding.\n\n"
            "5. Check fit or preview. Save the full request for another user or program, export transparent layers "
            "with their placement manifest, or save a combined PNG. A checkerboard/background helps inspect alpha "
            "and is not included in saved PNGs unless you choose that option.\n\n"
            "Rendering uses the same versioned public Python/JSON contract. No consumer-specific preset or "
            "speech/video processing is involved. The existing still-image editor remains available."
        )
        help_label = ttk.Label(
            self._frames["Help"], text=help_text, wraplength=580, justify="left"
        )
        help_label.grid(row=0, column=0, columnspan=2, sticky="nw")

    @staticmethod
    def _scroll_page(page: ttk.Frame) -> ttk.Frame:
        """Keep all controls reachable on smaller displays or enlarged system text."""
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        canvas = tk.Canvas(page, highlightthickness=0)
        vertical = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(page, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        form = ttk.Frame(canvas, padding=8)
        item = canvas.create_window((0, 0), window=form, anchor="nw")

        def resize(_event: Any) -> None:
            canvas.itemconfigure(
                item, width=max(canvas.winfo_width(), form.winfo_reqwidth())
            )
            canvas.configure(scrollregion=canvas.bbox("all"))

        form.bind("<Configure>", resize)
        canvas.bind("<Configure>", resize)
        canvas.bind(
            "<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta / 120), "units")
        )
        return form

    def _build_cues(self) -> None:
        frame = self._frames["Captions"]
        self._cues = ttk.Treeview(frame, columns=("ranges", "english"), height=5)
        self._cues.heading("#0", text="Caption / occurrence")
        self._cues.heading("ranges", text="Chapter:verse words")
        self._cues.heading("english", text="Translation")
        self._cues.column("#0", width=140)
        self._cues.column("ranges", width=210)
        self._cues.column("english", width=90)
        self._cues.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._cues.bind("<<TreeviewSelect>>", self._guard(self._select_cue))
        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, columnspan=2, sticky="w")
        for label, command in (
            ("Add", self._add_cue),
            ("Duplicate", self._duplicate),
            ("Remove", self._remove_cue),
            ("Up", lambda: self._move_cue(-1)),
            ("Down", lambda: self._move_cue(1)),
        ):
            self._button(buttons, label, command)
        self._entry(frame, 2, "Caption ID", "cue_id")
        self._entry(
            frame,
            3,
            "English policy",
            "translation_policy",
            choices=("none", "review", "required"),
        )
        self._binding_combo = self._entry(
            frame, 4, "Phrase binding", "binding_id", choices=("",)
        )
        self._binding_combo.bind(
            "<<ComboboxSelected>>", self._guard(self._load_binding)
        )
        self._entry(frame, 5, "Arabic title override", "arabic_title")
        self._entry(frame, 6, "Latin title override", "latin_title")
        self._entry(frame, 7, "Title chapter (for basmala)", "title_surah")
        timing = ttk.Frame(frame)
        timing.grid(row=8, column=0, columnspan=2, sticky="ew")
        for name, label in (
            ("start_seconds", "Start seconds (optional)"),
            ("end_seconds", "End seconds (optional)"),
        ):
            ttk.Label(timing, text=label).pack(side="left", padx=4)
            ttk.Entry(timing, textvariable=self._var(name), width=10).pack(side="left")
        self._spans = ttk.Treeview(
            frame, columns=("surah", "ayah", "first", "last"), show="headings", height=4
        )
        for name, label in (
            ("surah", "Chapter"),
            ("ayah", "Verse"),
            ("first", "First word"),
            ("last", "Last word"),
        ):
            self._spans.heading(name, text=label)
            self._spans.column(name, width=85)
        self._spans.grid(row=9, column=0, columnspan=2, sticky="ew", pady=4)
        self._spans.bind("<<TreeviewSelect>>", self._select_range)
        ranges = ttk.Frame(frame)
        ranges.grid(row=10, column=0, columnspan=2, sticky="ew")
        for name, label, default in (
            ("surah", "Chapter", 1),
            ("ayah", "Verse", 1),
            ("first", "First", 1),
            ("last", "Last", 4),
        ):
            ttk.Label(ranges, text=label).pack(side="left")
            ttk.Entry(
                ranges, textvariable=self._var("range_" + name, default), width=4
            ).pack(side="left", padx=3)
        commands = ttk.Frame(frame)
        commands.grid(row=11, column=0, columnspan=2, sticky="w")
        for label, command in (
            ("Add range", self._add_range),
            ("Replace range", lambda: self._add_range(replace_selected=True)),
            ("Whole verse", self._whole_verse),
            ("Basmala", self._basmala),
            ("Remove range", self._remove_range),
            ("Range up", lambda: self._move_range(-1)),
            ("Range down", lambda: self._move_range(1)),
        ):
            self._button(commands, label, command)
        self._arabic = tk.Text(frame, height=3, wrap="word", state="disabled")
        self._arabic.grid(row=12, column=0, columnspan=2, sticky="ew", pady=4)
        extra = ttk.Frame(frame)
        extra.grid(row=13, column=0, columnspan=2, sticky="w")
        self._button(
            extra,
            "Caption timing / extra metadata…",
            lambda: self._edit_metadata("cue"),
        )
        self._button(extra, "Apply caption", self._apply_cue)

    def _build_layers(self) -> None:
        frame = self._frames["Layers"]
        chooser = ttk.Combobox(
            frame, values=tuple(ROLE_LABELS[r] for r in LAYER_ROLES), state="readonly"
        )
        chooser.set(ROLE_LABELS[self._layer])
        chooser.grid(row=0, column=0, columnspan=2, sticky="ew")
        chooser.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._change_layer(self._role(chooser.get())),
        )
        self._layer_choice = chooser
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, columnspan=2, sticky="nsew")
        scrollbar.grid(row=1, column=2, sticky="ns")
        frame.rowconfigure(1, weight=1)
        form = ttk.Frame(canvas)
        form.columnconfigure(1, weight=1)
        item = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        canvas.bind(
            "<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta / 120), "units")
        )
        for row, (name, spec) in enumerate(STYLE_FIELDS.items()):
            ttk.Label(form, text=name.replace("_", " ").capitalize()).grid(
                row=row * 2, column=0, sticky="w", padx=4, pady=3
            )
            boolean = spec.get("type") == "boolean"
            variable = (
                tk.BooleanVar(self.window) if boolean else tk.StringVar(self.window)
            )
            variable.trace_add("write", self._changed)
            variable.trace_add("write", self._style_changed)
            self._styles[name] = variable
            if boolean:
                control: Any = ttk.Checkbutton(form, variable=variable)
            elif name in CHOICES:
                control = ttk.Combobox(
                    form, textvariable=variable, values=CHOICES[name], state="readonly"
                )
            else:
                control = ttk.Entry(form, textvariable=variable)
            control.grid(row=row * 2, column=1, sticky="ew", padx=4)
            if name.endswith("color") or name == "color":
                ttk.Button(
                    form,
                    text="Choose…",
                    command=self._guard(partial(self._color, variable)),
                ).grid(row=row * 2, column=2)
            if name in STYLE_HELP:
                ttk.Label(form, text=STYLE_HELP[name], wraplength=450).grid(
                    row=row * 2 + 1, column=0, columnspan=3, sticky="w", padx=4
                )
        footer = ttk.Frame(frame)
        footer.grid(row=2, column=0, columnspan=2, sticky="w")
        self._button(footer, "Apply layer", self._apply_layer)
        self._button(footer, "Import styles…", self._import_profile)
        self._button(footer, "Save styles…", self._export_profile)

    def _build_assets(self) -> None:
        frame = self._frames["Fonts & Branding"]
        chooser = ttk.Combobox(
            frame, values=tuple(ROLE_LABELS[r] for r in ASSET_ROLES), state="readonly"
        )
        chooser.set(ROLE_LABELS[self._asset_role])
        chooser.grid(row=0, column=0, columnspan=2, sticky="ew")
        chooser.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._change_asset(self._role(chooser.get())),
        )
        self._asset_choice = chooser
        for row, label, name in (
            (1, "Font or logo file", "asset_path"),
            (2, "Pinned fingerprint", "asset_sha"),
            (3, "License / terms", "asset_license"),
            (4, "Attribution", "asset_attribution"),
            (5, "Branding glyph (blank for PNG)", "asset_glyph"),
        ):
            entry = self._entry(frame, row, label, name)
            if name == "asset_sha":
                entry.configure(state="readonly")
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="w")
        self._button(buttons, "Browse…", self._browse_asset)
        self._button(
            buttons, "Use / pin this file", lambda: self._apply_asset(force=True)
        )
        self._button(buttons, "Use bundled / omit logo", self._clear_asset)
        ttk.Label(
            frame,
            text="Choose any compatible local font for each role. Decorations may use a separate font. Branding accepts a PNG image or a font plus its glyph. Changed files must be explicitly pinned again. Blank font paths use the identified bundled font; blank branding omits it.",
            wraplength=580,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=12)

    def _build_translations(self) -> None:
        frame = self._frames["Translations"]
        buttons = ttk.Frame(frame)
        buttons.grid(row=0, column=0, columnspan=2, sticky="ew")
        for label, command in (
            ("Import bindings…", self._import_bindings),
            ("Save bindings…", self._export_bindings),
            ("Open snapshot…", self._open_snapshot),
            ("Pin snapshot…", self._pin_dataset),
            ("Edit a local copy", self._edit_snapshot),
        ):
            self._button(buttons, label, command)
        details = ttk.Frame(frame)
        details.grid(row=1, column=0, columnspan=2, sticky="ew")
        details.columnconfigure(1, weight=1)
        for row, name in enumerate(
            (
                "provider",
                "resource",
                "version",
                "translator",
                "license",
                "attribution",
                "direction",
            )
        ):
            self._entry(
                details,
                row,
                "Source " + name,
                "source_" + name,
                choices=("ltr", "rtl") if name == "direction" else (),
            )
        self._entry(details, 7, "Binding revision", "binding_revision", "1")
        self._entry(details, 8, "Reviewer", "reviewer")
        ttk.Label(frame, text="Original source wording for this binding").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )
        self._source_text = tk.Text(frame, height=3, wrap="word")
        self._source_text.grid(row=3, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            frame, text="Caption segments (one per line; explicit wrapping)"
        ).grid(row=4, column=0, columnspan=2, sticky="w")
        self._segments = tk.Text(frame, height=3, wrap="word")
        self._segments.grid(row=5, column=0, columnspan=2, sticky="ew")
        for widget in (self._source_text, self._segments):
            widget.bind("<<Modified>>", self._translation_changed)
        flags = ttk.Frame(frame)
        flags.grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            flags,
            text="Caption wording is edited",
            variable=self._var("edited", False, boolean=True),
        ).pack(side="left")
        ttk.Checkbutton(
            flags,
            text="Reviewed and approved",
            variable=self._var("binding_approved", False, boolean=True),
        ).pack(side="left")
        self._button(flags, "Bind to selected caption", self._apply_binding)
        fetch = ttk.Frame(frame)
        fetch.grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Label(fetch, text="QuranEnc key").pack(side="left")
        ttk.Entry(fetch, textvariable=self._var("provider_key"), width=18).pack(
            side="left"
        )
        ttk.Label(fetch, text="Chapters (comma-separated)").pack(side="left")
        ttk.Entry(
            fetch, textvariable=self._var("provider_chapters", "1"), width=8
        ).pack(side="left")
        self._button(fetch, "Download source…", self._download_source)
        self._button(fetch, "Read verse source…", self._read_source)

    def _build_canvas(self) -> None:
        frame = self._frames["Canvas & Export"]
        for row, label, name, default, choices in (
            (0, "Canvas width", "width", 576, ()),
            (1, "Canvas height", "height", 1024, ()),
            (2, "Output folder", "output_directory", "", ()),
            (3, "Asset cache (optional)", "asset_cache_directory", "", ()),
            (4, "Export deadline in seconds", "deadline_seconds", 300, ()),
            (
                5,
                "Failure handling",
                "error_mode",
                "all_or_nothing",
                ("all_or_nothing", "per_cue"),
            ),
            (6, "Request name", "request_id", "captions", ()),
            (7, "Style name", "profile_id", "custom", ()),
            (8, "Style revision", "profile_revision", "1", ()),
            (
                9,
                "Style review",
                "profile_approval",
                "needs_review",
                ("needs_review", "approved"),
            ),
            (
                10,
                "Preview background",
                "preview_background",
                "Checkerboard",
                ("Checkerboard", "Dark", "Light", "Image"),
            ),
            (11, "Preview background image", "preview_image", "", ()),
        ):
            self._entry(frame, row, label, name, default, choices=choices)
        for row, name, label, default in (
            (12, "titles", "Include titles", False),
            (13, "quotations", "Include quotation ornaments", False),
            (14, "verse_numbers", "Include true verse-end numbers", False),
            (15, "cropped", "Crop exported layers and return placement offsets", False),
            (
                16,
                "require_approved_profile",
                "Require approved styles for export",
                False,
            ),
            (
                17,
                "save_background",
                "Include preview background in combined PNG",
                False,
            ),
        ):
            ttk.Checkbutton(
                frame, text=label, variable=self._var(name, default, boolean=True)
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
        buttons = ttk.Frame(frame)
        buttons.grid(row=18, column=0, columnspan=2, sticky="w")
        self._button(
            buttons, "Choose output…", lambda: self._browse_folder("output_directory")
        )
        self._button(
            buttons,
            "Choose cache…",
            lambda: self._browse_folder("asset_cache_directory"),
        )
        self._button(buttons, "Background image…", self._background_file)
        self._button(
            buttons, "Style provenance…", lambda: self._edit_metadata("profile")
        )
        self._button(
            buttons, "Request metadata…", lambda: self._edit_metadata("request")
        )

    def _fill(self) -> None:
        self._loading = True
        data = self.document.data
        for name in ("width", "height"):
            self._vars[name].set(data["canvas"][name])
        for name in (
            "output_directory",
            "asset_cache_directory",
            "deadline_seconds",
            "error_mode",
            "request_id",
            "titles",
            "quotations",
            "verse_numbers",
            "cropped",
            "require_approved_profile",
        ):
            default = (
                False
                if isinstance(self._vars[name], tk.BooleanVar)
                else {"deadline_seconds": 300, "error_mode": "all_or_nothing"}.get(
                    name, ""
                )
            )
            self._vars[name].set(data.get(name, default))
        profile = self.document.profile()
        for name in ("id", "revision", "approval"):
            self._vars["profile_" + name].set(profile[name])
        self._fill_cues()
        self._fill_layer()
        self._fill_asset()
        self._loading = False

    def _fill_cues(self) -> None:
        self._cues.delete(*self._cues.get_children())
        for index, cue in enumerate(self.document.data["cues"]):
            spans = "; ".join(
                f"{s['surah']}:{s['ayah']} {s['word_start']}–{s['word_end']}"
                for s in cue["spans"]
            )
            self._cues.insert(
                "",
                "end",
                iid=str(index),
                text=cue["cue_id"],
                values=(spans, cue.get("translation_policy", "none")),
            )
        self._cue_index = min(self._cue_index, len(self.document.data["cues"]) - 1)
        self._cues.selection_set(str(self._cue_index))
        self._fill_cue()

    def _fill_cue(self) -> None:
        was_loading = self._loading
        self._loading = True
        cue = self.document.data["cues"][self._cue_index]
        for name in ("cue_id", "arabic_title", "latin_title", "title_surah"):
            self._vars[name].set(cue.get(name, ""))
        self._vars["translation_policy"].set(cue.get("translation_policy", "none"))
        self._vars["binding_id"].set(cue.get("translation_binding_id", ""))
        for name in ("start_seconds", "end_seconds"):
            self._vars[name].set(cue.get("metadata", {}).get(name, ""))
        self._spans.delete(*self._spans.get_children())
        for i, span in enumerate(cue["spans"]):
            self._spans.insert(
                "",
                "end",
                iid=str(i),
                values=tuple(
                    span[name] for name in ("surah", "ayah", "word_start", "word_end")
                ),
            )
        try:
            arabic = self.document.arabic(self._cue_index)
        except ReferenceError as error:
            arabic = str(error)
        self._text(self._arabic, arabic, readonly=True)
        self._fill_binding()
        self._loading = was_loading

    def _fill_layer(self) -> None:
        was_loading = self._loading
        self._loading = True
        for name, value in self.document.styles(self._layer).items():
            self._styles[name].set(
                ", ".join(str(v) for v in value)
                if isinstance(value, (list, tuple))
                else value
            )
        self._loading = was_loading

    def _fill_asset(self) -> None:
        was_loading = self._loading
        self._loading = True
        asset = self.document.data.get("assets", {}).get(self._asset_role, {})
        for name in ("path", "sha", "license", "attribution", "glyph"):
            self._vars["asset_" + name].set(
                asset.get("sha256" if name == "sha" else name, "")
            )
        self._loading = was_loading

    @staticmethod
    def _text(widget: tk.Text, text: str, *, readonly: bool = False) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.edit_modified(False)
        if readonly:
            widget.configure(state="disabled")

    def _fill_binding(self) -> None:
        dataset = self.document.dataset()
        self._binding_combo.configure(
            values=tuple(b.binding_id for b in dataset.bindings) if dataset else ()
        )
        pinned = "translation_snapshot" in self.document.data
        if dataset:
            for name, value in asdict(dataset.source).items():
                self._vars["source_" + name].set(value)
        else:
            for name in (
                "provider",
                "resource",
                "version",
                "translator",
                "license",
                "attribution",
                "direction",
            ):
                self._vars["source_" + name].set("ltr" if name == "direction" else "")
        binding_id = self._vars["binding_id"].get()
        binding = (
            next((b for b in dataset.bindings if b.binding_id == binding_id), None)
            if dataset
            else None
        )
        self._text(
            self._source_text, binding.source_text if binding else "", readonly=pinned
        )
        self._text(self._segments, binding.text if binding else "", readonly=pinned)
        for name, value in (
            ("binding_revision", binding.revision if binding else "1"),
            ("reviewer", binding.reviewer if binding else ""),
            ("edited", binding.edited if binding else False),
            (
                "binding_approved",
                binding.review_status == "approved" if binding else False,
            ),
        ):
            self._vars[name].set(value)
        self._binding_dirty = False

    def _load_binding(self, _event: Any = None) -> None:
        was_loading = self._loading
        self._loading = True
        self._fill_binding()
        self._loading = was_loading
        self._changed()

    def _binding_field_changed(self, name: str, *_args: Any) -> None:
        if not self._loading:
            self._binding_dirty = True
            if name != "binding_approved":
                self._loading = True
                self._vars["binding_approved"].set(False)
                self._loading = False

    def _translation_changed(self, event: Any) -> None:
        widget = event.widget
        if widget.edit_modified():
            widget.edit_modified(False)
            if not self._loading:
                self._binding_dirty = True
                self._vars["binding_approved"].set(False)
                self._changed()

    def _apply_cue(self) -> None:
        cue = self.document.data["cues"][self._cue_index]
        cue["cue_id"] = self._vars["cue_id"].get()
        cue["translation_policy"] = self._vars["translation_policy"].get()
        for name in ("arabic_title", "latin_title"):
            cue[name] = self._vars[name].get()
        for name, key in (
            ("binding_id", "translation_binding_id"),
            ("title_surah", "title_surah"),
        ):
            value = self._vars[name].get().strip()
            if value:
                cue[key] = int(value) if key == "title_surah" else value
            else:
                cue.pop(key, None)
        timing = {}
        for name in ("start_seconds", "end_seconds"):
            value = self._vars[name].get().strip()
            if value:
                seconds = float(value)
                json.dumps(seconds, allow_nan=False)
                if seconds < 0:
                    raise ValueError("Caption seconds must be positive or zero")
                timing[name] = seconds
        if len(timing) == 2 and timing["end_seconds"] < timing["start_seconds"]:
            raise ValueError("Caption end must follow its start")
        if timing or "metadata" in cue:
            metadata = cue.setdefault("metadata", {})
            for name in ("start_seconds", "end_seconds"):
                metadata.pop(name, None)
            metadata.update(timing)

    def _commit_cue(self) -> None:
        self._apply_cue()
        if self._binding_dirty:
            self._apply_binding()

    def _apply_layer(self) -> None:
        self.document.set_style(
            self._layer,
            {
                name: parse_style_value(name, var.get())
                for name, var in self._styles.items()
            },
        )

    def _apply_asset(self, *, force: bool = False) -> None:
        path = self._vars["asset_path"].get()
        current = self.document.data.get("assets", {}).get(self._asset_role, {})
        values = {
            "path": path,
            "license": self._vars["asset_license"].get(),
            "attribution": self._vars["asset_attribution"].get(),
            "glyph": self._vars["asset_glyph"].get(),
        }
        if force or any(values[k] != current.get(k, "") for k in values):
            self._apply_layer()
            self.document.set_asset(self._asset_role, **values)
            self._fill_asset()
            self._fill_layer()
            if force:
                self._style_changed()
                self._changed()

    def _apply_binding(self) -> None:
        source = TranslationSource(
            **{
                name: self._vars["source_" + name].get()
                for name in (
                    "provider",
                    "resource",
                    "version",
                    "translator",
                    "license",
                    "attribution",
                    "direction",
                )
            }
        )
        self.document.bind(
            self._cue_index,
            source,
            binding_id=self._vars["binding_id"].get(),
            revision=self._vars["binding_revision"].get(),
            source_text=self._source_text.get("1.0", "end-1c"),
            segments=tuple(self._segments.get("1.0", "end-1c").splitlines()),
            approved=self._vars["binding_approved"].get(),
            reviewer=self._vars["reviewer"].get(),
            edited=self._vars["edited"].get(),
        )
        self._binding_dirty = False
        self._changed()

    def _collect(self) -> None:
        original = copy.deepcopy(self.document.data)
        binding_dirty = self._binding_dirty
        try:
            self._collect_fields()
        except (ReferenceError, ValueError, OSError):
            self.document.data = original
            self._binding_dirty = binding_dirty
            raise

    def _collect_fields(self) -> None:
        self._commit_cue()
        self._apply_layer()
        self._apply_asset()
        data = self.document.data
        data["canvas"] = {
            name: int(self._vars[name].get()) for name in ("width", "height")
        }
        for name in (
            "request_id",
            "error_mode",
            "titles",
            "quotations",
            "verse_numbers",
            "cropped",
            "require_approved_profile",
        ):
            data[name] = self._vars[name].get()
        data["deadline_seconds"] = float(self._vars["deadline_seconds"].get())
        for name in ("output_directory", "asset_cache_directory"):
            value = self._vars[name].get().strip()
            if value:
                data[name] = str(self.document.resolve(value))
            else:
                data.pop(name, None)
        profile = self.document.profile()
        for name in ("id", "revision", "approval"):
            profile[name] = self._vars["profile_" + name].get()
        self.document.request()

    def _select_cue(self, _event: Any = None) -> None:
        selection = self._cues.selection()
        if not selection or self._loading or int(selection[0]) == self._cue_index:
            return
        self._commit_cue()
        self._cue_index = int(selection[0])
        self._fill_cue()
        self._show_preview()

    def _change_layer(self, role: str) -> None:
        try:
            self._apply_layer()
            self._layer = role
            self._fill_layer()
        except ReferenceError as error:
            self._layer_choice.set(ROLE_LABELS[self._layer])
            messagebox.showerror("Layer settings", str(error), parent=self.window)

    def _change_asset(self, role: str) -> None:
        try:
            self._apply_asset()
            self._asset_role = role
            self._fill_asset()
        except (ReferenceError, OSError) as error:
            self._asset_choice.set(ROLE_LABELS[self._asset_role])
            messagebox.showerror("Font settings", str(error), parent=self.window)

    @staticmethod
    def _role(label: str) -> str:
        return next(role for role, value in ROLE_LABELS.items() if value == label)

    def _add_cue(self) -> None:
        self._commit_cue()
        index = self.document.duplicate_cue(self._cue_index)
        self.document.data["cues"][index] = {
            "cue_id": self.document.data["cues"][index]["cue_id"],
            "spans": [asdict(SourceSpan(1, 1, 1, 4))],
        }
        self._cue_index = index
        self._fill_cues()
        self._changed()

    def _duplicate(self) -> None:
        self._collect()
        self._cue_index = self.document.duplicate_cue(self._cue_index)
        self._fill_cues()
        self._changed()

    def _remove_cue(self) -> None:
        if len(self.document.data["cues"]) == 1:
            raise ValueError("Keep at least one caption")
        self.document.data["cues"].pop(self._cue_index)
        self._fill_cues()
        self._changed()

    def _move_cue(self, direction: int) -> None:
        self._commit_cue()
        cues = self.document.data["cues"]
        target = self._cue_index + direction
        if 0 <= target < len(cues):
            cues.insert(target, cues.pop(self._cue_index))
            self._cue_index = target
            self._fill_cues()
            self._changed()

    def _select_range(self, _event: Any = None) -> None:
        selection = self._spans.selection()
        if selection:
            span = self.document.data["cues"][self._cue_index]["spans"][
                int(selection[0])
            ]
            was_loading = self._loading
            self._loading = True
            for name, key in (
                ("surah", "surah"),
                ("ayah", "ayah"),
                ("first", "word_start"),
                ("last", "word_end"),
            ):
                self._vars["range_" + name].set(span[key])
            self._loading = was_loading

    def _add_range(self, *, replace_selected: bool = False) -> None:
        span = SourceSpan(
            *(
                int(self._vars["range_" + name].get())
                for name in ("surah", "ayah", "first", "last")
            )
        )
        self._commit_cue()
        if replace_selected:
            selection = self._spans.selection()
            index = int(selection[0]) if selection else 0
            candidate = list(self.document.spans(self._cue_index))
            candidate[index] = span
            from .excerpts import ExcerptRequest, select_excerpt

            select_excerpt(ExcerptRequest("selection", tuple(candidate)))
            self.document.data["cues"][self._cue_index]["spans"] = [
                asdict(s) for s in candidate
            ]
        else:
            self.document.add_span(self._cue_index, span)
        self._fill_cues()
        self._changed()

    def _whole_verse(self) -> None:
        surah, ayah = (
            int(self._vars["range_" + name].get()) for name in ("surah", "ayah")
        )
        self._vars["range_first"].set(1)
        self._vars["range_last"].set(self.document.word_count(surah, ayah))
        self._add_range()

    def _basmala(self) -> None:
        for name, value in (("surah", 0), ("ayah", 0), ("first", 1), ("last", 4)):
            self._vars["range_" + name].set(value)
        self._add_range()

    def _remove_range(self) -> None:
        self._commit_cue()
        selection = self._spans.selection()
        spans = self.document.data["cues"][self._cue_index]["spans"]
        if selection and len(spans) > 1:
            spans.pop(int(selection[0]))
            self._fill_cue()
            self._changed()

    def _move_range(self, direction: int) -> None:
        self._commit_cue()
        selection = self._spans.selection()
        if selection:
            index = int(selection[0])
            spans = self.document.data["cues"][self._cue_index]["spans"]
            target = index + direction
            if 0 <= target < len(spans):
                spans.insert(target, spans.pop(index))
                self._fill_cue()
                self._spans.selection_set(str(target))
                self._changed()

    def _browse_asset(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window,
            filetypes=[("Fonts and logos", "*.ttf *.otf *.png"), ("All files", "*")],
        )
        if path:
            self._vars["asset_path"].set(path)

    def _clear_asset(self) -> None:
        self._apply_layer()
        self.document.set_asset(self._asset_role, "", "", "")
        self._fill_asset()
        self._fill_layer()
        self._style_changed()
        self._changed()

    def _confirm_replace(self) -> bool:
        if self._revision == self._saved_revision:
            return True
        answer = messagebox.askyesnocancel(
            "Save caption request?",
            "Save your changes before replacing this request?",
            parent=self.window,
        )
        if answer is None:
            return False
        return self.save_request() if answer else True

    def _color(self, variable: Any) -> None:
        color = colorchooser.askcolor(
            parent=self.window, color=variable.get() or "#FFFFFF"
        )[1]
        if color:
            variable.set(color)

    def _browse_folder(self, name: str) -> None:
        path = filedialog.askdirectory(parent=self.window)
        if path:
            self._vars[name].set(path)

    def _background_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window, filetypes=[("Images", "*.png *.jpg *.jpeg")]
        )
        if path:
            self._vars["preview_image"].set(path)
            self._vars["preview_background"].set("Image")

    def new(self) -> None:
        if self._worker.busy:
            raise ValueError("Cancel the current operation first")
        if not self._confirm_replace():
            return
        self.document = CaptionDocument()
        self._response = None
        self._cue_index = 0
        self._fill()
        self._changed()
        self._saved_revision = self._revision

    def open_request(self) -> None:
        if self._worker.busy:
            raise ValueError("Cancel the current operation first")
        path = filedialog.askopenfilename(
            parent=self.window, filetypes=[("Caption request", "*.json")]
        )
        if path:
            document = CaptionDocument.load(Path(path))
            if not self._confirm_replace():
                return
            self.document = document
            self._response = None
            self._cue_index = 0
            self._fill()
            self._changed()
            self._saved_revision = self._revision

    def save_request(self) -> bool:
        self._collect()
        path = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".json",
            filetypes=[("Caption request", "*.json")],
        )
        if path:
            self.document.save(Path(path))
            self._saved_revision = self._revision
            self._status.set("Saved complete reusable caption request.")
            return True
        return False

    def _import_profile(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window, filetypes=[("Styles", "*.json")]
        )
        if path:
            self.document.data["profile"] = import_profile(Path(path)).to_dict()
            self._loading = True
            for name in ("id", "revision", "approval"):
                self._vars["profile_" + name].set(self.document.profile()[name])
            self._fill_layer()
            self._loading = False
            self._changed()

    def _export_profile(self) -> None:
        from .profiles import CaptionProfile

        self._collect()
        path = filedialog.asksaveasfilename(
            parent=self.window, defaultextension=".json"
        )
        if path:
            export_profile(
                CaptionProfile.from_dict(self.document.profile()), Path(path)
            )

    def _import_bindings(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window, filetypes=[("Phrase bindings", "*.json")]
        )
        if path:
            self.document.set_dataset(import_bindings(Path(path)))
            self._fill_cue()
            self._changed()

    def _export_bindings(self) -> None:
        self._commit_cue()
        dataset = self.document.dataset()
        if dataset is None:
            raise ValueError("Create or import phrase bindings first")
        path = filedialog.asksaveasfilename(
            parent=self.window, defaultextension=".json"
        )
        if path:
            export_bindings(dataset, Path(path))

    def _open_snapshot(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window, filetypes=[("Pinned phrase snapshot", "*.json")]
        )
        if path:
            file = Path(path)
            self.document.pin_snapshot(file.parent, file.stem)
            self._fill_cue()
            self._changed()

    def _pin_dataset(self) -> None:
        self._commit_cue()
        dataset = self.document.dataset()
        if dataset is None:
            raise ValueError("Create or import phrase bindings first")
        path = filedialog.askdirectory(parent=self.window)
        if path:
            digest = SnapshotStore(Path(path)).import_dataset(dataset)
            self.document.pin_snapshot(Path(path), digest)
            self._fill_cue()
            self._changed()

    def _edit_snapshot(self) -> None:
        dataset = self.document.dataset()
        if dataset:
            self.document.set_dataset(dataset)
            self._fill_cue()
            self._changed()

    def _edit_metadata(self, kind: str) -> None:
        if kind == "cue":
            self._commit_cue()
        container = (
            self.document.profile()
            if kind == "profile"
            else self.document.data["cues"][self._cue_index]
            if kind == "cue"
            else self.document.data
        )
        key = "provenance" if kind == "profile" else "metadata"
        dialog = tk.Toplevel(self.window)
        dialog.title("Optional " + key)
        text = tk.Text(dialog, width=75, height=20)
        text.pack(fill="both", expand=True)
        text.insert(
            "1.0", json.dumps(container.get(key, {}), ensure_ascii=False, indent=2)
        )

        def save() -> None:
            value = json.loads(text.get("1.0", "end-1c"))
            if not isinstance(value, dict):
                raise ValueError("Use a metadata object")
            container[key] = value
            if kind == "cue":
                self._fill_cue()
            dialog.destroy()
            self._changed()

        ttk.Button(dialog, text="Save", command=self._guard(save)).pack(pady=5)

    def _download_source(self) -> None:
        if self._worker.busy:
            raise ValueError("Wait for the current operation")
        directory = filedialog.askdirectory(
            parent=self.window, title="Source snapshot folder"
        )
        if not directory:
            return
        key = self._vars["provider_key"].get()
        chapters = tuple(
            int(v.strip()) for v in self._vars["provider_chapters"].get().split(",")
        )
        license = self._vars["source_license"].get()
        attribution = self._vars["source_attribution"].get()
        self._job += 1
        shutdown = self._shutdown
        temporary = self._temporary

        def download(cancel: Any) -> dict[str, Any]:
            try:
                if cancel.is_set():
                    return {"cancelled": True}
                digest = prepare_quranenc_snapshot(
                    SnapshotStore(Path(directory)),
                    key,
                    chapters,
                    license=license,
                    attribution=attribution,
                )
                return {"source_snapshot": str(Path(directory) / f"{digest}.json")}
            except ReferenceError as error:
                return {"download_error": str(error)}
            finally:
                if shutdown.is_set():
                    temporary.cleanup()

        self._worker.submit(JobToken(self._job, self._revision, "download"), download)
        self._status.set(
            "Downloading selected whole-verse source; phrase review is still required."
        )

    def _read_source(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window, filetypes=[("Whole-verse snapshot", "*.json")]
        )
        if not path:
            return
        file = Path(path)
        payload = SnapshotStore(file.parent).read(file.stem)
        if payload.get("kind") != "whole_ayah_translation":
            raise ValueError("Choose a whole-verse translation source snapshot")
        source = payload["source"]
        values = {
            "provider": source["provider"],
            "resource": source["resource_id"],
            "version": source["version"] + "; snapshot:" + file.stem,
            "translator": source["author"],
            "license": source["license"],
            "attribution": source["attribution"],
            "direction": source["direction"],
        }
        keys = dict.fromkeys(
            f"{s.surah}:{s.ayah}" for s in self.document.spans(self._cue_index)
        )
        text = "\n".join(payload["verses"][key] for key in keys)
        for name, value in values.items():
            self._vars["source_" + name].set(value)
        self._text(self._source_text, text)
        self._text(self._segments, "")
        self._vars["binding_approved"].set(False)
        self._status.set(
            "Whole-verse source loaded. Author the exact phrase segments and review them before binding."
        )
        self._binding_dirty = False

    def _start(self, kind: str) -> None:
        if self._worker.busy:
            raise ValueError("Wait for the current operation or cancel it")
        self._collect()
        payload = self.document.request(
            kind if kind in ("layout", "preflight") else "render_batch"
        ).to_dict()
        if kind == "preview":
            payload["output_directory"] = self._temporary.name
        self._job += 1
        revision = self._revision
        job_id = self._job
        asset_root = self.document.root
        progress_queue = self._progress
        shutdown = self._shutdown
        temporary = self._temporary

        def operation(cancel: Any) -> dict[str, Any]:
            try:
                return execute_request(
                    payload,
                    asset_root=asset_root,
                    cancelled=cancel.is_set,
                    progress=lambda value: progress_queue.put(
                        (job_id, revision, value)
                    ),
                ).to_dict()
            finally:
                if shutdown.is_set():
                    temporary.cleanup()

        self._worker.submit(JobToken(self._job, revision, kind), operation)
        if kind in ("preview", "export"):
            self._response = None
            self._save_png.configure(state="disabled")
            self._preview.configure(image="", text="Rendering current captions…")
        self._status.set(
            "Checking every caption…"
            if kind == "layout"
            else "Rendering caption layers…"
        )

    def _poll(self) -> None:
        if self._closed:
            return
        while not self._progress.empty():
            job_id, revision, progress = self._progress.get_nowait()
            if job_id == self._job and revision == self._revision:
                self._status.set(
                    f"{progress.completed} of {progress.total} captions — {progress.phase}"
                    + (f": {progress.cue_id}" if progress.cue_id else "")
                )
        for item in self._worker.poll():
            if item.cancelled:
                self._status.set("Operation cancelled.")
            elif item.message:
                self._status.set(item.message)
            elif isinstance(item.value, dict):
                result = item.value
                if "source_snapshot" in result:
                    self._status.set(
                        "Source snapshot saved: " + result["source_snapshot"]
                    )
                    continue
                if "download_error" in result:
                    self._status.set(result["download_error"])
                    continue
                if item.token.revision != self._revision:
                    self._status.set(
                        "Settings changed during rendering. Refresh to see the current result."
                    )
                    continue
                lines = ["Result: " + result["status"]]
                if result.get("preflight"):
                    for check, value in result["preflight"]["checks"].items():
                        lines.append(
                            check.replace("_", " ")
                            + ": "
                            + (
                                json.dumps(value, ensure_ascii=False)
                                if isinstance(value, dict)
                                else str(value)
                            )
                        )
                if result.get("error"):
                    lines.append(result["error"]["message"])
                for cue in result.get("cues", []):
                    lines.append(cue["cue_id"] + ": " + cue["status"])
                    if cue.get("error"):
                        lines.append(cue["error"]["message"])
                        if cue["error"].get("details"):
                            lines.append(
                                json.dumps(cue["error"]["details"], ensure_ascii=False)
                            )
                    lines.extend(cue.get("warnings", []))
                    for plan in cue.get("layers", []):
                        lines.append(
                            f"  {ROLE_LABELS[plan['layer']['role']]}: {plan['status']}, size {plan['font_size']}, {len(plan['lines'])} lines, bounds {plan['bounds']}"
                        )
                self._text(self._diagnostics, "\n".join(lines), readonly=True)
                if result.get("assets"):
                    self._response = result
                    self._response_revision = self._revision
                    self._save_png.configure(state="normal")
                    self._show_preview()
                self._status.set(
                    "\n".join(lines[:2])
                    + (
                        " — Saved job: " + result["job_directory"]
                        if item.token.kind == "export" and "job_directory" in result
                        else ""
                    )
                )
        self._poll_id = self.window.after(100, self._poll)

    def _background(self, size: tuple[int, int]) -> Image.Image:
        choice = self._vars["preview_background"].get()
        if choice == "Image":
            with Image.open(str(self._vars["preview_image"].get())) as opened:
                background: Image.Image = opened.convert("RGBA").resize(
                    size, Image.Resampling.LANCZOS
                )
                return background
        color = "#202124" if choice == "Dark" else "#FAFAFA"
        image = Image.new("RGBA", size, color)
        if choice == "Checkerboard":
            draw = ImageDraw.Draw(image)
            for y in range(0, size[1], 24):
                for x in range(0, size[0], 24):
                    if (x // 24 + y // 24) % 2:
                        draw.rectangle((x, y, x + 23, y + 23), fill="#C8C8C8")
        return image

    def _show_preview(self) -> None:
        if self._response is None or self._closed:
            return
        if self._response_revision != self._revision:
            return
        try:
            size = tuple(
                self.document.data["canvas"][name] for name in ("width", "height")
            )
            caption = compose_caption(self._response, self._cue_index, size)
            backdrop = self._background(size)
            backdrop.alpha_composite(caption)
            backdrop.thumbnail(
                (
                    max(1, self._preview.winfo_width() - 8),
                    max(1, self._preview.winfo_height() - 8),
                )
            )
            self._photo = ImageTk.PhotoImage(backdrop, master=self.window)
            self._preview.configure(image=self._photo, text="")
            self._save_png.configure(state="normal")
        except (ReferenceError, OSError, IndexError):
            self._preview.configure(image="", text="No valid preview for this caption")
            self._save_png.configure(state="disabled")

    def save_png(self) -> None:
        if self._response is None or self._response_revision != self._revision:
            raise ValueError("Refresh the current settings before saving")
        path = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
        )
        if path:
            size = tuple(
                self.document.data["canvas"][name] for name in ("width", "height")
            )
            image = compose_caption(self._response, self._cue_index, size)
            if self._vars["save_background"].get():
                background = self._background(size)
                background.alpha_composite(image)
                image = background
            image.save(path, "PNG")
            self._status.set("Saved the full-resolution combined PNG.")

    def close(self, *, discard: bool = False) -> bool:
        if self._closed:
            return True
        if not discard and not self._confirm_replace():
            return False
        self._closed = True
        self._shutdown.set()
        if self._poll_id:
            self.window.after_cancel(self._poll_id)
        busy = self._worker.busy
        self._worker.close()
        if not busy:
            self._temporary.cleanup()
        self.window.destroy()
        return True
