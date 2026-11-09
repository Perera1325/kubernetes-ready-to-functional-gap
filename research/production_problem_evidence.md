# Evidence for Recovery Debt (strength: moderate, mostly practitioner)
- DZone Ollama experiments (S14): Ready-to-inference gap 3.8-14.3 s; "model exists" vs "model ready". Single-author blog; treat as hypothesis support only.
- Red Hat Krkn (S15): "A Ready pod does not prove that transactions succeed" - vendor guidance.
- Expedia (S17): leader marked Ready, follower not; liveness checked container, not function.
- CNCF blog (S16): a recovery test is not deleting a pod; validate user path, not resource status.
- Longhorn docs (S18): replacement pods stuck while VolumeAttachment lingers (~6 min).
- NOT used: a dev.to "Kubernetes 1.32 eviction postmortem" that surfaced in search. It looks unreliable (no verifiable source, implausible claims). Excluded.
No primary production incident report specific to this gap has been verified yet.
