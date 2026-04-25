# music_assistant_provider/

A standalone Music Assistant **metadata provider** — separate from the
`media_art_wrapper` Home Assistant integration that lives next to it in
this repository. The two share a repository for distribution convenience
but are loaded by different runtimes:

| Component                     | Loaded by                                  |
|-------------------------------|--------------------------------------------|
| `custom_components/media_art_wrapper/` | Home Assistant (custom integration) |
| `music_assistant_provider/itunes_metadata/` | Music Assistant server (provider) |

## Contents

```
music_assistant_provider/
└── itunes_metadata/        # MA metadata provider
    ├── __init__.py         # Provider class
    └── manifest.json       # MA provider manifest
```

## What it does

`itunes_metadata` fetches cover art from the public Apple iTunes Search
API (no API key required). Its primary use case is filling in missing
artwork for **radio streams and ICY metadata** where none of the other
Music Assistant metadata providers find a match.

Supported provider features: `ARTIST_METADATA`, `ALBUM_METADATA`,
`TRACK_METADATA`.

## Installation into Music Assistant

This is **not** a Home Assistant integration. To install it into a
Music Assistant server:

1. Copy the `itunes_metadata/` folder into
   `music_assistant/providers/` of your music-assistant/server checkout.
2. Restart the Music Assistant server.
3. In the Music Assistant UI, open **Settings → Providers → Metadata**
   and enable **iTunes Metadata**.

No configuration is required — the provider works out of the box.

## Why ship it from this repo

The provider is the upstream-of-MAW companion: when iTunes-resolvable
metadata reaches a HomePod via Music Assistant, the MAW Home Assistant
integration sees native artwork on the source entity and §2.3 prio 1
of the LASTENHEFT applies (pass-through, no further lookup). Bundling
both lets a user upgrade them in lockstep.

## Status

The Home Assistant integration in this repo will be renamed to
`smart_player` (LASTENHEFT §9). At that point the long-term home of
this provider will be re-evaluated — either keep it bundled here, or
move it to its own repository. See LASTENHEFT §8.3 for the open item.
