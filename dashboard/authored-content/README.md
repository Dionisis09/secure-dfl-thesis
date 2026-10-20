# Dashboard authored content

These are the editable content files from the existing local Data app. They
belong in `src/content/dashboard/` of that app and use its public component
API. They are not a standalone web application. The protected runtime and
app ID are preserved in the local project. `src/publish_extended_campaign.py`
merges checkpoints into its reviewed snapshot and builds the same dashboard.
The portable dashboard is delivered separately as self-contained HTML after
the complete campaign has been verified.
