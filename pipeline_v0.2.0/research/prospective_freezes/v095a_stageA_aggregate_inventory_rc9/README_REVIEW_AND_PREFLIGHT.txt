v095a Stage A Aggregate Inventory Implementation RC9
==================================================

STATUS: FINAL BOUNDED CORRECTION CANDIDATE; NOT EXECUTION-FROZEN.

RC9 is correction/review cycle 3 of 3 after RC5. RC7 was staged but never independently reviewed and therefore did not consume a correction/review cycle. RC4, RC5, RC6, RC7 and RC8 remain immutable audit/review evidence.

RC9 addresses only ASTRA RESPONSE v095a-rc8-release-review comment 5634646740:
  1. publication now reuses the complete checkpoint validator against the exact expected family/batch/query/context/result lifecycle and therefore requires 1-3 consecutive attempts with a final VALIDATED attempt bound to the published result;
  2. frozen-parent proof archive selection is restored to research/proof_archives/v094y_rc4_proof_archive.zip while retaining the unchanged frozen digest;
  3. on controller interruption during submission-body streaming, the spawned worker is stopped and already-fsynced bounded body bytes are atomically copied out of temporary IPC before cleanup, then hash-bound with the durable header receipt into uncertain submission evidence. The attempt remains HOLD and cannot authorize resubmission.

The RC4 acknowledgement helper remains create_v095a_rc4_unknown_submission_disposition.ps1. It verifies the exact retained RC4 Q0 checkpoint and creates provenance evidence only when the user explicitly supplies -AcknowledgeSupersedingReadOnlyRetry. It does not alter or resolve the RC4 checkpoint.

Scientific SQL, histogram bins, population, selected-solution binding, batch sizes and permission boundaries are unchanged. No individual source IDs, coordinates, photometry, pairing, pixels or scans are permitted.

Required later gates:
  1. independent RC9 release-specific review;
  2. if YAY, Windows RC9 self-test;
  3. Windows full preflight against frozen parents/proof archive;
  4. exact-byte Git execution freeze and remote evidence;
  5. explicit RC4 unknown-submission acknowledgement evidence;
  6. explicit authorization before catalogue execution.

If independent review NAYs RC9, STOP and return to Ryan. The bounded workflow does not authorize RC10 or any fourth correction/review cycle.

Do not copy/import the RC4 failed work directory. RC9 uses work/v095a_stageA_aggregate_inventory_rc9.
