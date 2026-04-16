# Changelog

## 3.2.0 (2026-04-16)

### Bug Fixes
- OptionsFlow: Fixed double-step bug — artwork and combined steps were shown twice on first submission. Schema now only rebuilds when field visibility actually changes (custom dimensions / custom URL toggle).
- `_fallback_data`: Stale cover from a previous track is no longer shown when the new track's cover lookup fails. Returns empty CoverData instead, allowing the configured fallback mode (service logo / placeholder) to apply.
- Combined Player: Removed duplicate `combined_audio_sources` schema field that caused unpredictable form behaviour.

### New Features
- EPG: Channel classification — public broadcasters (ARD, ZDF, WDR, arte, ÖR regional) trigger full TVMaze + TMDb episode lookups. Private/commercial channels return channel_icon directly without API calls.
- EPG: `fix_epg_encoding()` corrects common EPG encoding artifacts (SS→ß, English "and"→"und").
- EPG: `EPG_TITLE_CORRECTIONS` dictionary covers ARD, ZDF and WDR programme title normalisation.
- TVMaze: When `subtitle_hint` is set, uses `episodesbydate` API for episode-specific cover images.
- TMDb: Added `tv` category support; when `subtitle_hint` is set, searches last 2 seasons for episode still_path.
- Config Flow: Delegate fields (`combined_delegate_1..8`) now always visible for filled source slots.
- `ArtworkQuery`: Added `channel_icon` and `channel_name` fields for channel-aware providers.

### Housekeeping
- Removed `xmltv_url` from UI (kept in storage as reserved field for future EPG v3.2).
- Fixed German strings in `translations/en.json`.
- Config entry version bumped to 6 (migration: remove legacy `delegate_entity`, add `channel_icon`/`channel_name` defaults).
- Manifest version: 3.2.0.

## 3.1.1 (2026-04-14)
- OptionsFlow-Routing und bedingte Feldanzeige bereinigt (kein doppelter Artwork-Step).
- Delegate auf Wrapper-Ebene entfernt; stattdessen pro Combined-Quelle optional steuerbare Entität (`combined_delegate_1..8`).
- TV/Auto: optionaler `epg_sensor` integriert, inkl. Programmtitel-Override und Channel-Icon-Fallback.
- Query-Builder erweitert um Umlaut-Varianten (`title_candidates`) und `subtitle_hint` für TV-Suche.
- Ratio-Mapping/Migration auf neue Presets (`4:3_1600`, `16:9_1920`) aktualisiert.

## 3.1.0 (2026-04-14)
- Config/UI: Conditional Felder im Config- und Options-Flow werden jetzt wirklich ausgeblendet, bis die jeweilige Bedingung erfüllt ist (Artwork + Combined Step).
- Neue Artwork-Presets mit 2K/3K-Defaults und Provider-Abrufe auf höhere Auflösungen angepasst (iTunes/TMDb/IGDB/SteamGridDB).
- Neues optionales `delegate_entity` pro MAW-Instanz: Steuerungs-/Browse-Aufrufe können an einen Delegat-Player weitergeleitet werden, Metadaten/Cover bleiben vom Original-Player.
- Combined Player nutzt MAW-Wrapper als auswählbare Quellen und kann Audio-Targets aus Delegaten automatisch vorbelegen.
- Migration v3.0 → v3.1 ergänzt (`delegate_entity`, neue Ratio-Werte).
- Platzhalter-Service-Logos unter `icons/services/` hinzugefügt, inkl. README mit erwarteten Dateinamen/Quellen.

## 1.0.1 (2026-02-25)
- Lizenzdatei `LICENSE` (MIT) hinzugefügt
- GitHub `CODEOWNERS` hinzugefügt (`@Levtos`)
- `manifest.json` gepflegt: Version auf `1.0.1` erhöht und Dokumentations-/Issue-Links auf `Media_Art_Wrapper` aktualisiert

## 0.3.0 (2026-02-25)
- `supported_features` gibt jetzt `MediaPlayerEntityFeature` (IntFlag) zurück statt `int` – behebt `TypeError: argument of type 'int' is not iterable` beim Hinzufügen der Entity (HA prüft Feature-Flags mit `in`-Operator)

## 0.2.9 (2026-02-25)
- `media_player.__init__`: Beide Basisklassen (`CoordinatorEntity`, `MediaPlayerEntity`) jetzt explizit initialisiert – identisches Muster wie `camera.py`/`image.py`, behebt Entitäts-Erstellungsfehler in neueren HA-Versionen
- `state`-Property gibt jetzt `MediaPlayerState`-Enum zurück statt plain String (Kompatibilität mit HA-Validierung)
- `sensor.py`: `_attr_has_entity_name = True` entfernt (ohne `device_info` verursacht es in HA 2024.1+ Warnungen/Fehler); Name wird jetzt in `__init__` gesetzt

## 0.2.8 (2026-02-25)
- `Platform.SENSOR` zu `PLATFORMS` hinzugefügt – Sensor-Entity wurde nie geladen, da sie fehlte
- `available`-Property korrigiert: gibt jetzt `False` zurück wenn Quelle den State `unavailable`/`unknown` hat (statt immer `True`)
- `state`-Property korrigiert: gibt `None` zurück wenn kein Source-State vorhanden (HA setzt dann automatisch `unavailable`)
- `media_image_hash` verbessert: beinhaltet jetzt `last_updated`-Zeitstempel, damit der Browser-Cache invalidiert wird wenn das Cover nach dem Platzhalter nachgeladen wird

## 0.2.7 (2026-02-25)
- `media_player`-Wrapper robuster gemacht, damit die Entität zuverlässig erzeugt wird (reduzierte Attribut-Spiegelung + defensivere Source-Attribut-Lesezugriffe)
- Universal-Proxy-Verhalten beibehalten: Steuerung bleibt auf dem Source-Player, Cover kommt aus dem Coordinator
- MusicBrainz User-Agent auf `0.2.7` aktualisiert

## 0.2.6 (2026-02-25)
- Universellen `media_player`-Wrapper für Cover-Art dokumentiert (Entity `media_player.*_cover`)
- Merge-Konflikte für häufig parallel geänderte Doku-Dateien reduziert (`.gitattributes` mit `merge=union` für README/CHANGELOG)
- MusicBrainz User-Agent auf `0.2.6` aktualisiert

## 0.2.2 (2026-02-24)
- Gemeinsamen Code (`FALLBACK_IMAGE`, `source_name`) aus `image.py` und `camera.py` in neue Datei `helpers.py` ausgelagert (Duplikation beseitigt)
- `itunes.py`: Vier Regex-Muster in `_clean()` auf Modulebene vorkompiliert statt bei jedem Aufruf neu zu kompilieren
- `musicbrainz.py`: Debug-Logging bei fehlgeschlagenem Artwork-Download hinzugefügt (statt stilles `return None`)
- `musicbrainz.py`: User-Agent-Header auf aktuelle Version angepasst (`0.2.2`)

## 0.2.1 (2026-02-23)
- Staged Remix Fallback: Erst Remix-spezifisches Cover suchen, dann Original-Release als Fallback
- MusicBrainz als zweiter Provider hinzugefügt (Cover Art Archive)
- Camera-Entity für bessere Lovelace-Kompatibilität
- Status-Sensor mit Diagnostik-Attributen
- Konfigurierbare Artwork-Dimensionen (Breite/Höhe getrennt)
- Englische und deutsche Übersetzungen
- HACS-Metadaten und Icon

## 0.1.0 (2026-02-22)
- Initiale Version
- Image-Entity für Cover-Art aus `media_artist` + `media_title`
- Provider: iTunes Search API
