"""Satranç kuralları: hamle üretimi, rok, geçerken alma, terfi, şah/mat/pat,
üç kez tekrar, 50 hamle, yetersiz materyal ve SAN gösterimi.

Kare numarası: a1=0, b1=1 ... h8=63. Taşlar: 'PNBRQK' beyaz, küçük harf siyah.
"""
from collections import namedtuple

FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def sq_name(s):
    return FILES[s & 7] + str((s >> 3) + 1)


def sq_index(n):
    return FILES.index(n[0]) + 8 * (int(n[1]) - 1)


def color(p):
    return "w" if p.isupper() else "b"


def opp(c):
    return "b" if c == "w" else "w"


def _steps(table):
    out = []
    for s in range(64):
        f, r = s & 7, s >> 3
        out.append(tuple((r + dr) * 8 + f + df for df, dr in table
                         if 0 <= f + df < 8 and 0 <= r + dr < 8))
    return out


def _rays(dirs):
    out = []
    for s in range(64):
        f, r = s & 7, s >> 3
        rays = []
        for df, dr in dirs:
            ray, x, y = [], f + df, r + dr
            while 0 <= x < 8 and 0 <= y < 8:
                ray.append(y * 8 + x)
                x += df
                y += dr
            if ray:
                rays.append(tuple(ray))
        out.append(tuple(rays))
    return out


KNIGHT_TO = _steps(((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)))
KING_TO = _steps(((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)))
DIAG_RAYS = _rays(((1, 1), (1, -1), (-1, 1), (-1, -1)))
ORTH_RAYS = _rays(((1, 0), (-1, 0), (0, 1), (0, -1)))
# Bu karelere dokunulursa ilgili rok hakkı gider
CASTLE_LOSS = {4: "KQ", 0: "Q", 7: "K", 60: "kq", 56: "q", 63: "k"}


class Move(namedtuple("Move", "frm to promo")):
    __slots__ = ()

    def uci(self):
        return sq_name(self.frm) + sq_name(self.to) + (self.promo.lower() if self.promo else "")

    @staticmethod
    def from_uci(u):
        u = u.strip()
        promo = u[4].upper() if len(u) > 4 else None
        return Move(sq_index(u[0:2]), sq_index(u[2:4]), promo)


