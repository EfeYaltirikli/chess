"""Hızlı test: kurallar (perft + özel durumlar) ve iki oyunculu ortak DB senaryoları.

Çalıştır:  py test_zeichess.py      (sonda "TÜM TESTLER OK" yazmalı)
"""
import os
import tempfile
import time

import chess_engine as ce
import db as zdb


def perft(p, d):
    if d == 0:
        return 1
    ms = p.legal_moves()
    if d == 1:
        return len(ms)
    return sum(perft(p.push(m), d - 1) for m in ms)


def test_rules():
    cases = [
        (ce.START_FEN, 3, 8902),
        ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3, 97862),
        ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238),
        ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3, 9467),
        ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3, 62379),
    ]
    for fen, d, n in cases:
        r = perft(ce.Position(fen), d)
        assert r == n, (fen, r, n)
    # çoban matı
    g = ce.Game("e2e4 e7e5 f1c4 b8c6 d1h5 g8f6 h5f7".split())
    assert g.sans[-1] == "Qxf7#" and g.outcome() == ("1-0", "mate"), (g.sans, g.outcome())
    # geçerken alma
    g = ce.Game("e2e4 a7a6 e4e5 d7d5 e5d6".split())
    assert g.sans[-1] == "exd6" and g.pos.board[ce.sq_index("d5")] == ""
    # rok ve SAN
    g = ce.Game("e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 e1g1".split())
    assert g.sans[-1] == "O-O" and g.pos.board[ce.sq_index("f1")] == "R"
    # şahtan rok yapılamaz
    p = ce.Position("4k3/8/8/8/8/8/4r3/R3K2R w KQ - 0 1")
    assert all(abs(m.to - m.frm) != 2 for m in p.legal_moves() if m.frm == 4)
    # tehdit altındaki kareden geçerek rok yok
    p = ce.Position("4k3/8/8/8/8/8/5r2/R3K2R w KQ - 0 1")
    assert ce.Move(4, 6, None) not in p.legal_moves() and ce.Move(4, 2, None) in p.legal_moves()
    # terfi
    p = ce.Position("8/P7/8/8/8/8/8/k6K w - - 0 1")
    assert {m.promo for m in p.legal_moves() if m.frm == 48} == set("QRBN")
    san, _ = p.san(ce.Move(48, 56, "Q"))
    assert san == "a8=Q+", san
    # pat
    g = ce.Game()
    g.positions = [ce.Position("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")]
    g.keys = [g.pos.key()]
    assert g.outcome() == ("1/2-1/2", "stalemate")
    # yetersiz materyal
    assert ce.Position("8/8/8/4k3/8/8/2B5/4K3 w - - 0 1").insufficient_material()
    assert not ce.Position("8/8/8/4k3/8/8/2R5/4K3 w - - 0 1").insufficient_material()
    # üç kez tekrar
    g = ce.Game("g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8".split())
    assert g.outcome() == ("1/2-1/2", "repetition"), g.outcome()
    # belirsizlik giderme
    p = ce.Position("4k3/8/8/8/8/8/4K3/R6R w - - 0 1")
    assert p.san(ce.Move(0, 3, None))[0] == "Rad1"
    print("Kurallar OK")


