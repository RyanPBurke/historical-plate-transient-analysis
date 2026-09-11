# RC6 correction evidence

Processed independent review comment: `5626606472` (RC5 NAY).

RC6 repairs only R1/R2 transport receipt durability/integrity. Scientific SQL, bins, population, selected-key binding, batch sizes, parent provenance and source restrictions are unchanged. RC4 unknown submission remains preserved and is not imported/reset.

Offline validation:
- `python -m unittest -v test_v095a_rc6`: 58/58 PASS.
- `python run_v095a_stageA_inventory_rc6.py --self-test`: PASS; catalogue/network calls=0.
- Actual spawned transport-worker synthetic regressions preserve received status/Location across stream error, response-size hold and parent deadline kill.
- Completed checkpoint receipt deletion/status/foreign-Location mutation: HOLD; semantic mutation remains HOLD even after recomputing canonical envelope hash.
- Publication revalidates submission receipt semantics.
- SQL SHA-256 unchanged: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`.
- bins SHA-256 unchanged: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`.

Limitation: unchanged PGlite SQL fixtures were not re-run because this coordinator environment has no `node_modules` and dependency-network installation is outside the offline workflow. Windows parent-data preflight remains required after independent approval.

No TAP/catalogue/source/pixel calls were made.
