# Smart Player — Home Assistant Integration
## Lastenheft v1.0 | April 2026

Migrationsbasis: Umbau der bestehenden Media Art Wrapper (MAW) + Combined Media Player (CMP)
Integrationen zu einer neuen konsolidierten Integration unter dem Namen `smart_player`.
Das bestehende MAW-Repository bleibt die Basis — Code wird umgebaut, nicht neu geschrieben.

---

# 1. Überblick & Zielsetzung

Die `smart_player` Integration ersetzt MAW und CMP durch eine einheitliche Integration
mit zwei klar getrennten internen Schichten:

| Schicht     | Verantwortung                                                                 | Output                              |
|-------------|-------------------------------------------------------------------------------|-------------------------------------|
| CMP-Schicht | Player-Fusion: fasst steuerbare Media Player zu einem virtuellen Meta-Player  | Eine steuerbare HA media_player Entity |
| MAW-Schicht | Artwork-Kontext: liefert Cover-Art als Fallback wenn Quelle kein Artwork hat  | entity_picture / image Entity       |

**Kernprinzip:**
Liefert die aktive Quelle bereits Artwork (z.B. Music Assistant für HomePods), wird dieses
durchgereicht. MAW greift nur wenn kein natives Artwork vorhanden ist. CMP steuert
ausschließlich steuerbare Entitäten — nicht-steuerbare Quellen (Discord, TV/Sat, Switch)
sind reiner Kontext.

---

# 2. Architektur

## 2.1 Entitäten-Klassifizierung

| Gerät / Quelle       | Steuerbar via CMP | Artwork-Quelle          | Bemerkung                                              |
|----------------------|-------------------|-------------------------|--------------------------------------------------------|
| HomePods (via MA)    | Ja                | MA liefert nativ        | Music Assistant als Musik-Backend                      |
| Apple TV             | Ja                | ATV liefert eigenes Artwork | Streaming / Apps                                   |
| PS5                  | Begrenzt          | IGDB / SteamGridDB      | Kontext via binary_sensor.ps5_context_active_combined  |
| Nintendo Switch      | Nein              | IGDB                    | Nur Kontext-Quelle                                     |
| Discord              | Nein              | IGDB / SteamGridDB      | Kontext via sensor.discord_active_game_atomic          |
| TV / Sat             | Nein              | EPG -> WDR / ARD / ZDF  | Kontext via sensor.tv_active_input == live_tv          |
| Stash                | Ja (Stash Player) | StashDB / PornDB / AEBN | Adult Content, eigener Provider-Pfad                   |
| Denon AVR            | OUT OF SCOPE      | —                       | Audio-Routing gehört zur Medienlogik-Automation        |

## 2.2 CMP — Player-Priorität (Transport-Controls)

| Priorität | Bedingung                               | Aktiver Player                              |
|-----------|-----------------------------------------|---------------------------------------------|
| 1         | Apple TV playing / paused               | Apple TV                                    |
| 2         | Nur HomePods spielen (kein PS5-Kontext) | Music Assistant / HomePods                  |
| 3         | PS5 aktiv, HomePods an                  | HomePods (Audio), PS5 als Kontext           |
| 4         | PS5 aktiv, HomePods aus                 | Kein steuerbarer Player — kein Transport    |
| 5         | Stash aktiv                             | Stash Player                                |

**OUT OF SCOPE (diese Version):**
PS5 + HomePods gleichzeitig als vollwertiges Dual-Szenario. Wird implementiert sobald die
neue Medienlogik (CEC-Abschaltung + simultane HomePod-Aktivierung bei PS5) steht.
Im Code als TODO markieren.

## 2.3 MAW — Artwork-Hierarchie

Wird für jede aktive Quelle in dieser Reihenfolge durchlaufen:

| Prio | Bedingung                                  | Aktion                                  | Provider                  |
|------|--------------------------------------------|-----------------------------------------|---------------------------|
| 1    | Quelle liefert Artwork nativ (MA)          | Durchreichen, fertig                    | —                         |
| 2    | ATV aktiv, kein media_title                | App-Logo anzeigen                       | service_logo() Helper     |
| 3    | ATV aktiv, media_title vorhanden           | Content-Lookup                          | TMDb / iTunes             |
| 4    | PS5 / Switch / Discord aktiv               | Game-Lookup                             | IGDB -> SteamGridDB       |
| 5    | Stash aktiv                                | Scene-Lookup                            | Stash -> StashDB -> PornDB -> AEBN |
| 6    | TV/Sat, Sender in EPG-Liste                | EPG-Lookup -> Programmtitel -> Cover    | TVMaze / TMDb             |
| 7    | TV/Sat, Sender nicht in Liste              | Sender-Logo                             | service_logo() Helper     |
| 8    | Nichts gefunden                            | Placeholder                             | FALLBACK_IMAGE            |