def test_db():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "test.db")
    a, b = zdb.DB(path), zdb.DB(path)
    A, B = a.login("ali"), b.login("Bora")
    assert b.login("bora") == "Bora"
    # hızlı eşleşme
    k1, sid = a.quick_pair(A, 180, 2, True)
    assert k1 == "seek"
    lob = b.poll_lobby(B)
    assert any(s["id"] == sid for s in lob["seeks"])
    k2, gid = b.quick_pair(B, 180, 2, True)
    assert k2 == "game"
    assert a.poll_lobby(A, sid)["mine"]["game_id"] == gid
    g = a.get_game(gid)
    w, bl = (a, A), (b, B)
    if g["white"] != A:
        w, bl = bl, w
    # iki hamle (saat başlamaz)
    w[0].play_move(gid, w[1], "e2e4", 99999)
    bl[0].play_move(gid, bl[1], "e7e5", 99999)
    g = a.get_game(gid)
    assert g["white_ms"] == 180000 and g["black_ms"] == 180000
    # sıra dışı hamle
    try:
        bl[0].play_move(gid, bl[1], "d7d5", 0)
        raise AssertionError("sıra kontrolü yok")
    except zdb.GameError:
        pass
    # geçersiz hamle
    try:
        w[0].play_move(gid, w[1], "e4e6", 0)
        raise AssertionError("geçersiz hamle kabul edildi")
    except zdb.GameError:
        pass
    # saat + artış
    w[0].play_move(gid, w[1], "g1f3", 5000)
    g = a.get_game(gid)
    assert g["white_ms"] == 180000 - 5000 + 2000, g["white_ms"]
    # geri alma: siyah hamle yapmadan beyaz ister → 1 hamle geri
    w[0].offer_takeback(gid, w[1])
    bl[0].answer_takeback(gid, bl[1], True)
    assert a.get_game(gid)["moves"] == "e2e4 e7e5"
    w[0].play_move(gid, w[1], "g1f3", 1000)
    bl[0].play_move(gid, bl[1], "b8c6", 1000)
    # beyaz isterse ve sıra beyazdaysa → 2 hamle geri
    w[0].offer_takeback(gid, w[1])
    bl[0].answer_takeback(gid, bl[1], True)
    assert a.get_game(gid)["moves"] == "e2e4 e7e5"
    # reddedilen geri alma
    w[0].play_move(gid, w[1], "g1f3", 1000)
    w[0].offer_takeback(gid, w[1])
    bl[0].answer_takeback(gid, bl[1], False)
    assert a.get_game(gid)["moves"] == "e2e4 e7e5 g1f3" and not a.get_game(gid)["takeback_offer"]
    # beraberlik teklifi → hamle yapınca düşer
    w[0].offer_draw(gid, w[1])
    bl[0].play_move(gid, bl[1], "b8c6", 1000)
    assert a.get_game(gid)["draw_offer"] == ""  # rakip hamle yapınca teklif reddedilmiş sayılır
    w[0].play_move(gid, w[1], "f1c4", 1000)
    bl[0].offer_draw(gid, bl[1])
    w[0].answer_draw(gid, w[1], False)
    assert a.get_game(gid)["draw_offer"] == "" and a.get_game(gid)["status"] == "started"
    # süre ver
    before = a.get_game(gid)
    key = "black_ms" if w[1] == before["white"] else "white_ms"
    w[0].give_time(gid, w[1])
    assert a.get_game(gid)[key] == before[key] + 15000
    bl[0].play_move(gid, bl[1], "f8c5", 1000)
    w[0].play_move(gid, w[1], "d1e2", 1000)
    bl[0].play_move(gid, bl[1], "g8f6", 1000)
    # pes et
    bl[0].resign(gid, bl[1])
    g = a.get_game(gid)
    assert g["status"] == "finished" and g["reason"] == "resign"
    assert g["result"] == ("1-0" if g["white"] == w[1] else "0-1")
    assert g["white_diff"] == 20 and g["black_diff"] == -20, (g["white_diff"], g["black_diff"])
    assert a._rating(a.con, w[1], "blitz") == (1520, 1)
    # rövanş: renkler değişir
    a.offer_rematch(gid, A)
    b.offer_rematch(gid, B)
    nid = a.get_game(gid)["rematch_id"]
    ng = a.get_game(nid)
    assert ng["white"] == g["black"] and ng["black"] == g["white"]
    # iptal (ilk iki hamleden önce) → puan değişmez
    a.abort(nid, A)
    assert a.get_game(nid)["status"] == "aborted"
    assert a._rating(a.con, w[1], "blitz") == (1520, 1)
    # meydan okuma + red
    sid = a.create_seek(A, 60, 0, False, "white", "bora")
    assert b.poll_lobby(B)["incoming"][0]["id"] == sid
    b.decline_seek(B, sid)
    assert a.poll_lobby(A, sid)["mine"]["declined"] == 1
    # meydan okuma + kabul (A beyaz)
    sid = a.create_seek(A, 60, 0, False, "white", "Bora")
    gid = b.accept_seek(B, sid)
    g = a.get_game(gid)
    assert g["white"] == A and g["speed"] == "bullet" and not g["rated"]
    # süre bitimi: beyazın süresi düşünürken bitiyor
    a.play_move(gid, A, "e2e4", 0)
    b.play_move(gid, B, "e7e5", 0)
    a.play_move(gid, A, "g1f3", 70000)
    g = a.get_game(gid)
    assert g["status"] == "finished" and g["reason"] == "timeout" and g["result"] == "0-1"
    # rakibin bayrağını düşürme bildirimi
    sid = a.create_seek(A, 60, 0, False, "white", "Bora")
    gid = b.accept_seek(B, sid)
    a.play_move(gid, A, "e2e4", 0)
    b.play_move(gid, B, "e7e5", 0)
    b.claim_timeout(gid, "w", 1)          # eski hamle sayısı → yok sayılır
    assert a.get_game(gid)["status"] == "started"
    b.claim_timeout(gid, "w", 2)
    g = a.get_game(gid)
    assert g["status"] == "finished" and g["result"] == "0-1" and g["white_ms"] == 0
    # profil
    pr = a.profile("BORA")
    assert pr["name"] == "Bora" and pr["wins"] + pr["losses"] + pr["draws"] == 3
    # mat ile bitiş
    sid = a.create_seek(A, 300, 0, True, "white", "Bora")
    gid = b.accept_seek(B, sid)
    for i, u in enumerate("e2e4 e7e5 f1c4 b8c6 d1h5 g8f6 h5f7".split()):
        (a if i % 2 == 0 else b).play_move(gid, A if i % 2 == 0 else B, u, 100)
    g = a.get_game(gid)
    assert g["status"] == "finished" and g["reason"] == "mate" and g["result"] == "1-0"
    # iki oyun aynı anda olmaz
    sid = a.create_seek(A, 300, 0, True, "random", None)
    gid = b.accept_seek(B, sid)
    try:
        a.create_seek(A, 300, 0, True)
        raise AssertionError("ikinci oyun engellenmedi")
    except zdb.GameError:
        pass
    a.resign(gid, A)  # 0 hamle → iptal
    assert a.get_game(gid)["status"] == "aborted"
    # hız ölçümü: tek yoklama
    t = time.perf_counter()
    for _ in range(50):
        a.poll_game(gid)
    ms = (time.perf_counter() - t) / 50 * 1000
    a.close()
    b.close()
    print("DB OK (yoklama %.2f ms)" % ms)


if __name__ == "__main__":
    test_rules()
    test_db()
    print("TÜM TESTLER OK")
