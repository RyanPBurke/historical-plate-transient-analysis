WIDE CENSUS — FROZEN SHIFTED POPULATION CONTROLS v062
================================================================

Prerequisites
-------------
v056 heavy detector: COMPLETE
v057 prospective adjudication contract SHA:
  1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad
v061 execution plan SHA:
  08330cb1c1693e1b40cfb7e41dd35abe721206df3a6437511cb0e642e6b5bfd3

Method
------
This executes the already-frozen population controls:
  radii:      60", 120"
  directions: N, NE, E, SE, S, SW, W, NW
  gates:      <=3", <=10"
  jobs:       33 pairs x 16 shifts = 528

For each pair:
1. Select endpoint A/B candidate coordinates using the exact same v054 common
   polygon and point-in-polygon implementation used by v056.
2. Recompute the unshifted <=3"/<=10" counts with a unit-sphere cKDTree.
3. REFUSE unless those counts reproduce the exact v056 pair counts.
4. Shift endpoint B by an exact great-circle directional offset.
5. Count all cross-endpoint candidate pairs within <=3" and <=10".
6. Checkpoint after every pair.

The shifted denominator is fixed to the endpoint-B detections that were inside
the common polygon before shifting. No candidates outside the observed v056
domain are introduced.

Interpretation
--------------
Population context only. An excess or null never promotes/rejects an individual
candidate. The next frozen stage remains primary common-Gaia registration.

Resource use
------------
No network.
No science pixels.
No detector.
No candidate state mutation.
Two streaming passes over the 5.08M-row candidate CSV, retaining only RA/Dec
(~81 MiB of numeric coordinate storage plus KD trees).

Run
---
  Expand-Archive ".\wide_census_population_controls_v062.zip" `
      -DestinationPath ".\wide_census_population_controls_v062" `
      -Force

  Copy-Item ".\wide_census_population_controls_v062\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\run_wide_census_population_controls_v062.py"

The stage is resumable after each completed pair.
