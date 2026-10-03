# Public review subset: publication and provenance

This is a curated public subset of the Luna architecture experiment dated 2026-10-02, published on 2026-10-03 for independent review. It is not the complete original ZIP.

REPORT.md, README.md, manifest.json, task prompts, patches, independent probe code, and structured JSON results are preserved byte-for-byte. Historical statements in these files that no publication occurred describe the experiment at its original completion; this public subset was published later. The historical README and report mention raw logs that are not included here.

All raw execution .log files are omitted as a data-minimization precaution. This does not claim secrets were found. The original SHA256SUMS was replaced with hashes for this public subset. No source payload was redacted or altered. PUBLICATION.json records the original ZIP hash, each retained original member hash, and every omitted member and its original hash.

Read REPORT.md for results, README.md for reproduction instructions, and PUBLICATION.json for provenance. The original report is observational evidence, not an independent verification. Tests were not rerun for this publication; the included code has not been applied to this branch. Each implementation patch must be applied separately to baseline commit 950058e2d9d2cfac01c3b1f50b5805097c04ab58 in a disposable checkout. Preserve the known held-out HTTP 422 versus expected 400 mismatch when assessing the experiment.

Safety review used credential/private-path/internal-metadata pattern scans and inspection of report, prompts, probes, documentation patches, metadata, and structured results. Email literals are test fixtures. The source bundle and all original checksums were verified against the ZIP before publication. These checks reduce accidental disclosure risk but are not a guarantee that every possible secret format is detectable.
