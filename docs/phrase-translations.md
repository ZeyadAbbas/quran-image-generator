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
Validation checks that unedited segments occur in source order in `source_text`,
ignoring whitespace reflow only. Changed wording, punctuation or reordering
requires the explicit edit flag; this is provenance validation, not semantic
approval. Imports enforce the same strict schema as machine requests.
Changed Arabic/source hashes or mapping revisions invalidate a binding. A changed
provider version must be imported as a new dataset; never mutate an export's
pinned dataset. Required English fails on missing, mismatched or unapproved
bindings; explicitly choose Arabic-only or review-required behavior otherwise.

The renderer capability is complete without selecting a default English resource
or inventing a creator translation edition. Test fixtures are authored test
material. Import reviewed wording, source notices and exact spans in the caller's
dataset before production use. A binding ID is selected per cue, so callers may
choose an explicitly authored override while retaining the source text and edit
metadata. Alternative wording uses a new binding ID/revision, not a silent change
to a saved immutable snapshot.

## Immutable offline snapshots

`SnapshotStore(path).import_dataset(dataset)` publishes a content-addressed JSON
snapshot atomically and returns its SHA-256. Pin that ID in a saved caption plan.
`SnapshotStore(path).bindings(id)` only reads and verifies local bytes; it never
updates a version or contacts HTTP. Copy the JSON to another cache to transfer a
permitted dataset. Keep source licenses/attribution with it. Cleanup is explicit:
delete only IDs no saved job references. No automatic expiration is applied.

`prepare_quranenc_snapshot` is an explicit whole-ayah download, separate from
export. It fetches each unique chapter once, checks catalog identity before/after,
retains provider/resource/version/chapter provenance, and pins actual payload
bytes. The default client has 5-second HTTP timeouts and at most two attempts;
the overall 120-second deadline is checked between calls. A caller-supplied client
must supply its own bounded HTTP timeouts. Latest lookup never replaces pinned
content. Whole-ayah snapshots need reviewed phrase bindings before partial export.
Missing/corrupt snapshots and changed provider versions fail explicitly.
