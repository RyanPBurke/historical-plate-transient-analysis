WIDE CENSUS — POST-DETECTOR INVENTORY + QUEUES v061

v056 is complete and v057 was frozen prospectively before v056 outcomes were
inspected. v061 is the first bookkeeping step after v056.

It performs no network access, no pixel reads, no detector runs and no candidate
state changes. It verifies the raw-match totals by streaming the completed v056
raw-match CSV, inventories the 33 pair rows, writes the prospectively specified
population-control queue (60"/120" x 8 directions) and primary astrometry queue
(5'/10'/20'/30', >=5 common same-Gaia refs, translation median only), and freezes
the execution order.

Run:

  Expand-Archive ".\wide_census_postdetector_inventory_v061.zip" `
      -DestinationPath ".\wide_census_postdetector_inventory_v061" `
      -Force

  Copy-Item ".\wide_census_postdetector_inventory_v061\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\compile_wide_census_postdetector_inventory_v061.py"
