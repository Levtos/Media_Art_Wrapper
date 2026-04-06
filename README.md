# Media Art Wrapper

A Home Assistant custom integration that fetches cover art for any `media_player` entity and exposes it as **Image**, **Camera**, **Media Player wrapper**, and **Sensor** entities.

Designed for use-cases where the source player provides no artwork — most notably internet radio streams, but equally useful for games and TV.

## Providers

| Provider | Use-case | API key |
|---|---|---|
| **iTunes** (Apple Search API) | Music — tracks, singles, albums | None |
| **MusicBrainz + Cover Art Archive** | Music — open-source fallback | None |
| **TV** | TV channel logos, movies & series (iTunes TV, TVMaze, Wikipedia) | None |
| **Battle.net** | Blizzard games: Overwatch, Hearthstone, WoW, Diablo, StarCraft, … | None |
| **Steam** | All Steam games — portrait library artwork (up to 1200 × 1800 px) | None |

Up to **5 providers** can be enabled in priority order. The integration tries each in turn and uses the first successful result.

## Entities

For each configured source player the following entities are created:

| Entity | Type | Description |
|---|---|---|
| `image.<name>_cover` | Image | Cover art, updates on every track change |
| `camera.<name>_cover` | Camera | Same image via camera platform (for Picture Glance cards) |
| `media_player.<name>_cover` | Media Player | Full proxy of the source player with cover art overridden |
| `sensor.<name>_cover_status` | Sensor | `ready` / `not_found` / `idle` + diagnostics attributes |

## Features

- **Provider priority slots** — choose up to 5 providers in order; first match wins
- **Staged title fallback** — tries original title (e.g. `Song (Remix)`) then stripped title (`Song`), then swapped artist/title order (catches stations that transmit them reversed)
- **Artwork size presets** — square (300 – 1000 px) and portrait formats (600 × 900, 1200 × 1800) for game artwork
- **Persistent last cover** — keeps the previous cover visible while the next one loads
- **No-cover fallback** — shows a neutral SVG instead of a broken image
- **Track-keyed caching** — only fetches when `(artist, title, album)` actually changes
- **Config entry options flow** — change providers and artwork size without re-adding the integration

## Installation

### HACS (recommended)

1. HACS → ⋮ → *Custom repositories* → add this repository URL → type **Integration**
2. Install *Media Art Wrapper*
3. Restart Home Assistant

### Manual

Copy `custom_components/media_art_wrapper/` to `<config>/custom_components/media_art_wrapper/` and restart.

## Setup

**Settings → Devices & Services → Add Integration → Media Art Wrapper**

1. Select the source `media_player` entity
2. Choose providers and their priority order
3. Choose artwork dimensions (or use a preset)

## Lovelace

```yaml
type: picture-entity
entity: image.my_player_cover
```

Or for the full media player card with controls:

```yaml
type: media-control
entity: media_player.my_player_cover
```

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.media_art_wrapper: debug
```

The sensor entity (`sensor.*_cover_status`) exposes `provider`, `artwork_url`, `track_key`, and `last_error` as attributes — useful for diagnosing why a cover was not found.

## Known limitations

- Radio streams with very generic or misspelled metadata can still produce wrong matches.
- The TV provider works best for German-speaking public broadcasting channels; other regions may see reduced match rates.
- Battle.net artwork depends on Blizzard's website structure and may break when they redesign their pages.
