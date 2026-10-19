"""Ortak SQLite dosyası. Ağ klasöründeki aynı .db dosyasını tüm oyuncular açar.

Her yazma kısa bir işlemdir (BEGIN IMMEDIATE): oyun okunur, kurallarla
doğrulanır, sürüm +1 ile geri yazılır. Ağ sürücüsünde WAL çalışmadığı için
klasik günlük modu kullanılır.

Süre: hamleyi yapan oyuncu kendi düşünme süresini kendi bilgisayarında ölçer
(bilgisayar saatleri farklı olsa da süre doğru kalır).
"""
import os
import random
import re
import sqlite3
import time
from contextlib import contextmanager

import chess_engine as ce

START_RATING = 1500
SPEEDS = ("bullet", "blitz", "rapid", "classical")
SPEED_NAMES = {"bullet": "Bullet", "blitz": "Blitz", "rapid": "Rapid", "classical": "Klasik"}
ONLINE_SEC = 12
NAME_RE = re.compile(r"^[A-Za-z0-9_\-çğıöşüÇĞİÖŞÜ]{2,20}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    created REAL NOT NULL,
    last_seen REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ratings (
    name TEXT NOT NULL COLLATE NOCASE,
    speed TEXT NOT NULL,
    rating INTEGER NOT NULL,
    games INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name, speed)
);
CREATE TABLE IF NOT EXISTS seeks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator TEXT NOT NULL,
    base INTEGER NOT NULL,
    inc INTEGER NOT NULL,
    rated INTEGER NOT NULL,
    color TEXT NOT NULL DEFAULT 'random',
    target TEXT,
    created REAL NOT NULL,
    game_id INTEGER,
    declined INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    white TEXT NOT NULL,
    black TEXT NOT NULL,
    base INTEGER NOT NULL,
    inc INTEGER NOT NULL,
    rated INTEGER NOT NULL,
    speed TEXT NOT NULL,
    moves TEXT NOT NULL DEFAULT '',
    white_ms INTEGER NOT NULL,
    black_ms INTEGER NOT NULL,
    last_ts REAL NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '*',
    reason TEXT NOT NULL DEFAULT '',
    draw_offer TEXT NOT NULL DEFAULT '',
    takeback_offer TEXT NOT NULL DEFAULT '',
    rematch_offer TEXT NOT NULL DEFAULT '',
    rematch_id INTEGER,
    white_rating INTEGER,
    black_rating INTEGER,
    white_diff INTEGER,
    black_diff INTEGER,
    created REAL NOT NULL,
    ended REAL,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS games_status ON games(status);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_game ON chat(game_id, id);
