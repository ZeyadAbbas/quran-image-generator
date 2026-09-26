# Desktop GUI manual smoke test

Use a normal graphical Windows or Linux session. Keep Quran Foundation and
Instagram credentials in environment variables; never put them in YAML.

1. Run `quran-image-generator-gui`. Confirm one resizable window titled
   **Quran Image Generator** opens and its Help / About tab works. With Quran
   Foundation credentials absent, confirm config/help remain usable and the
   window shows setup guidance instead of crashing.
2. With valid `QF_CLIENT_ID` and `QF_CLIENT_SECRET`, refresh the live catalog.
   Confirm chapter names/bounds and translation name, language, author, and ID
   are visible. Select a chapter, range, and up to three translations.
3. Change representative values on every settings tab, including colors,
   fonts, resolution, spacing, verse-number visibility, and a background.
   Enter one invalid value and confirm its error appears beside that field.
4. Generate a preview. Resize the window and confirm the displayed copy scales
   without another fetch/render. Change only a color and refresh; confirm the
   verse content is reused and the window stays responsive. Exercise Cancel
   during a slow fetch/render and then generate again.
5. Save the preview. Confirm the saved full-resolution PNG matches the preview,
   Open Saved opens that file, and editing any field disables stale save/open/
   publish actions until a fresh preview is generated and saved.
6. Save the config, load it again, and confirm values and ordered translation
   IDs round-trip. Inspect the YAML: no Quran Foundation or Instagram secret,
   access token, runtime catalog object, or machine-specific bundled-font path
   may appear.
7. If the optional Instagram extra and credentials are available, choose post
   or story, click Publish, and confirm the explicit target/path prompt. Cancel
   once, then confirm one publish; it must use the current saved PNG only.
8. Close during an in-progress operation. Confirm the window closes promptly
   without another window, traceback, or lingering non-daemon GUI worker.
