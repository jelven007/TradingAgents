"""Personal watchlists isolated by the authenticated workspace and subject."""

import time

from tradingagents.domain.research_settings import InputError
from tradingagents.infrastructure.reports import database


class WatchlistStore:
    def __init__(self, path):
        self.path = path
        with database(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS investor_watchlist (
                workspace TEXT NOT NULL, subject TEXT NOT NULL, symbol TEXT NOT NULL,
                note TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(workspace,subject,symbol))""")

    def list(self, principal):
        with database(self.path) as db:
            return [dict(row) for row in db.execute(
                """SELECT symbol,note,created,updated FROM investor_watchlist
                WHERE workspace=? AND subject=? ORDER BY updated DESC,symbol""",
                (principal.workspace, principal.subject),
            )]

    def change(self, principal, data, approved):
        key = (principal.workspace, principal.subject, data.symbol)
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT 1 FROM investor_watchlist WHERE workspace=? AND subject=? AND symbol=?",
                key,
            ).fetchone()
            if data.action == "remove":
                db.execute(
                    "DELETE FROM investor_watchlist WHERE workspace=? AND subject=? AND symbol=?",
                    key,
                )
            elif data.action == "save_note":
                if not old:
                    raise InputError("symbol", "请先将对象加入关注清单。")
                db.execute("""UPDATE investor_watchlist SET note=?,updated=?
                    WHERE workspace=? AND subject=? AND symbol=?""", (data.note, time.time(), *key))
            elif not old:
                if data.symbol not in approved:
                    raise InputError("symbol", "对象不在当前批准清单中，请先配置研究模板。")
                count = db.execute(
                    "SELECT COUNT(*) FROM investor_watchlist WHERE workspace=? AND subject=?",
                    key[:2],
                ).fetchone()[0]
                if count >= 100:
                    raise InputError("symbol", "最多关注100个对象，请移除不再关注的对象。")
                now = time.time()
                db.execute("INSERT INTO investor_watchlist VALUES (?,?,?,?,?,?)",
                           (*key, data.note, now, now))
        return {"symbol": data.symbol, "action": data.action}