class Position:
    __slots__ = ("board", "turn", "castling", "ep", "halfmove", "fullmove", "_legal")

    def __init__(self, fen=START_FEN):
        self._legal = None
        if fen is None:
            return
        parts = fen.split()
        self.board = [""] * 64
        for i, row in enumerate(parts[0].split("/")):
            r, f = 7 - i, 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                else:
                    self.board[r * 8 + f] = ch
                    f += 1
        self.turn = parts[1]
        self.castling = "" if parts[2] == "-" else parts[2]
        self.ep = None if parts[3] == "-" else sq_index(parts[3])
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1

    def copy(self):
        n = Position(None)
        n.board = self.board[:]
        n.turn, n.castling, n.ep = self.turn, self.castling, self.ep
        n.halfmove, n.fullmove = self.halfmove, self.fullmove
        return n

    def fen(self):
        rows = []
        for r in range(7, -1, -1):
            row, empty = "", 0
            for f in range(8):
                p = self.board[r * 8 + f]
                if p:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += p
                else:
                    empty += 1
            rows.append(row + (str(empty) if empty else ""))
        ep = sq_name(self.ep) if self.ep is not None else "-"
        return "%s %s %s %s %d %d" % ("/".join(rows), self.turn, self.castling or "-",
                                      ep, self.halfmove, self.fullmove)

    # ------------------------------------------------------------- saldırı
    def king(self, c):
        return self.board.index("K" if c == "w" else "k")

    def attacked(self, s, by):
        """s karesine 'by' rengi saldırıyor mu?"""
        b = self.board
        P, N, B, R, Q, K = "PNBRQK" if by == "w" else "pnbrqk"
        f, r = s & 7, s >> 3
        pr = r - 1 if by == "w" else r + 1
        if 0 <= pr < 8:
            if f > 0 and b[pr * 8 + f - 1] == P:
                return True
            if f < 7 and b[pr * 8 + f + 1] == P:
                return True
        for t in KNIGHT_TO[s]:
            if b[t] == N:
                return True
        for t in KING_TO[s]:
            if b[t] == K:
                return True
        for ray in DIAG_RAYS[s]:
            for t in ray:
                p = b[t]
                if p:
                    if p == B or p == Q:
                        return True
                    break
        for ray in ORTH_RAYS[s]:
            for t in ray:
                p = b[t]
                if p:
                    if p == R or p == Q:
                        return True
                    break
        return False

    def in_check(self):
        return self.attacked(self.king(self.turn), opp(self.turn))

    # ------------------------------------------------------------- hamleler
    def pseudo_moves(self):
        b, us = self.board, self.turn
        white = us == "w"
        mine = str.isupper if white else str.islower
        them = opp(us)
        out = []
        for s, p in enumerate(b):
            if not p or not mine(p):
                continue
            k = p.upper()
            if k == "P":
                d = 8 if white else -8
                f, r = s & 7, s >> 3
                last = 7 if white else 0
                t = s + d
                if not b[t]:
                    self._pawn_to(out, s, t, last)
                    if r == (1 if white else 6) and not b[t + d]:
                        out.append(Move(s, t + d, None))
                for df in (-1, 1):
                    if 0 <= f + df < 8:
                        t = s + d + df
                        if b[t] and not mine(b[t]):
                            self._pawn_to(out, s, t, last)
                        elif t == self.ep and not b[t]:
                            out.append(Move(s, t, None))
            elif k == "N":
                for t in KNIGHT_TO[s]:
                    if not b[t] or not mine(b[t]):
                        out.append(Move(s, t, None))
            elif k == "K":
                for t in KING_TO[s]:
                    if not b[t] or not mine(b[t]):
                        out.append(Move(s, t, None))
                home = 4 if white else 60
                if s == home and self.castling:
                    ks, qs = ("K", "Q") if white else ("k", "q")
                    rook = "R" if white else "r"
                    if (ks in self.castling and b[home + 3] == rook and not b[home + 1]
                            and not b[home + 2] and not self.attacked(home, them)
                            and not self.attacked(home + 1, them)
                            and not self.attacked(home + 2, them)):
                        out.append(Move(home, home + 2, None))
                    if (qs in self.castling and b[home - 4] == rook and not b[home - 1]
                            and not b[home - 2] and not b[home - 3]
                            and not self.attacked(home, them)
                            and not self.attacked(home - 1, them)
                            and not self.attacked(home - 2, them)):
                        out.append(Move(home, home - 2, None))
            else:
                rays = ()
                if k in "BQ":
                    rays += DIAG_RAYS[s]
                if k in "RQ":
                    rays += ORTH_RAYS[s]
                for ray in rays:
                    for t in ray:
                        q = b[t]
                        if not q:
                            out.append(Move(s, t, None))
                        else:
                            if not mine(q):
                                out.append(Move(s, t, None))
                            break
        return out

    @staticmethod
    def _pawn_to(out, s, t, last):
        if t >> 3 == last:
            for q in "QRBN":
                out.append(Move(s, t, q))
        else:
            out.append(Move(s, t, None))

    def push(self, m):
        n = self.copy()
        b = n.board
        p = b[m.frm]
        cap = b[m.to]
        white = p.isupper()
        b[m.frm] = ""
        pawn = p in "Pp"
        if pawn and m.to == self.ep and not cap:
            b[m.to + (-8 if white else 8)] = ""
            cap = "x"
        b[m.to] = (m.promo if white else m.promo.lower()) if m.promo else p
        if p in "Kk" and abs(m.to - m.frm) == 2:
            if m.to > m.frm:
                b[m.frm + 1], b[m.frm + 3] = b[m.frm + 3], ""
            else:
                b[m.frm - 1], b[m.frm - 4] = b[m.frm - 4], ""
        if n.castling:
            for s in (m.frm, m.to):
                for ch in CASTLE_LOSS.get(s, ""):
                    n.castling = n.castling.replace(ch, "")
        n.ep = (m.frm + m.to) // 2 if pawn and abs(m.to - m.frm) == 16 else None
        n.halfmove = 0 if pawn or cap else self.halfmove + 1
        if not white:
            n.fullmove += 1
        n.turn = opp(self.turn)
        return n

    def legal_moves(self):
        if self._legal is None:
            us, them = self.turn, opp(self.turn)
            res = []
            for m in self.pseudo_moves():
                n = self.push(m)
                if not n.attacked(n.king(us), them):
                    res.append(m)
            self._legal = res
        return self._legal

    # ------------------------------------------------------------- durum
    def key(self):
        """Tekrar karşılaştırması için anahtar (ep yalnızca alınabiliyorsa sayılır)."""
        ep = ""
        if self.ep is not None:
            for m in self.legal_moves():
                if m.to == self.ep and self.board[m.frm] in "Pp":
                    ep = str(self.ep)
                    break
        return "".join(p or "." for p in self.board) + self.turn + self.castling + ep

    def insufficient_material(self):
        rest = [(p, i) for i, p in enumerate(self.board) if p and p not in "Kk"]
        if any(p in "PpRrQq" for p, _ in rest):
            return False
        if len(rest) <= 1:
            return True
        if all(p in "Bb" for p, _ in rest):
            return len({((i & 7) + (i >> 3)) % 2 for _, i in rest}) == 1
        return False

    def can_mate(self, c):
        """Süre bittiğinde: c rengi teorik olarak mat edebilir mi?"""
        own = [p for p in self.board if p and p not in "Kk" and color(p) == c]
        if not own:
            return False
        others = [p for p in self.board if p and p not in "Kk" and color(p) != c]
        if len(own) == 1 and own[0] in "NBnb" and not others:
            return False
        return not self.insufficient_material()

    def san(self, m):
        b = self.board
        p = b[m.frm].upper()
        if p == "K" and abs(m.to - m.frm) == 2:
            s = "O-O" if m.to > m.frm else "O-O-O"
        else:
            cap = bool(b[m.to]) or (p == "P" and m.to == self.ep)
            if p == "P":
                s = (FILES[m.frm & 7] + "x" if cap else "") + sq_name(m.to)
                if m.promo:
                    s += "=" + m.promo
            else:
                others = [o.frm for o in self.legal_moves()
                          if o.to == m.to and o.frm != m.frm and b[o.frm] == b[m.frm]]
                dis = ""
                if others:
                    if all(o & 7 != m.frm & 7 for o in others):
                        dis = FILES[m.frm & 7]
                    elif all(o >> 3 != m.frm >> 3 for o in others):
                        dis = str((m.frm >> 3) + 1)
                    else:
                        dis = sq_name(m.frm)
                s = p + dis + ("x" if cap else "") + sq_name(m.to)
        n = self.push(m)
        if n.in_check():
            s += "#" if not n.legal_moves() else "+"
        return s, n

    def material(self):
        """{'w': puan, 'b': puan} ve taş sayıları."""
        cnt = {}
        for p in self.board:
            if p:
                cnt[p] = cnt.get(p, 0) + 1
        return cnt