"""


class GameError(Exception):
    pass


def speed_of(base, inc):
    est = base + 40 * inc
    if est < 180:
        return "bullet"
    if est < 480:
        return "blitz"
    if est < 1500:
        return "rapid"
    return "classical"


def fmt_minutes(base):
    m = base / 60
    frac = {0.25: "¼", 0.5: "½", 0.75: "¾", 1.5: "1½"}
    return frac.get(m, "%g" % m)


def tc_text(base, inc):
    return "%s+%d" % (fmt_minutes(base), inc)


def expected(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def k_factor(games):
    return 40 if games < 30 else 20


class DB:
    def __init__(self, path):
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            raise GameError("Klasör bulunamadı: %s" % folder)
        self.path = path
        self.con = sqlite3.connect(path, timeout=20, isolation_level=None,
                                   check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=DELETE")
        self.con.execute("PRAGMA busy_timeout=20000")
        self.con.executescript(SCHEMA)
        self.me = None
        self._hb = 0.0
        self._clean = 0.0
        self._cache = {}

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass

    @contextmanager
    def tx(self):
        self.con.execute("BEGIN IMMEDIATE")
        try:
            yield self.con
        except BaseException:
            self.con.execute("ROLLBACK")
            raise
        else:
            self.con.execute("COMMIT")

    # ------------------------------------------------------------ kullanıcı
    def login(self, name):
        name = (name or "").strip()
        if not NAME_RE.match(name):
            raise GameError("Kullanıcı adı 2-20 karakter olmalı (harf, rakam, _ ve -).")
        now = time.time()
        with self.tx() as con:
            r = con.execute("SELECT name FROM users WHERE name=?", (name,)).fetchone()
            if r:
                name = r["name"]
                con.execute("UPDATE users SET last_seen=? WHERE name=?", (now, name))
            else:
                con.execute("INSERT INTO users(name, created, last_seen) VALUES (?,?,?)",
                            (name, now, now))
        self.me = name
        self._hb = now
        return name

    def logout(self, name):
        with self.tx() as con:
            con.execute("DELETE FROM seeks WHERE creator=? AND game_id IS NULL", (name,))
            con.execute("UPDATE users SET last_seen=0 WHERE name=?", (name,))
        self.me = None

    def _heartbeat(self):
        now = time.time()
        if self.me and now - self._hb > 4:
            self._hb = now
            self.con.execute("UPDATE users SET last_seen=? WHERE name=?", (now, self.me))

    def _rating(self, con, name, speed):
        r = con.execute("SELECT rating, games FROM ratings WHERE name=? AND speed=?",
                        (name, speed)).fetchone()
        return (r["rating"], r["games"]) if r else (START_RATING, 0)

    def _all_ratings(self):
        out = {}
        for r in self.con.execute("SELECT name, speed, rating, games FROM ratings"):
            out.setdefault(r["name"].lower(), {})[r["speed"]] = (r["rating"], r["games"])
        return out

    def players(self):
        now = time.time()
        rat = self._all_ratings()
        out = []
        for r in self.con.execute("SELECT name, last_seen FROM users ORDER BY name COLLATE NOCASE"):
            rs = rat.get(r["name"].lower(), {})
            out.append({"name": r["name"], "online": now - r["last_seen"] < ONLINE_SEC,
                        "ratings": {s: rs.get(s, (START_RATING, 0)) for s in SPEEDS}})
        return out

    def profile(self, name):
        r = self.con.execute("SELECT name, created, last_seen FROM users WHERE name=?",
                             (name,)).fetchone()
        if not r:
            raise GameError("Oyuncu bulunamadı.")
        name = r["name"]
        rs = {s: self._rating(self.con, name, s) for s in SPEEDS}
        games = [dict(g) for g in self.con.execute(
            "SELECT * FROM games WHERE (white=? OR black=?) AND status='finished' "
            "ORDER BY ended DESC LIMIT 100", (name, name))]
        w = l = d = 0
        for g in self.con.execute(
                "SELECT white, result FROM games WHERE (white=? OR black=?) AND status='finished'",
                (name, name)):
            if g["result"] == "1/2-1/2":
                d += 1
            elif (g["result"] == "1-0") == (g["white"] == name):
                w += 1
            else:
                l += 1
        return {"name": name, "created": r["created"],
                "online": time.time() - r["last_seen"] < ONLINE_SEC,
                "ratings": rs, "wins": w, "losses": l, "draws": d, "games": games}

    # ------------------------------------------------------------ ilanlar
    def _active_game(self, con, name):
        r = con.execute("SELECT id FROM games WHERE status='started' AND (white=? OR black=?) "
                        "ORDER BY id DESC LIMIT 1", (name, name)).fetchone()
        return r["id"] if r else None

    def _insert_seek(self, con, me, base, inc, rated, color, target):
        if base < 15 or base > 180 * 60 or inc < 0 or inc > 180:
            raise GameError("Geçersiz süre.")
        if color not in ("random", "white", "black"):
            color = "random"
        if target:
            t = con.execute("SELECT name FROM users WHERE name=?", (target,)).fetchone()
            if not t:
                raise GameError("Böyle bir oyuncu yok: %s" % target)
            target = t["name"]
            if target.lower() == me.lower():
                raise GameError("Kendine meydan okuyamazsın.")
        if self._active_game(con, me):
            raise GameError("Devam eden bir oyunun var.")
        con.execute("DELETE FROM seeks WHERE creator=? AND game_id IS NULL", (me,))
        cur = con.execute("INSERT INTO seeks(creator, base, inc, rated, color, target, created) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (me, int(base), int(inc), 1 if rated else 0, color, target or None,
                           time.time()))
        return cur.lastrowid

    def create_seek(self, me, base, inc, rated, color="random", target=None):
        with self.tx() as con:
            return self._insert_seek(con, me, base, inc, rated, color, target)

    def cancel_seek(self, me, sid):
        with self.tx() as con:
            con.execute("DELETE FROM seeks WHERE id=? AND creator=? AND game_id IS NULL", (sid, me))

    def decline_seek(self, me, sid):
        with self.tx() as con:
            con.execute("UPDATE seeks SET declined=1 WHERE id=? AND target=? AND game_id IS NULL",
                        (sid, me))

    def _accept(self, con, s, me):
        if s is None or s["game_id"] or s["declined"]:
            raise GameError("Bu ilan artık geçerli değil.")
        if s["creator"].lower() == me.lower():
            raise GameError("Kendi ilanını kabul edemezsin.")
        if s["target"] and s["target"].lower() != me.lower():
            raise GameError("Bu davet sana değil.")
        if self._active_game(con, me):
            raise GameError("Devam eden bir oyunun var.")
        if self._active_game(con, s["creator"]):
            raise GameError("%s şu an başka bir oyunda." % s["creator"])
        c = s["color"]
        if c == "random":
            c = random.choice(("white", "black"))
        white, black = (s["creator"], me) if c == "white" else (me, s["creator"])
        gid = self._create_game(con, white, black, s["base"], s["inc"], s["rated"])
        con.execute("UPDATE seeks SET game_id=? WHERE id=?", (gid, s["id"]))
        con.execute("DELETE FROM seeks WHERE creator=? AND game_id IS NULL", (me,))
        return gid

    def accept_seek(self, me, sid):
        with self.tx() as con:
            s = con.execute("SELECT * FROM seeks WHERE id=?", (sid,)).fetchone()
            return self._accept(con, s, me)

    def quick_pair(self, me, base, inc, rated):
        """Aynı süreli açık ilan varsa eşleşir ('game', id), yoksa ilan açar ('seek', id)."""
        with self.tx() as con:
            s = con.execute(
                "SELECT s.* FROM seeks s JOIN users u ON u.name=s.creator "
                "WHERE s.target IS NULL AND s.game_id IS NULL AND s.creator<>? "
                "AND s.base=? AND s.inc=? AND s.rated=? AND s.color='random' "
                "AND u.last_seen>? ORDER BY s.created LIMIT 1",
                (me, int(base), int(inc), 1 if rated else 0, time.time() - ONLINE_SEC)).fetchone()
            if s and not self._active_game(con, s["creator"]):
                return "game", self._accept(con, s, me)
            return "seek", self._insert_seek(con, me, base, inc, rated, "random", None)

    def poll_lobby(self, me, seek_id=None):
        self._heartbeat()
        now = time.time()
        if now - self._clean > 15:
            self._clean = now
            self.con.execute(
                "DELETE FROM seeks WHERE game_id IS NULL AND creator IN "
                "(SELECT name FROM users WHERE last_seen<?)", (now - 120,))
            self.con.execute("DELETE FROM seeks WHERE game_id IS NOT NULL AND created<?",
                             (now - 3600,))
        rat = self._all_ratings()

        def rating_of(name, speed):
            return rat.get(name.lower(), {}).get(speed, (START_RATING, 0))

        alive = now - ONLINE_SEC
        seeks = []
        for s in self.con.execute(
                "SELECT s.* FROM seeks s JOIN users u ON u.name=s.creator "
                "WHERE s.target IS NULL AND s.game_id IS NULL AND u.last_seen>? "
                "ORDER BY s.created", (alive,)):
            d = dict(s)
            d["speed"] = speed_of(s["base"], s["inc"])
            d["rating"] = rating_of(s["creator"], d["speed"])
            seeks.append(d)
        incoming = []
        for s in self.con.execute(
                "SELECT s.* FROM seeks s JOIN users u ON u.name=s.creator "
                "WHERE s.target=? AND s.game_id IS NULL AND s.declined=0 AND u.last_seen>? "
                "ORDER BY s.created", (me, alive)):
            d = dict(s)
            d["speed"] = speed_of(s["base"], s["inc"])
            d["rating"] = rating_of(s["creator"], d["speed"])
            incoming.append(d)
        mine = None
        if seek_id:
            r = self.con.execute("SELECT * FROM seeks WHERE id=?", (seek_id,)).fetchone()
            mine = dict(r) if r else {"id": seek_id, "gone": True}
        playing = [dict(g) for g in self.con.execute(
            "SELECT id, white, black, base, inc, rated, speed, moves, white_rating, black_rating "
            "FROM games WHERE status='started' ORDER BY id DESC LIMIT 50")]
        active = self._active_game(self.con, me)
        return {"seeks": seeks, "incoming": incoming, "mine": mine, "playing": playing,
                "active": active, "players": self.players(), "now": now}

    # ------------------------------------------------------------ oyun
    def _create_game(self, con, white, black, base, inc, rated):
        speed = speed_of(base, inc)
        now = time.time()
        cur = con.execute(
            "INSERT INTO games(white, black, base, inc, rated, speed, white_ms, black_ms, last_ts, "
            "status, white_rating, black_rating, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (white, black, base, inc, rated, speed, base * 1000, base * 1000, now, "started",
             self._rating(con, white, speed)[0], self._rating(con, black, speed)[0], now))
        return cur.lastrowid

    def _load(self, con, gid):
        r = con.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
        if not r:
            raise GameError("Oyun bulunamadı.")
        return dict(r)

    @staticmethod
    def _color(g, me):
        if g["white"] == me:
            return "w"
        if g["black"] == me:
            return "b"
        raise GameError("Bu oyunda oyuncu değilsin.")

    def _game_obj(self, g):
        c = self._cache.get(g["id"])
        if c and c[0] == g["moves"]:
            return c[1].clone()
        game = ce.Game(g["moves"].split())
        self._cache[g["id"]] = (g["moves"], game)
        return game.clone()

    @staticmethod
    def _update(con, gid, **f):
        cols = ", ".join("%s=?" % k for k in f)
        con.execute("UPDATE games SET %s%sversion=version+1 WHERE id=?"
                    % (cols, ", " if cols else ""), list(f.values()) + [gid])

    def _finish(self, con, g, result, reason, **extra):
        f = dict(status="finished", result=result, reason=reason, ended=time.time(),
                 draw_offer="", takeback_offer="")
        f.update(extra)
        if g["rated"]:
            sp = g["speed"]
            rw, gw = self._rating(con, g["white"], sp)
            rb, gb = self._rating(con, g["black"], sp)
            sw = 1.0 if result == "1-0" else 0.0 if result == "0-1" else 0.5
            ew = expected(rw, rb)
            dw = int(round(k_factor(gw) * (sw - ew)))
            dbl = int(round(k_factor(gb) * ((1 - sw) - (1 - ew))))
            for name, r, n, d in ((g["white"], rw, gw, dw), (g["black"], rb, gb, dbl)):
                con.execute("INSERT OR REPLACE INTO ratings(name, speed, rating, games) "
                            "VALUES (?,?,?,?)", (name, sp, r + d, n + 1))
            f.update(white_diff=dw, black_diff=dbl)
        self._update(con, g["id"], **f)

    def _timeout(self, con, g, loser, game):
        winner = ce.opp(loser)
        key = "white_ms" if loser == "w" else "black_ms"
        if game.pos.can_mate(winner):
            self._finish(con, g, "1-0" if winner == "w" else "0-1", "timeout", **{key: 0})
        else:
            self._finish(con, g, "1/2-1/2", "timeout_draw", **{key: 0})

    def _started(self, con, gid, me):
        g = self._load(con, gid)
        if g["status"] != "started":
            raise GameError("Oyun bitti.")
        return g, self._color(g, me)

    def get_game(self, gid):
        return self._load(self.con, gid)

    def poll_game(self, gid, chat_after=0):
        self._heartbeat()
        g = self._load(self.con, gid)
        chat = [dict(c) for c in self.con.execute(
            "SELECT id, name, text, ts FROM chat WHERE game_id=? AND id>? ORDER BY id",
            (gid, chat_after))]
        seen = {}
        now = time.time()
        for r in self.con.execute("SELECT name, last_seen FROM users WHERE name IN (?,?)",
                                  (g["white"], g["black"])):
            seen[r["name"]] = now - r["last_seen"] < ONLINE_SEC
        return {"game": g, "chat": chat, "online": seen}

    def play_move(self, gid, me, uci, think_ms):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            moves = g["moves"].split()
            ply = len(moves)
            if ("w" if ply % 2 == 0 else "b") != c:
                raise GameError("Sıra sende değil.")
            game = self._game_obj(g)
            key = "white_ms" if c == "w" else "black_ms"
            clock = g[key]
            if ply >= 2:
                clock -= max(0, int(think_ms))
                if clock <= 0:
                    self._timeout(con, g, c, game)
                    return self.poll_game(gid)
                clock += g["inc"] * 1000
            try:
                game.push_uci(uci)
            except ValueError:
                raise GameError("Geçersiz hamle.")
            f = {"moves": " ".join(game.moves), key: clock, "last_ts": time.time(),
                 "takeback_offer": ""}
            if g["draw_offer"] and g["draw_offer"] != c:
                f["draw_offer"] = ""
            out = game.outcome()
            if out:
                g.update(f)
                self._finish(con, g, out[0], out[1], **f)
            else:
                self._update(con, gid, **f)
        return self.poll_game(gid)

    def claim_timeout(self, gid, flagged, nmoves):
        """Sırası gelen oyuncunun süresi bitti (oyunculardan biri bildirir)."""
        with self.tx() as con:
            g = self._load(con, gid)
            moves = g["moves"].split()
            if g["status"] == "started" and len(moves) == nmoves and len(moves) >= 2 \
                    and ("w" if len(moves) % 2 == 0 else "b") == flagged:
                self._timeout(con, g, flagged, self._game_obj(g))
        return self.poll_game(gid)

    def resign(self, gid, me):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            if len(g["moves"].split()) < 2:
                self._update(con, gid, status="aborted", reason="abort", ended=time.time())
            else:
                self._finish(con, g, "0-1" if c == "w" else "1-0", "resign")
        return self.poll_game(gid)

    def abort(self, gid, me):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            if len(g["moves"].split()) >= 2:
                raise GameError("Oyun artık iptal edilemez.")
            self._update(con, gid, status="aborted", reason="abort", ended=time.time(),
                         draw_offer="", takeback_offer="")
        return self.poll_game(gid)

    def offer_draw(self, gid, me):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            if g["draw_offer"] == ce.opp(c):
                self._finish(con, g, "1/2-1/2", "agreement")
            elif not g["draw_offer"]:
                self._update(con, gid, draw_offer=c)
        return self.poll_game(gid)

    def answer_draw(self, gid, me, accept):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            if g["draw_offer"] == ce.opp(c):
                if accept:
                    self._finish(con, g, "1/2-1/2", "agreement")
                else:
                    self._update(con, gid, draw_offer="")
        return self.poll_game(gid)

    def offer_takeback(self, gid, me):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            ply = len(g["moves"].split())
            if ply < (1 if c == "w" else 2):
                raise GameError("Geri alınacak hamlen yok.")
            if not g["takeback_offer"]:
                self._update(con, gid, takeback_offer=c)
        return self.poll_game(gid)

    def answer_takeback(self, gid, me, accept):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            asker = ce.opp(c)
            if g["takeback_offer"] == asker:
                if accept:
                    moves = g["moves"].split()
                    turn = "w" if len(moves) % 2 == 0 else "b"
                    n = min(2 if turn == asker else 1, len(moves))
                    self._update(con, gid, moves=" ".join(moves[:len(moves) - n]),
                                 takeback_offer="", draw_offer="", last_ts=time.time())
                else:
                    self._update(con, gid, takeback_offer="")
        return self.poll_game(gid)

    def give_time(self, gid, me, sec=15):
        with self.tx() as con:
            g, c = self._started(con, gid, me)
            key = "black_ms" if c == "w" else "white_ms"
            self._update(con, gid, **{key: g[key] + sec * 1000})
        return self.poll_game(gid)

    def offer_rematch(self, gid, me):
        with self.tx() as con:
            g = self._load(con, gid)
            c = self._color(g, me)
            if g["status"] == "started" or g["rematch_id"]:
                return self.poll_game(gid)
            if g["rematch_offer"] == ce.opp(c):
                for n in (g["white"], g["black"]):
                    if self._active_game(con, n):
                        raise GameError("%s şu an başka bir oyunda." % n)
                nid = self._create_game(con, g["black"], g["white"], g["base"], g["inc"], g["rated"])
                self._update(con, gid, rematch_id=nid, rematch_offer="")
            elif not g["rematch_offer"]:
                self._update(con, gid, rematch_offer=c)
        return self.poll_game(gid)

    def decline_rematch(self, gid, me):
        with self.tx() as con:
            g = self._load(con, gid)
            self._color(g, me)
            if g["rematch_offer"]:
                self._update(con, gid, rematch_offer="")
        return self.poll_game(gid)

    def send_chat(self, gid, me, text):
        text = (text or "").strip()[:200]
        if text:
            with self.tx() as con:
                con.execute("INSERT INTO chat(game_id, name, text, ts) VALUES (?,?,?,?)",
                            (gid, me, text, time.time()))
        return True
