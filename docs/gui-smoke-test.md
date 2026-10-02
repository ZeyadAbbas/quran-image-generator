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
