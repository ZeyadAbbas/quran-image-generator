# Reviewed phrase translations

Public `BindingDataset`, `TranslationSource`, `PhraseBinding`, `import_bindings`
and `export_bindings` accept creator datasets without HTTP. Each binding pins
ordered Simple source spans, Uthmani Arabic content hash, mapping revision,
translation source content/hash, revision, ordered English segments, edited
status and reviewer. Separate basmala binds explicitly to 0:0, numbered to 1:1.
Segments may reorder English or represent many Arabic words; no proportional
slicing or model paraphrase is treated as semantic proof. The author must review
negation, clipped phrases and punctuation before setting `approved`.

Caption segments are plain UTF-8 text with explicit line breaks. HTML and null
characters fail; footnotes/commentary must be deliberately excluded or authored
as separately reviewed content. Source text is preserved for provenance. An
edited phrase must set `edited=true`; never label creator edits as verbatim.
Changed Arabic/source hashes or mapping revisions invalidate a binding. A changed
provider version must be imported as a new dataset; never mutate an export's
pinned dataset. Required English fails on missing, mismatched or unapproved
bindings; explicitly choose Arabic-only or review-required behavior otherwise.

The exact creator translation edition remains unconfirmed. Test fixtures are
authored test material, not claims of approved reference provenance. Import the
creator's reviewed wording and license before asserting a reference match.
