# POSS-I archive-availability accounting — v0.2.5

This implementation note does not change any detector threshold, time gate, matching radius, source filter, or scientific stopping rule.

For a prospective POSS-I exposure whose VI/25 row is internally valid and whose timing agrees with the frozen queue, a failure to obtain digital DSS pixels is an archive-availability state, not a scientific non-detection. If the primary STScI route fails and the validated SkyView DSS1 descriptor contains no entry for the deterministically expected VI/25 MLP-derived region, the workflow may complete as `catalogue_identified_pixels_unavailable` with `eligible_for_science=false`.

Such an exposure remains in the frozen prospective denominator. No neighbouring plate may be substituted. It is excluded from detector execution until a validated pixel source becomes available.

The only pre-existing exception admitted at the v0.2.5 freeze is `POSS-I:449:O:rec198` / expected region `XO197`. Freeze requires machine-readable local evidence that (1) the current SkyView DSS1B descriptor has zero XO197 entries and the raw XO197 HHH path returned HTTP 404, and (2) a direct STScI `poss1_blue` request at the target position read the official `poss1_blue.v30.lis` plate list and reported that calibration/image data were unavailable for the field.

This classification was made before any transient detector was run on the prospective production cohort.