## 2.4 Badge-System

Wenn mehrere Quellen gleichzeitig aktiv sind, wird ein Badge-Logo über das primäre Cover gelegt:

| Szenario                                      | Primäres Cover             | Badge                                          |
|-----------------------------------------------|----------------------------|------------------------------------------------|
| HomePods spielen Musik, Discord meldet Spiel  | Musik-Cover (MA nativ)     | Game-Logo (SteamGridDB transparent PNG)        |
| Nur PS5 aktiv (HomePods aus)                  | Spielcover (IGDB/SGDB)     | Kein Badge                                     |
| Nur Discord aktiv                             | Spielcover                 | Kein Badge                                     |
| Animiertes GIF verfügbar (SteamGridDB)        | GIF als Full-Cover         | Kein Badge — GIF nicht als Overlay compositen  |

**Badge-Spezifikation:**
- Quelle: SteamGridDB /logos/ Endpoint (transparente PNG-Logos)
- Position: unten rechts
- Größe: 22% der Cover-Breite
- Format: PNG mit Alpha-Kanal (kein GIF als Badge)

---

# 3. Provider-Architektur

## 3.1 Bestehende Provider (Übernahme / Anpassung)

| Provider    | Datei                    | Status      | Aktion                                          |
|-------------|--------------------------|-------------|-------------------------------------------------|
| iTunes      | providers/itunes.py      | Fertig      | Übernehmen, confidence-Feld aktivieren          |
| MusicBrainz | providers/musicbrainz.py | Fertig      | Übernehmen, Scoring ergänzen                    |
| TMDb        | providers/tmdb.py        | Fertig      | tv-Kategorie-Bug fixen                          |
| TVMaze      | providers/tvmaze.py      | Halbfertig  | Doppelten API-Call cachen, EPG zusammenführen   |
| IGDB        | providers/igdb.py        | Fertig      | Übernehmen                                      |
| SteamGridDB | providers/steamgriddb.py | Halbfertig  | Retry-Bug fixen, Logo-Endpoint ergänzen         |
| Fanart.tv   | providers/fanart.py      | Fertig      | Übernehmen                                      |
| EPG Base    | providers/epg_base.py    | Halbfertig  | Timezone-Fix, mit TVMaze-EPG zusammenführen     |

## 3.2 Neue Provider

| Provider | Datei                  | Kategorie | APIs              | Bemerkung                                    |
|----------|------------------------|-----------|-------------------|----------------------------------------------|
| StashDB  | providers/stashdb.py   | adult     | StashDB GraphQL   | Portiert aus stash_player StashClient        |
| PornDB   | providers/porndb.py    | adult     | PornDB REST API   | Fallback nach StashDB                        |
| AEBN     | providers/aebn.py      | adult     | AEBN API          | Fallback nach PornDB                         |

## 3.3 Legacy-Code — Löschen

Folgende Dateien werden ersatzlos gelöscht (toter Code, nie importiert):

- cover_resolver.py
- models.py
- battlenet.py
- epg.py
- itunes.py (root)
- musicbrainz.py (root)
- steam.py (root)
- tv.py (root)

---

# 4. Game Database

## 4.1 Konzept

Eine persistente lokale Datenbank die alle je gesehenen Spieltitel mit zugehörigem Artwork
speichert. Wachsende Wissensbasis — einmal geladen, immer verfügbar.

## 4.2 Datenstruktur (JSON)

Speicherort: /config/custom_components/smart_player/game_db.json

```json
{
  "civilization_vi": {
    "canonical_title": "Sid Meier's Civilization VI",
    "sgdb_id": 3877,
    "igdb_id": 1068,
    "logo_url": "https://cdn.sgdb.com/...",
    "logo_override_url": null,
    "logo_cached_path": "logo_cache/sgdb_3877.png",
    "cover_cached_path": "cover_cache/igdb_1068.jpg",
    "last_seen": "2026-04-24T20:00:00",
    "play_count": 12,
    "lookup_failed": false
  }
}
```

## 4.3 Verhalten

