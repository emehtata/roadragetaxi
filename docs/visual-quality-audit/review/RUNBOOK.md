# Remaining independent review

Open the pending panels listed in [batches.json](batches.json) at native resolution with `view_image`. There are four new frames on 3 pages; all prior 6,442 source-pixel reviews are retained. Confirm the gravel-road/forest/return views and rain-wet raised bridge, check the passing readiness plus same-ID removed/reloaded timeline, and log exact source/crop/hash identities. Do not infer review from atlas generation or validator success.

Use `.venv/bin/python tools/visual_quality_audit.py --check`, `.venv/bin/python tools/visual_quality_audit_review.py --check`, and `.venv/bin/python -m pytest -q -n auto tests/test_visual_quality_audit.py tests/test_visual_quality_audit_review.py`. System Python may not have Pillow installed.
