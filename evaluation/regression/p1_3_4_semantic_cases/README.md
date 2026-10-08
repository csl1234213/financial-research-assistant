# P1.3.4 semantic regression cases

These cases replay the saved P1.3.3 provider responses offline.  The raw
answer, final context and citations remain in the immutable smoke artifact
under `evaluation/results/p1_3_3_remaining_9q_smoke/smoke_results.json`; this
manifest only identifies the five cases and their observed failure stage.

Run:

```text
python evaluation/replay_p1_3_4.py
```

The replay never imports a provider adapter and never enables
`ALLOW_REAL_PROVIDER`.
