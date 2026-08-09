"""The automated follow-up sequence.

A lead who runs the calculator is scheduled three follow-ups. A background tick
sends whatever is due. The sequence stops the moment someone buys or opts out,
because chasing a customer who has already paid is the fastest way to lose them.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import config
import db
import emailer


def schedule_for_lead(lead_id):
    if not config.SEQUENCE_ENABLED:
        return
    now = datetime.now(timezone.utc)
    due = {}
    for step, hours in enumerate(config.SEQ_STEP_HOURS, start=1):
        due[step] = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
    db.schedule_sequence(lead_id, due)


def stop_for_lead(lead_id):
    db.cancel_sequence(lead_id)


def run_due(limit=25):
    """Send every follow-up that is due. Returns how many went out."""
    if not config.SEQUENCE_ENABLED:
        return 0
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sent = 0
    for job in db.due_sequence_jobs(now_iso, limit):
        step = job["step"]
        if step < 1 or step > len(emailer.SEQUENCE):
            db.mark_sequence_sent(job["id"], None)
            continue
        if job["unsubscribed"] or not job["email"]:
            db.cancel_sequence(job["lead_id"])
            continue
        try:
            res = json.loads(job["calc_results"]) if job["calc_results"] else None
        except (ValueError, TypeError):
            res = None
        lead = {"name": job["name"], "email": job["email"],
                "product_name": job["product_name"], "token": job["token"]}
        subject, body = emailer.SEQUENCE[step - 1](lead, res)
        email_id = emailer.send(job["email"], subject, body, kind="sequence_%d" % step)
        db.mark_sequence_sent(job["id"], email_id)
        sent += 1
    return sent


async def ticker():
    """Background loop. Deliberately forgiving: a failure never kills the task."""
    while True:
        try:
            await asyncio.sleep(config.SEQUENCE_TICK_SECONDS)
            await asyncio.to_thread(run_due)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                   # noqa: BLE001
            try:
                db.log_email("(sequence runner)", "Sequence tick failed", str(exc)[:500],
                             "error", "failed", str(exc)[:400])
            except Exception:                      # noqa: BLE001
                pass
