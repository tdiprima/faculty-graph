"""Link records that different sources reported separately.

Harvesting keeps each source's data as that source stated it. Reconciliation is
the separate phase that says two of those records describe the same thing. The
distinction matters operationally: links live in their own graph, so a bad
reconciliation is undone by dropping one file rather than by re-harvesting.
"""