| Situation                          | Aktion                                                            |
|------------------------------------|-------------------------------------------------------------------|
| Titel zum ersten Mal gesehen       | Eintrag anlegen, API-Lookup starten, Ergebnis cachen             |
| Titel bekannt, Cache vorhanden     | Direkt aus Cache laden, kein API-Call                            |
| Titel bekannt, lookup_failed=true  | Kein erneuter API-Call (bis manuell zurückgesetzt)               |
| logo_override_url gesetzt          | Override gewinnt immer — kein API-Call für Logo                  |
| GIF als Logo verfügbar             | Als Full-Cover speichern, nicht als Badge-Overlay                |

## 4.4 Cache-Strategie nach Kategorie

| Kategorie              | Persistenter Cache | TTL        | Override möglich        |
|------------------------|--------------------|------------|-------------------------|
| Games (Logo + Cover)   | Ja                 | Unbegrenzt | Ja (logo_override_url)  |
| Serien (Poster)        | Ja                 | 30 Tage    | Nein                    |
| Filme (Poster)         | Ja                 | 1 Jahr     | Nein                    |
| Adult / Stash (Cover)  | Ja                 | Unbegrenzt | Nein                    |
| Musik / Radio          | Nein               | —          | —                       |
| TV / EPG               | Nein               | —          | —                       |

---

# 5. EPG-Funktion

## 5.1 Scope

EPG ist ausschließlich für TV/Sat-Modus relevant. Konfigurierbare Sender-Liste
(initial: WDR, ARD, ZDF). Kein XMLTV-Direktingest in dieser Version.

## 5.2 Logik

| Bedingung                              | Aktion                                                        |
|----------------------------------------|---------------------------------------------------------------|
| sensor.tv_active_input == live_tv      | EPG-Pfad aktivieren                                           |
| Sender in konfigurierter Liste         | EPG-Lookup -> Programmtitel -> Cover via TVMaze / TMDb        |
| Sender nicht in Liste                  | Sender-Logo direkt (service_logo Helper)                      |
| EPG-Lookup erfolgreich                 | CoverData.title = Programmtitel (nicht Sendername)            |
| EPG-Lookup fehlgeschlagen              | Sender-Logo als Fallback                                      |

## 5.3 Fixes gegenüber aktuellem Stand

- Timezone-Fix: epg_base.py nutzt datetime.now() ohne Timezone — auf UTC umstellen
- EPG-Duplication: HaEpgProvider und TVMaze-EPG zusammenführen zu einem einzigen Pfad
- CoverData.title muss EPG-Programmtitel enthalten, nicht den Sendernamen
- EPG_FULL_LOOKUP_CHANNELS konfigurierbar machen (nicht mehr hardcoded im Code)

---

# 6. Stash-Integration

## 6.1 Konzept

Die stash_player Integration bleibt als eigene Integration bestehen für die
Media-Player-Steuerung. Smart Player übernimmt ausschließlich das Cover-Fetching
als Provider.

## 6.2 Portierbare Komponenten aus stash-ha

| Komponente                    | Quelle              | Aktion                                          |
|-------------------------------|---------------------|-------------------------------------------------|
| StashClient (GraphQL-Wrapper) | __init__.py:44-157  | 1:1 portieren nach providers/stashdb.py         |
| Query-Strings                 | const.py:51-116     | 1:1 übernehmen                                  |
| _fix_paths() URL-Rewriter     | __init__.py:229-240 | Übernehmen + erweitertes Hostname-Rewriting     |
| fetch_cover() Core            | image.py:105-146    | Portieren ohne _is_streaming-Gate               |

## 6.3 Neu zu bauen

- Performer- und Studio-Bilder abfragen (performers{image_path}, studio{image_path} ergänzen)
- SCENE_BY_ID_QUERY tatsächlich aufrufen (existiert, wird nie genutzt)
- HTTP-Timeout + Retry-Logik
- Erweitertes Hostname-Rewriting (127.0.0.1, Docker-Hostnamen, Custom-Ports)
- StashDB API-Key in Options/Config-Flow

## 6.4 Adult Content Provider-Priorität

| Priorität | Provider        | Bedingung                              |
|-----------|-----------------|----------------------------------------|
| 1         | Stash Screenshot | Stash liefert paths.screenshot direkt |
| 2         | StashDB         | Lookup via Szenen-Titel                |
| 3         | PornDB          | Fallback wenn StashDB nichts findet    |
| 4         | AEBN            | Fallback wenn PornDB nichts findet     |
| 5         | Studio-Logo     | Letzter Fallback — service_logo()      |

---

# 7. Medienlogik-Abhängigkeiten

