# Database-to-website field map

This document records the display and privacy policy for the normalized SQLite schema used by the website. Row counts below describe the supplied `vachikatelugu.db` snapshot only; counts change as the private data repository is updated. This file contains no database data or credentials.

## Source-of-truth rules

1. The private SQLite file is the only catalogue input. The generator opens it read-only during the Cloudflare build.
2. Catalogue values come from scalar columns and normalized relationship tables, not from raw/source JSON columns.
3. `search-index.json` is a deliberately limited, generated output used by browser-side search. It is never read by `build.py` as an input and is not a competing source of truth. `site.json` is site configuration (name, tagline and canonical URL), not a catalogue.
4. A song's `song_id` is its identity and canonical route. Spotify/YouTube identifiers only power provider buttons, embeds and redirects from old provider-ID URLs where a mapping exists.
5. Missing optional values are omitted. Missing media, genres or lyrics do not remove an otherwise valid song page.
6. `source_album_matches`, raw source blobs, provenance, source status, internal matching values and provider-maintenance fields are not exposed as visitor-facing metadata.

## Snapshot coverage (uploaded schema-v5 database)

These values describe the uploaded `vachikatelugu.db` snapshot only; the private repository may change them over time.

| Table | Rows | Public use |
|---|---:|---|
| `schema_metadata` | 1 | Confirms schema version 5. |
| `movies` | 45 | Public film pages and shared film context. |
| `movie_genres` | 119 | Film genres; normalized rows are authoritative. |
| `movie_people` | 515 | Film credits; role and credit ordering retained. |
| `movie_links` | 243 | Validated external film/soundtrack links. |
| `ott_availability` | 117 | Streaming/rent/buy availability links. |
| `albums` | 45 | Album pages and song-to-album relationships. |
| `songs` | 243 | Canonical song pages and track metadata. |
| `artists` | 246 | Artist names for song credits. |
| `song_artists` | 424 | Normalized artist credits and credit roles/order. |
| `lyricists` | 41 | Lyricist names. |
| `song_lyricists` | 97 | Normalized lyricist credits and order. |
| `song_media` | 351 | Track-level provider links, player IDs and video details. |
| `song_genres` | 0 | Track-level genres; filter stays hidden while empty. |
| `source_album_matches` | 77 | Internal candidate/source matching only; not public. |

All 45 processed movies have all three IMDb values needed for rating/vote display and sorting. All 243 songs have at least one `song_media` row, so every song currently has at least one provider-backed media record. The snapshot has no populated LRC/plain lyrics and no normalized song-genre relationships. All 243 tracks still receive canonical song pages regardless of lyrics or track genres.

## Every table and column

### `schema_metadata`

- `key`, `value`: used to check `schema_version = 5`; not shown to visitors.

### `movies`

- `imdb_id`: route identity where it matches an IMDb ID, plus references/structured metadata.
- `title`, `title_telugu`, `release_year`, `original_language`: film title/context; Telugu title and optional language are omitted when absent.
- `cinematic_universe`, `certification`, `runtime_minutes`: shown in the film's detailed information only when populated.
- `imdb_score`, `imdb_votes`, `imdb_votes_numeric`: film rating/vote display and optional structured rating information.
- `tmdb_url`, `imdb_url`, `wikipedia_url`, `wikipedia_soundtrack_url`: external links after URL validation.
- `plot_summary`: film summary on its movie page and contextual song page when present.
- `poster_url`, `backdrop_url`, `title_logo_url`: artwork. Movie poster is the fallback for album art when the dedicated album artwork fields are empty.
- `trailer_youtube_id`: sanitized ID used for the movie trailer player; not exposed as a raw ID.
- `total_songs`: not trusted as a display count; displayed totals are computed from normalized song relationships to prevent stale counts.
- `processing_status`: build eligibility filter (`processed` only), not a public field.
- `genres_json`: ignored; `movie_genres` is the authoritative genre source.
- `raw_json`, `source_metadata_json`, `source_status_json`, `created_at`, `updated_at`: ignored by the catalogue adapter and never rendered.

### `movie_genres`

- `movie_id`: relationship to the movie.
- `genre`: film genre shown on film pages/cards and used in the movie catalogue filter.
- `genre_order`: preserves source/intended display order.

### `movie_people`

- `movie_id`: relationship to the movie.
- `role`: determines the credit label. Common roles (director, cast, music director, cinematographer, production banner) have curated labels; other normalized roles are retained as additional film credits.
- `person_name`: public credit name, shown only when present.
- `credit_order`: controls ordering within the role.

### `movie_links`

- `movie_id`: owner movie.
- `link_type`: maps the link to a user-facing label.
- `url`: validated HTTP(S) URL shown in the movie's optional links menu. Invalid URLs are omitted.

### `ott_availability`

- `movie_id`: owner movie.
- `provider`: provider name shown for that film.
- `availability_type`: label for streaming, rent, buy or free/ads availability. The project constructs a provider search URL because this table stores availability, not a per-title playable URL.

### `albums`

