# Session Event Contract - Media, Documents, and Artifacts Note

This note captures the future V1.5/V2 direction for structured media handling.

The session event contract should eventually cover uploads and generated outputs
as first-class session artifacts, not just loose attachments.

Future cases include:

- user-uploaded voice clips;
- user-uploaded documents;
- user-uploaded images;
- tool-generated files;
- media received through Telegram, Web, or Nexus.

These items should be represented in `media.index.json` or an equivalent derived
index, linked to:

- `session_id`;
- `turn_id`;
- `message_id`;
- `work_id` when present;
- `origin_event_id`.

Beyond the original file, the system should be able to persist derived or cached
artifacts such as:

- audio transcripts;
- extracted document text;
- image OCR;
- image summaries;
- document summaries;
- thumbnails;
- processing status;
- references to derived artifacts.

Why this matters:

- avoids repeated reprocessing;
- reduces token usage;
- supports session recovery;
- enables consistent cards and previews;
- prevents the frontend from inferring attachments or derivatives by scanning
  `chat.json`.

This is intentionally out of scope for B4B.
B4B remains focused only on the pure frontend event normalizer.
