v095a Stage A Aggregate Inventory Implementation RC5
==================================================

STATUS: TRANSPORT-EVIDENCE REPAIR CANDIDATE; NOT EXECUTION-FROZEN.

RC5 supersedes RC4 only for transport receipt observability. RC4's first live Q0 submission entered a conservative HOLD after an unaccepted HTTP status but failed to persist the status/headers/body. RC5 records that evidence before classifying the receipt.

Scientific SQL, histogram bins, population, selected-solution binding, batch sizes and permission boundaries are unchanged. No individual source IDs, coordinates, photometry, pairing, pixels or scans are permitted.

Required gates:
  1. independent RC5 release review;
  2. Windows RC5 self-test;
  3. Windows full preflight against frozen parents/proof archive;
  4. exact-byte Git execution freeze and remote evidence;
  5. explicit authorization before catalogue execution.

Do not copy/import the RC4 failed work directory. RC5 uses work/v095a_stageA_aggregate_inventory_rc5.
