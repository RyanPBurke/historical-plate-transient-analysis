# v094c exploratory preservation

Exploratory raw-coordinate screening baseline; preserved for reproducibility and superseded for confirmatory inference.

This directory is an **archival preservation**, not scientific validation. It preserves the completed v094c raw-coordinate catalogue-mismatch screen before fragment-aware timing repair.

Known limitations include: parent exposure envelopes were used without `exposure_sub` fragment timing; the 784 directed triplets are not a universal branch denominator; second-site matching used raw catalogue coordinates; source absence is not a qualified negative; and the v094c survivors are not a valid input population for a parallax-permitting branch.

The candidate CSV was never parsed by the preservation script. It was hashed and compressed as an opaque byte stream. Its original SHA256 is `68f1e5f0a42a2c292371c930aad51ff8a5d7d2bd4d71e5026449b35928939d1d` and its integrity basis is `verified_against_frozen_v094c_report_and_bank`.

The zero-source hold table SHA256 is `c97a3093992905b0b7119a83d147d202384b6f407fc2ca5611efd858153a9643` and its integrity basis is `verified_against_frozen_v094c_report_and_bank`.

To verify this snapshot, check `SHA256SUMS.txt` and `preservation_manifest_v094c.json`. If the candidate gzip is split, concatenate `.partNNN` files in lexical order before decompression.
