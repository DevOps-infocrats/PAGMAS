"""Camera proof of the FRT's Daily Achievement:

* the FRT on a phone sends a Camera photo WITH its location (latitude / longitude) and capture time; on a laptop a plain
  uploaded photo (no location) is accepted too;
* the location / time are validated (ranges, not in the future, at most a day old) and saved with the photo;
* the FE / Area Manager keep uploading proof as before (no location required);
* malformed proofMeta is refused and nothing is written.
"""

import datetime as dt
import json

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import TicketProgressFile

from .conftest import login
from .evidence import JPG, camera_geo, progress
from .test_ticket_fe import FE2, fe_org  # noqa: F401 - shared fixture
from .test_ticket_frt import FRT, _ticket, frt_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def _post(client, tid, h, gid, meta, category="A"):
    data = {"payload": json.dumps({"items": [{"taskGpId": gid, "category": category, "remark": "Splicing done"}]}), "proofGps": [str(gid)]}
    if meta is not ...:
        data["proofMeta"] = json.dumps([meta]) if not isinstance(meta, str) else meta
    return client.post(f"/api/v1/tickets/{tid}/progress-form", data=data, files=[("proofs", ("camera.jpg", JPG, "image/jpeg"))], headers=h)


def test_frt_camera_photo_location_is_checked(client, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    hf = {"X-CSRF-Token": login(client, FRT)}
    gid = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]["id"]
    now = dt.datetime.now(dt.UTC)
    bad = [
        ({**camera_geo(), "lat": 200}, "location is not valid"),
        ({**camera_geo(), "lat": 0, "lng": 0}, "location is not valid"),
        ({**camera_geo(), "capturedAt": (now - dt.timedelta(days=3)).isoformat()}, "not taken now"),
        ({**camera_geo(), "capturedAt": (now + dt.timedelta(hours=2)).isoformat()}, "not taken now"),
        ({"lat": "x", "lng": 75.1, "capturedAt": now.isoformat()}, "could not be read"),
    ]
    for meta, why in bad:
        r = _post(client, tid, hf, gid, meta)
        assert r.status_code == 422 and why in r.json()["detail"], (meta, r.text)
    assert _post(client, tid, hf, gid, "not json").status_code == 422
    assert _post(client, tid, hf, gid, json.dumps([camera_geo(), camera_geo()])).status_code == 422  # one location per photo
    with SessionLocal() as db:  # nothing was written by a refused submission
        assert db.scalar(select(func.count()).select_from(TicketProgressFile).where(TicketProgressFile.task_gp_id == gid)) == 0

    geo = camera_geo()
    r = _post(client, tid, hf, gid, geo)
    assert r.status_code == 200, r.text
    f = next(x for x in r.json()["task"]["gps"] if x["id"] == gid)["files"][0]
    assert f["latitude"] == geo["lat"] and f["longitude"] == geo["lng"] and f["accuracy"] == geo["accuracy"] and f["source"] == "CAMERA" and f["capturedAt"]
    with SessionLocal() as db:
        row = db.scalars(select(TicketProgressFile).where(TicketProgressFile.task_gp_id == gid)).one()
        assert (row.latitude, row.longitude, row.capture_source) == (geo["lat"], geo["lng"], "CAMERA") and row.captured_at is not None


def test_frt_laptop_photo_upload_accepted(client, frt_org, mail):  # noqa: F811
    """On a laptop the FRT uploads a photo file – no location – and it is accepted (saved without location)."""
    tid = _ticket(client, frt_org)
    hf = {"X-CSRF-Token": login(client, FRT)}
    gid = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]["id"]
    r = _post(client, tid, hf, gid, ...)
    assert r.status_code == 200, r.text
    f = next(x for x in r.json()["task"]["gps"] if x["id"] == gid)["files"][0]
    assert "latitude" not in f


def test_fe_proof_upload_unchanged(client, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    h2 = {"X-CSRF-Token": login(client, FE2)}  # FE Two's GPs have no FRT: the FE reports them as before
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    r = progress(client, tid, [{"taskGpId": g["id"], "category": "A", "remark": "Done by FE"}], h2, geo=False)
    assert r.status_code == 200, r.text
    f = next(x for x in r.json()["task"]["gps"] if x["id"] == g["id"])["files"][0]
    assert "latitude" not in f  # an upload without location – accepted for the FE as before
