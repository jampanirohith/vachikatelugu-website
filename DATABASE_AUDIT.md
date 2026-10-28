# Vachika SQLite database audit

Audited file: uploaded `vachikatelugu.db` (schema version 5). This is a read-only audit of the supplied snapshot; the source DB was not modified.

## Overall status

SQLite integrity is `ok`, and the foreign-key check reports no violations. All 45 movies are marked processed; the site can build 45 movie pages, 45 album pages and 243 distinct song pages. There are 352 generated files in the site output. The catalogue adapter reads normalized columns and relationship tables, not `raw_json`/provider JSON blobs; the source-JSON-independence regression test passes.

### Table inventory

| Table | Rows | Interpretation |
|---|---:|---|
| `schema_metadata` | 1 | Schema version 5 |
| `movies` | 45 | All processed |
| `movie_genres` | 119 | Film genre relationships |
| `movie_people` | 515 | Film credits |
| `movie_links` | 243 | External film/soundtrack links |
| `ott_availability` | 117 | Availability entries across 44 movies |
| `albums` | 45 | One album per current movie entry |
| `songs` | 243 | Stable song IDs and relational links |
| `artists` | 246 | Artist dictionary |
| `song_artists` | 424 | Artist credits; three songs have no artist relationship |
| `lyricists` | 41 | Lyricist dictionary |
| `song_lyricists` | 97 | Song/lyricist credits |
| `song_media` | 351 | Validated platform media rows |
| `song_genres` | 0 | No normalized track genre assignments |
| `source_album_matches` | 77 | Internal matching/provenance table; not public |

## IMDb and movie data

All 45 movies have an IMDb score, a formatted vote string, and an integer `imdb_votes_numeric` value, so there is no missing value blocking vote-count sort in this snapshot. Poster, backdrop and plot summary are populated for all 45. Certification is populated for 42, trailer IDs for 33, soundtrack Wikipedia links for 31, Telugu titles for 5 and cinematic-universe labels for 16. Missing optional metadata should stay gracefully hidden rather than display empty labels.

The intended sorting field is `imdb_votes_numeric`, not the rating score (`imdb_score`) and not a lexicographic comparison of display strings such as `228K`. The patch orders descending by numeric vote count and uses title A–Z as a deterministic tie breaker. The first entries in this snapshot are:

| Movie | Year | IMDb score | IMDb votes |
|---|---:|---:|---:|
| RRR | 2022 | 7.8 | 228K |
| Bāhubali: The Beginning | 2015 | 8.0 | 157K |
| Adipurush | 2023 | 2.6 | 138K |
| Bāhubali 2: The Conclusion | 2017 | 8.2 | 137K |
| Pushpa: The Rise | 2021 | 7.6 | 102K |
| Sita Ramam | 2022 | 8.5 | 86K |
| Salaar: Part 1 – Ceasefire | 2023 | 6.7 | 80K |
| Kalki 2898-AD | 2024 | 7.0 | 78K |
| Dhurandhar: The Revenge | 2026 | 8.2 | 73K |
| Pushpa 2 – The Rule | 2024 | 6.0 | 69K |

Those figures are the values in the supplied database snapshot, not a live IMDb refresh.

## Albums and track counts

All 45 albums have a title and are linked to movies. Release date and dedicated 640px artwork are present for 35 albums; Spotify album ID/URL values are present for 41, and YouTube Music album ID/URL values for 36. Album artwork has a movie-poster fallback where its own cover URL is absent. The current snapshot has no populated label, UPC, copyright-C or copyright-P values; those fields are correctly omitted rather than fabricated.

Seven albums have `total_tracks` values that disagree with the actual number of `songs` rows linked by `album_id`. Similarly, 17 movies have `total_songs` values that disagree with the normalized songs joined by `movie_id`. The site already calculates visible track counts using the relationships, which avoids stale-count display errors. The raw DB totals are left unchanged by this patch.

## Songs, credits, media and duration

Every one of 243 songs has at least one media relationship: 212 have a YouTube Music record and 139 have a YouTube video record (these sets overlap). Three songs have no normalized artist credit; the other 240 have one or more. There are 97 normalized song/lyricist links. The scalar legacy `lyricist` value remains available as a fallback when a normalized relationship is absent.

The largest content gap is lyrics: none of the 243 tracks has populated plain lyrics or LRC lyrics. There are also no normalized `song_genres` rows. Lyrics and track genres should only be added from authorized/reliable data; do not infer song genres from movie genres or manufacture lyrics. The app retains song pages, credits and media links even when these fields are absent.

All 243 songs have `duration_formatted` and `duration_sec`, but 94 rows have values that disagree. The patch treats a valid `duration_formatted` (`M:SS`, with seconds below 60) as the UI source and calculates matching numeric seconds/milliseconds for the generated search model and structured data. It does not write back to SQLite. Review/correct the source data in the private DB later if the underlying durations are confirmed wrong.

## What the website uses (and current omissions)

- **Movies:** title/Telugu title, release year/language, numeric IMDb score/votes, plot, certification/runtime/universe labels, posters/backdrops, trailer, movie genres/credits, links and OTT availability. Some optional fields are unpopulated for part of the catalogue.
- **Albums:** normalized movie relationship, title, release date, artwork (with poster fallback), validated Spotify/YouTube Music links, linked track list and computed track count. Label/copyright/UPC columns are empty in this snapshot.
- **Songs:** stable `song_id`, canonical title, album/movie relationships, track number, normalized artists/lyricists, duration, provider media URLs/IDs, provider view snapshots, optional flavor/explicit/bonus flags, lyrics when present. The provider button/player behaviour is derived from `song_media`; raw IDs and raw JSON are not exposed as ordinary metadata.
- **Search projection:** songs, albums and movies are all represented. The new home search consumes all three types; movie records include IMDb score, formatted votes and numeric votes for presentation/sorting.
- **Intentionally not public:** raw/source JSON, source matching records, provenance/status columns, internal normalized names, provider maintenance/popularity/library data, raw UPC/ISRC/IDs when not needed for a particular structured-data field.

## Recommended data maintenance priorities

1. Review the 94 duration mismatches against a trustworthy source, then correct the source DB rows once verified.
2. Add/repair the three missing artist relationships and review the 7 album and 17 movie denormalized count fields (even though the site now derives actual counts correctly).
3. Populate authorized lyrics and normalized song genres only where a reliable, publishable source exists.
4. Enrich optional album release/artwork data and missing movie Telugu-title/certification/trailer/source links as available.
5. Refresh IMDb numbers deliberately in the private database pipeline if desired; the website sorts the snapshot it receives and does not call IMDb live.

No schema migration is needed for the source database for this front-end patch.
