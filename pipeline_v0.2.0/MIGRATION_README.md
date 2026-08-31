# Upgrade from the exploratory v0.1.0 working directory

This upgrade is intentionally **side-by-side**. Do not overwrite the v0.1.0 research directory that contains the completed revalidation work.

Recommended Windows layout:

```text
C:\Dev\Transients\historical_transient_laptop_pipeline_v0.1.0\transient_laptop_pipeline
C:\Dev\Transients\historical_transient_laptop_pipeline_v0.2.0_publication\transient_laptop_pipeline
```

From the new v0.2.0 directory:

```powershell
.\upgrade_from_v0.1.ps1 `
  -OldRoot "C:\Dev\Transients\historical_transient_laptop_pipeline_v0.1.0\transient_laptop_pipeline"

.\bootstrap_publication.ps1

.\freeze_publication_run.ps1
```

The upgrader copies only research state/data directories (`state`, `results`, `cache`, `logs`, `work`) and selected legacy top-level notes. It does not replace v0.2.0 source, protocol, queue, regression fixtures or documentation.

`freeze_publication_run.ps1` then:

1. freezes the annotated 74-pair production queue and original canonical queue;
2. freezes the v1 protocol, evidence policy, pre-freeze analysis inventory and legacy evidence-gap declaration;
3. records code fingerprint, exact Python/platform environment and `pip freeze`;
4. activates the immutable snapshot for automatic stage provenance;
5. indexes already preserved StarGlass FITS without re-downloading them;
6. runs the two verified FITS/hash detector regressions;
7. exports the current pre-production job and stage-run ledgers.

Do not start the remaining production queue unless the final line is:

```text
PUBLICATION FREEZE PASSED.
```
