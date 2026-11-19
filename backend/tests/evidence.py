"""Shared helpers for the ticket tests: the evidence rules of the GP-wise task.

A Daily Achievement (a category A / C / D, the older Done / Pending, or a corrected returned GP) needs a remark and at
least one photo (JPG / PNG) in the same submission; the Area Manager's approval (AM_APPROVE) and the SME's forward
(SME_FORWARD) need the reviewer's own proof document. These helpers send exactly that, so a test can focus on what it
checks (they never weaken the rules – a test of the rule itself posts without them)."""

import datetime as dt
import json

JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # smallest content the JPG check accepts
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
DEFAULT_REMARK = "Work done – photo attached"
PROOF_STEPS = ("AM_APPROVE", "SME_FORWARD")


def _needs_photo(it: dict) -> bool:
    return it.get("category") is not None or it.get("status") is not None or bool(it.get("achievedToday"))


def camera_geo():
    """The location / time the camera dialog sends with a live photo (proofMeta item)."""
    return {"lat": 26.9124, "lng": 75.7873, "accuracy": 12.5, "capturedAt": dt.datetime.now(dt.UTC).isoformat()}


def progress(client, tid, items=None, headers=None, new_gps=None, note=None, photo=True, extra_files=None, geo=True):
    """POST /progress-form: every item that sets an achievement gets a remark (when missing) and a photo; added GPs
    with a category too. `photo=False` sends no photo (to test the rule). geo=True: every file is a camera photo with
    its location (proofMeta – required from the FRT); geo=False sends none."""
    items = [dict(it) for it in (items or [])]
    new_gps = [dict(n) for n in (new_gps or [])]
    files, gps = [], []
    for it in items:
        if photo and _needs_photo(it):
            it.setdefault("remark", DEFAULT_REMARK)
            it["remark"] = it["remark"] or DEFAULT_REMARK
            files.append(("proofs", (f"site_{it['taskGpId']}.jpg", JPG, "image/jpeg")))
            gps.append(str(it["taskGpId"]))
    for i, n in enumerate(new_gps):
        if photo and n.get("category"):
            n["remark"] = n.get("remark") or DEFAULT_REMARK
            files.append(("proofs", (f"new_{i}.jpg", JPG, "image/jpeg")))
            gps.append(str(-(i + 1)))
    for gid, f in extra_files or []:
        files.append(("proofs", f))
        gps.append(str(gid))
    data = {"payload": json.dumps({"items": items, "newGps": new_gps, "note": note})}
    if gps:
        data["proofGps"] = gps
        if geo:
            data["proofMeta"] = json.dumps([camera_geo() for _ in gps])
    return client.post(f"/api/v1/tickets/{tid}/progress-form", data=data, files=files or None, headers=headers)


def review(client, tid, body, headers=None, proof=True):
    """POST /review-form: AM_APPROVE / SME_FORWARD carry a proof document (the reviewer's evidence)."""
    files = [("proofs", (f"{body['action'].lower()}_proof.pdf", PDF, "application/pdf"))] if proof and body.get("action") in PROOF_STEPS else None
    return client.post(f"/api/v1/tickets/{tid}/review-form", data={"payload": json.dumps(body)}, files=files, headers=headers)
