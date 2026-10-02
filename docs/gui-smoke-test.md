# Desktop GUI manual smoke test

Use a normal graphical Windows or Linux session. Quran content must work
without any credential setup. Never put Instagram credentials in YAML.

1. Disconnect the network, run `quran-image-generator-gui`, and confirm one
   resizable window opens. The full bundled chapter list and Help / About tab
   must remain available; translation unavailability should be a status warning,
   not a blocking error.
2. Generate an Arabic-only passage from a late chapter while offline. Confirm
   the preview renders, saves, and opens without a content account or secret.
3. Reconnect the network and refresh the translation catalog. Confirm QuranEnc
   translation title, language, version, and exact key are visible. Select a
   chapter, range, and up to three translations.
4. Change representative values on every settings tab. Enter one invalid value
   and confirm its error appears beside that field.
5. Generate a preview. Resize the window and confirm the display scales without
   another render. Change only a color and refresh. Exercise Cancel during a
   slow fetch/render and then generate again.
6. Save the preview. Confirm the saved full-resolution PNG matches it, Open
   Saved opens that file, and editing disables stale save/open/publish actions
   until a fresh preview is generated and saved.
7. Save and reload the config. Confirm values and ordered translation keys
   round-trip. The YAML must contain no runtime catalog object, Instagram
   secret, or machine-specific bundled-font path.
8. If optional Instagram support is configured, choose post or story, click
   Publish, and confirm the explicit target/path prompt. Cancel once, then
   confirm one publish; it must use the current saved PNG only.
9. Close during an in-progress operation. Confirm the window closes promptly
   without another window, traceback, or lingering GUI worker.

## Caption Studio

1. Open **Caption Studio…** from the still-image editor; reopen it and confirm
   the existing window is raised. Also launch `--captions` and `--request`.
2. Offline, add and replace a partial word range, append a whole verse and
   separate basmala, duplicate a caption and reorder both lists. Verify exact
   source Arabic, unique occurrence IDs and optional timing/extra metadata.
3. Visit every layer and customize sizes, anchor/region, direction/alignment,
   fit limits, opacity, outline, shadow, quotation/number glyphs and scaling.
   Switch layers and verify edits persist. Resize to 1000×700 and scroll all pages.
4. Choose each text font, a separate decoration font, a PNG logo and a font-glyph
   logo. Record terms/attribution. Check a missing glyph and a changed fingerprint
   fail visibly; explicitly pin a reviewed changed file to repair it.
5. Author/import phrase bindings with source provenance and original/edited
   wording. Approve with a reviewer, edit wording, and verify approval is revoked.
   Pin an offline snapshot; open it and edit a local copy without changing the pin.
6. With network access, explicitly download a QuranEnc source snapshot and read
   a verse. Verify it fills original source wording and leaves phrase segments
   empty pending authoring/review. Disconnect before export.
7. Check setup/fit, preview, export cropped layers and save a combined transparent
   PNG. Inspect alpha and placement. Include a chosen background only by checking
   that option. A failed caption in a partial batch must not be savable.
8. Save/reload a full request and styles/bindings independently. Replay the same
   request with the machine adapter and compare PNG checksums. Change settings
   during a render, cancel a render, and confirm stale results cannot be saved.
9. Cancel the save-before-close prompt once and verify the editor stays open.
   Close during a render after saving or discarding the request; check prompt
   completion, cancellation and worker shutdown.

CI exercises native controls under Xvfb on Linux and native Tk on Windows, and
also runs an installed Caption Studio smoke outside the source checkout.
