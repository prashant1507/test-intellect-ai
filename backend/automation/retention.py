from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from settings import settings

from .store import _connect

_LOG = logging.getLogger(__name__)


def prune_automation_artifacts(*, max_age_days: int | None = None) -> dict[str, Any]:
    days = max_age_days if max_age_days is not None else int(
        getattr(settings, "automation_retention_days", 20) or 0
    )
    if days <= 0:
        return {"skipped": True, "max_age_days": days}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.replace(microsecond=0).isoformat()
    cutoff_ts = cutoff.timestamp()

    art = Path(settings.automation_artifacts_dir)
    rep = Path(settings.automation_reports_dir)
    art.mkdir(parents=True, exist_ok=True)
    rep.mkdir(parents=True, exist_ok=True)

    artifact_dirs_removed = 0
    run_html_removed = 0
    n_hist = 0
    c = _connect()
    try:
        old_ids = [
            r[0]
            for r in c.execute(
                "SELECT id FROM automation_runs WHERE created_at < ?",
                (cutoff_iso,),
            ).fetchall()
        ]
        for rid in old_ids:
            d = art / str(rid)
            if d.is_dir():
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    artifact_dirs_removed += 1
                except OSError as e:
                    _LOG.warning("remove artifact dir %s: %s", d, e)
            f = rep / f"{rid}.html"
            if f.is_file():
                try:
                    f.unlink()
                    run_html_removed += 1
                except OSError as e:
                    _LOG.warning("remove run report %s: %s", f, e)

        n_hist = c.execute(
            "SELECT count(*) FROM automation_suite_case_run_history WHERE finished_at < ?",
            (cutoff_iso,),
        ).fetchone()[0]
        c.execute(
            "DELETE FROM automation_suite_case_run_history WHERE finished_at < ?",
            (cutoff_iso,),
        )
        c.execute(
            "DELETE FROM automation_run_steps WHERE run_id IN (SELECT id FROM automation_runs WHERE created_at < ?)",
            (cutoff_iso,),
        )
        c.execute("DELETE FROM automation_runs WHERE created_at < ?", (cutoff_iso,))
        c.commit()
    finally:
        c.close()

    keep = set()
    c2 = _connect()
    try:
        keep = {str(r[0]) for r in c2.execute("SELECT id FROM automation_runs").fetchall()}
    finally:
        c2.close()

    orphan_dirs = 0
    if art.is_dir():
        for p in art.iterdir():
            if not p.is_dir() or p.name in keep:
                continue
            try:
                if p.stat().st_mtime < cutoff_ts:
                    shutil.rmtree(p, ignore_errors=True)
                    orphan_dirs += 1
            except OSError as e:
                _LOG.warning("remove orphan dir %s: %s", p, e)

    stale_html = 0
    for p in rep.glob("*.html"):
        try:
            if p.stat().st_mtime < cutoff_ts:
                p.unlink(missing_ok=True)
                stale_html += 1
        except OSError as e:
            _LOG.warning("remove old report %s: %s", p, e)

    return {
        "max_age_days": days,
        "cutoff": cutoff_iso,
        "automation_runs_pruned": len(old_ids),
        "suite_history_rows_pruned": int(n_hist or 0),
        "artifact_dirs_removed": artifact_dirs_removed,
        "run_html_removed": run_html_removed,
        "orphan_artifact_dirs_removed": orphan_dirs,
        "stale_html_reports_removed": stale_html,
    }
