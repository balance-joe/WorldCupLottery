# Project Rules

This project is for 中国体育彩票竞彩足球 analysis.

Business rules:
- Use 中国体育彩票竞彩足球 rules as source of truth.
- Treat SP as fixed-prize value, not normal bookmaker odds.
- Store raw Sporttery snapshots before normalization.
- Football result means 90 minutes including stoppage time.
- Same match different play types cannot be mixed into one parlay.
- Handicap line is fixed after sale starts; SP values can change.
- Never assume overseas bookmaker rules unless explicitly requested.

Engineering rules:
- Do not overwrite raw data.
- Keep crawlers, normalization, modeling, and reporting separated.
- Every probability calculation must be unit-tested.
- Every betting-ticket generation rule must be tested.