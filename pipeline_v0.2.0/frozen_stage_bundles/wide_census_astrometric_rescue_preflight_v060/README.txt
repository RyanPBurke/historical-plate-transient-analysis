WIDE CENSUS — INDEPENDENT ASTROMETRIC RESCUE PREFLIGHT v060
================================================================

v059 established:
  10 physical plates = PROCESS_COMPLETED_ASTROMETRICALLY_UNSOLVED
   1 physical plate  = NO_PROCESS_ROW_FOR_EXACT_SCAN
   1 physical plate  = V058_OFFICIAL_SOLUTION_ALREADY_PRESENT

There was no new solution_set-level rescue among the unsolved plates.

v060 does NOT solve anything. It freezes the metadata-preflight boundary first,
then obtains only candidate-independent archive information needed to choose a
solver method prospectively.

For the 10 completed-unsolved processes it obtains:
- physical plate scale / size / instrument metadata;
- exact scan pixel size and dimensions;
- approximate FOV priors from independent physical metadata;
- exposure pointing priors already present in v058;
- TOP 1000 existing APPLAUSE `source` rows with flag_clean=1, sorted by flux_max;
- nested counts for sextractor_flags=0 and model_prediction>=0.9;
- a small existing `source_xmatch` sample for diagnostics only.

For the one scan with no process row:
- no source catalogue is invented;
- it is explicitly labelled as requiring a separately frozen pixel-source
  extraction branch if we choose to rescue it.

No transient detector output or candidate coordinate is read or used.

Run while v056 continues:

  Expand-Archive ".\wide_census_astrometric_rescue_preflight_v060.zip" `
      -DestinationPath ".\wide_census_astrometric_rescue_preflight_v060" `
      -Force

  Copy-Item ".\wide_census_astrometric_rescue_preflight_v060\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\preflight_wide_census_astrometric_rescue_v060.py"

Guards:
  NETWORK: APPLAUSE metadata / extracted-source catalogue only
  SCIENCE PIXELS: NO
  TRANSIENT DETECTOR: NO
  ASTROMETRIC SOLVER: NO
  CANDIDATE STATE: NO CHANGE
  GEOMETRY CLASSIFICATION: NO CHANGE
  AUTOMATION REGISTRY: NO CHANGE