def premove_dests(pos, s):
    """Ön hamle için taşın gidebileceği kareler (engeller yok sayılır)."""
    p = pos.board[s]
    if not p:
        return []
    k, white = p.upper(), p.isupper()
    f, r = s & 7, s >> 3
    out = []
    if k == "P":
        d = 1 if white else -1
        if 0 <= r + d < 8:
            out.append(s + 8 * d)
            for df in (-1, 1):
                if 0 <= f + df < 8:
                    out.append(s + 8 * d + df)
        if r == (1 if white else 6):
            out.append(s + 16 * d)
    elif k == "N":
        out = list(KNIGHT_TO[s])
    elif k == "K":
        out = list(KING_TO[s])
        home = 4 if white else 60
        if s == home:
            ks, qs = ("K", "Q") if white else ("k", "q")
            if ks in pos.castling:
                out.append(home + 2)
            if qs in pos.castling:
                out.append(home - 2)
    else:
        rays = ()
        if k in "BQ":
            rays += DIAG_RAYS[s]
        if k in "RQ":
            rays += ORTH_RAYS[s]
        for ray in rays:
            out.extend(ray)
    return [t for t in out if not (pos.board[t] and color(pos.board[t]) == color(p))]


class Game:
    """Başlangıçtan itibaren oynanan hamleler ve her konum."""

    def __init__(self, ucis=()):
        self.positions = [Position()]
        self.moves = []      # uci listesi
        self.sans = []
        self.keys = [self.positions[0].key()]
        for u in ucis:
            self.push_uci(u)

    @property
    def pos(self):
        return self.positions[-1]

    def clone(self):
        g = Game.__new__(Game)
        g.positions, g.moves = self.positions[:], self.moves[:]
        g.sans, g.keys = self.sans[:], self.keys[:]
        return g

    def push_uci(self, u):
        try:
            m = Move.from_uci(u)
        except (ValueError, IndexError):
            raise ValueError("Geçersiz hamle: %s" % u)
        if m not in self.pos.legal_moves():
            raise ValueError("Geçersiz hamle: %s" % u)
        san, n = self.pos.san(m)
        self.positions.append(n)
        self.moves.append(m.uci())
        self.sans.append(san)
        self.keys.append(n.key())
        return san

    def outcome(self):
        """(sonuç, sebep) ya da None."""
        pos = self.pos
        if not pos.legal_moves():
            if pos.in_check():
                return ("1-0" if pos.turn == "b" else "0-1"), "mate"
            return "1/2-1/2", "stalemate"
        if pos.insufficient_material():
            return "1/2-1/2", "material"
        if self.keys.count(self.keys[-1]) >= 3:
            return "1/2-1/2", "repetition"
        if pos.halfmove >= 100:
            return "1/2-1/2", "fifty"
        return None

    def pgn(self, headers=None):
        lines = ['[%s "%s"]' % (k, v) for k, v in (headers or {}).items()]
        body = []
        for i, s in enumerate(self.sans):
            if i % 2 == 0:
                body.append("%d." % (i // 2 + 1))
            body.append(s)
        if headers and "Result" in headers:
            body.append(headers["Result"])
        return "\n".join(lines) + ("\n\n" if lines else "") + " ".join(body) + "\n"
