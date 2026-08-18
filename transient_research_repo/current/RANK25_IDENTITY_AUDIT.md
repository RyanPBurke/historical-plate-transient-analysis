# Rank 25 identity audit

## Finding
The legacy identifier `POSS-I:1023:O` is not unique. VI/25 contains two physical O-band exposures numbered 1023 on the same observing night.

- Rank 23 resolves to **POSS-I:1023:O:rec675**, centred near RA 181.858333, Dec -6.807222.
- Rank 25 resolves to **POSS-I:1023:O:rec799**, centred near RA 205.977083, Dec -18.728611.

The preserved morphology row `DEF-011`, labelled rank 25, is at RA ~181.8587, Dec ~-6.8872: the **rank-23 sky field**, not rank 25. It therefore cannot be used as contemporaneous rank-25 evidence. Rank 25 requires a clean identity-validated rerun at the rec799 field.

## Policy
All new POSS identifiers include VI/25 `recno`. Legacy `POSS-number:band` IDs are retained only for traceability.