- `album_id`: relational identity; participates in a unique local album route slug.
- `movie_id`: relationship to the owning film.
- `title`: public album title; provider-specific album titles are fallback values only when the canonical title is absent.
- `release_date`, `label`, `copyright_c`, `copyright_p`: displayed on the album page only if populated.
- `artwork_hd_640`, `artwork_300`: dedicated scalar artwork URLs; if absent, the linked movie poster is used with fallback alt text.
- `spotify_album_id`, `youtube_album_id`, `spotify_url`, `youtube_music_url`: validated provider buttons/links; raw IDs and URLs are not listed as song metadata.
- `spotify_album_title`, `youtube_album_title`: title fallback fields, not separate metadata rows.
- `total_tracks`: source-declared value is not used as truth for rendering the tracklist; actual connected song counts are calculated from `songs`.
- `spotify_total_tracks`, `spotify_popularity`, `spotify_saved_to_library`: provider-snapshot/maintenance values intentionally hidden.
- `upc_barcode`: technical catalog identifier intentionally hidden from ordinary listener pages.
- `spotify_images_json`, `source_metadata_json`, `raw_json`: intentionally ignored; the adapter does not parse or depend on them.

### `songs`

- `song_id`: canonical song identity and route `/song/{song_id}/`; must be unique and URL-safe.
- `album_id`, `movie_id`: normalized links to the actual album and movie. Mismatches fail the build rather than silently dropping a track.
- `title`: public track title.
- `track_number`, `track_number_original`, `disc_number`: track number uses the first available valid value; missing numbers are not invented; disc is omitted when it is the default disc 1.
- `duration_formatted`, `duration_sec`, `duration_ms`: duration displayed as `m:ss` only when it can be represented reliably.
- `lyricist`: legacy scalar fallback only when `song_lyricists` has no relationship for that song.
- `song_flavor`: shown only when it is a meaningful non-generic value; generic values like “Film Soundtrack” are suppressed.
- `lrc_lyrics`, `plain_lyrics`: separate lyrics section appears only when actual lyrics exist. LRC timestamps are retained line by line; plain lyrics are shown without pretending to be synchronized. Data must be licensed/authorized for publication.
- `is_explicit`: an “Explicit” label is shown only when the database explicitly confirms true; unknown/null does not become “No”.
- `is_bonus_track`: “Bonus track: Yes” is shown only when true.
- `spotify_uri`: can supply a Spotify track ID fallback for the provider button/player; never shown as metadata.
- `isrc_code`: not shown in the song metadata panel; used only in machine-readable `MusicRecording` structured data when present.
- `lrclib_id`, `lyrics_status`, `lyrics_type`, `data_source`: internal lookup/provenance/status information, hidden from ordinary visitor metadata.
- `artist_ids_json`, `genres_json`, `audio_features_json`, `source_metadata_json`, `raw_json`: ignored; artist and genre data are read from normalized relationships and source JSON blobs are not parsed.

### `artists`

- `artist_id`: join key for normalized credits.
- `artist_name`: displayed on song pages, search, and song filters when connected through `song_artists`.
- `normalized_name`: internal normalization/deduplication field; not displayed.
- `spotify_artist_id`: external matching identifier; not displayed and not used as song identity.

### `song_artists`

- `song_id`, `artist_id`: normalized many-to-many song/artist relationship.
- `credit_role`: groups credits into useful labels such as singers, performers or composers. It is not printed as a raw database value.
- `credit_order`: preserves ordering.

### `lyricists`

- `lyricist_id`: join key for normalized credits.
- `lyricist_name`: displayed as lyricist credit where linked to a song.
- `normalized_name`: internal matching/deduplication field; not displayed.

### `song_lyricists`

- `song_id`, `lyricist_id`: normalized song/lyricist relationship.
- `credit_order`: preserves ordering for multiple lyricists.

### `song_media`

- `song_id`: song receiving a provider link/media record.
- `platform`: selects the provider behavior (Spotify, YouTube Music or YouTube).
- `external_id`: validated provider ID used by buttons/embeds; never displayed as a raw ID.
- `url`: validated URL behind the relevant provider button, not duplicated in metadata.
- `preview_url`: read as a provider field but not displayed or currently used as a separate player.
- `video_title`: displayed only as the title of the associated YouTube video where available.
- `views_text`: shown only as associated YouTube video view information when meaningful; sentinel/missing values like `N/A` are discarded.
- `popularity`: provider-snapshot metric intentionally hidden from song metadata.
- `extra_json`: intentionally ignored.

### `song_genres`

- `song_id`: song relationship.
- `genre`: used for track-specific genres, metadata and filtering only when actual rows exist.
- `genre_order`: ordering.

The supplied snapshot contains no song-genre rows. The implementation does not wrongly present movie genres as if they were track-level genres.

### `ott_availability` and `source_album_matches`

`ott_availability` is documented above. `source_album_matches` contains `movie_id`, `platform`, `album_id`, `album_title`, `url`, and `source_csv`. These are data-ingestion/candidate-match fields used to reconcile album sources, not verified public catalogue facts; therefore none of these fields is rendered to visitors. Validated, linked album records in `albums` and `movie_links` power public links instead.

## Missing-data presentation policy

- Do not show empty metadata rows, the string `None`, sentinel values (`N/A`, `unknown`, `not provided`, etc.), or “not provided by source” explanations.
- Do not show Spotify/YouTube URLs, IDs, preview URLs, millisecond durations, source titles, or raw ingestion fields in Song metadata. Provider actions remain separate buttons; detailed YouTube video information belongs with the video section.
- Do not invent artists, lyricists, track numbers, genres, exact release dates or negative content ratings.
- Missing providers/lyrics/genres are coverage gaps, not reasons to reject a song or omit its page.
- Build validation reports coverage to maintainers without placing those diagnostics on public pages.