## 7.1 Bereits vorhandene Sensoren (nutzbar)

| Entity ID                              | Zweck                           | Werte                                              |
|----------------------------------------|---------------------------------|----------------------------------------------------|
| sensor.tv_active_input                 | Aktive TV-Quelle (NEU, gepusht) | ps5 / atv / live_tv / tv_on_idle / none            |
| binary_sensor.homepods_music_active    | HomePods spielen Musik (NEU)    | on / off                                           |
| binary_sensor.ps5_context_active_combined | PS5 Kontext aktiv            | on / off                                           |
| sensor.discord_active_game_atomic      | Discord Spiel aktiv             | 0=kein / 1=unbekannt / 2=Overwatch / 3=Hearthstone |
| binary_sensor.homepods_active_atomic   | HomePods aktiv (mit Delay)      | on / off                                           |
| sensor.audio_output_state_combined     | Audio-Output Zustand            | 0=idle / 1=H / 2=D / 3=DH / 4=DS / 5=DSH         |

## 7.2 Noch fehlende Sensoren

| Sensor                       | Wann benötigt             | Bemerkung                                    |
|------------------------------|---------------------------|----------------------------------------------|
| binary_sensor.stash_active   | Stash-Pfad in MAW-Schicht | Nach MAW-Umbau — basiert auf smart_player Entity |
| sensor.stash_playback_state  | Feinerer Stash-Kontext    | Nach MAW-Umbau                               |

---

# 8. Technischer Cleanup

## 8.1 Kritische Bugs fixen

| Bug                           | Datei                          | Fix                                                        |
|-------------------------------|--------------------------------|------------------------------------------------------------|
| Retry-Bug SteamGridDB         | providers/steamgriddb.py:211   | Dimension-Filter im ersten Request, Retry ohne Filter      |
| Timezone-Bug EPG              | providers/epg_base.py          | datetime.now() -> datetime.now(tz=timezone.utc)            |
| TMDb tv-Kategorie             | providers/tmdb.py              | categories frozenset korrigieren                           |
| TVMaze Doppel-API-Call        | providers/tvmaze.py            | Session-Cache für _tvmaze_show_id Ergebnis                 |
| manifest.json iot_class       | manifest.json                  | cloud_polling -> local_push                                |
| _active_entity_id() Duplikat  | media_player.py                | In Shared-Helper auslagern                                 |
| _entry_delegate_entity() Stub | media_player.py                | Entfernen                                                  |
| ArtworkResult.confidence      | providers/__init__.py          | Tatsächlich im resolve_cover() nutzen                      |

## 8.2 Fehlende Service-Logos

In helpers.py sind 29 Dienste gemappt, in icons/services/ liegen nur 13 PNGs.
Fehlende Logos nachziehen oder aus der Map entfernen:

- hulu, peacock, paramount_plus, youtube, youtube_tv, twitch
- gog, pocket_casts, overcast, castro, soundcloud, deezer

## 8.3 Sonstiges

- services.yaml: debug_connection Service implementieren oder entfernen
- Migration-Docstring async_migrate_entry auf v1->v6 korrigieren
- music_assistant_provider/ dokumentieren oder in eigenes Repo auslagern

---

# 9. Domain-Umbenennung

Der Domain-Rename von `media_art_wrapper` zu `smart_player` erfolgt als letzter Schritt
nach Abschluss aller übrigen Arbeiten.

| Schritt | Aktion                                                                  |
|---------|-------------------------------------------------------------------------|
| 1       | Alle Features implementiert und getestet                                |
| 2       | Config-Migration: media_art_wrapper -> smart_player (async_migrate_entry anpassen) |
| 3       | HACS: Repository-Name ändern, manifest.json domain aktualisieren        |
| 4       | README und Dokumentation aktualisieren                                  |
| 5       | Brands-Proxy: Neue Icons unter smart_player hinterlegen                 |

---

# 10. Explizit Out of Scope (diese Version)

- PS5 + HomePods gleichzeitig als vollwertiges Dual-Szenario
  (Abhängigkeit: neue Medienlogik mit CEC-Abschaltung)
- Denon AVR als CMP-Source (gehört zur Medienlogik-Automation)
- XMLTV-Direktingest (CONF_XMLTV_URL bleibt reserviert)
- Collage-Funktion für mehrere gleichwertige Cover
- Custom Panel / Cache-Browser (MAW v3.4 Roadmap-Feature)
- Battlenet-Provider (war nur in Legacy-Schicht, komplett absent im neuen System)
