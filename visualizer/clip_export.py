"""Server-side WebM clip generator for AoE2 replays.

Given a parsed mgz match + a focus player, produce a short (<=30s) WebM that:
  - clips to the biggest engagements (battle clusters), skipping idle stretches,
  - plays at 8x,
  - draws a timeline bar at the bottom so viewers see what was skipped,
  - returns the path to the .webm.

Pure Python (Pillow isometric renderer + ffmpeg) -- no headless browser, so it runs
on the python-slim deploy. Units are drawn as player-colored markers (military =
triangle, villager = dot); the focus player is outlined. Buildings = small diamonds.

build_clip(match, focus_player, out_path) -> out_path
"""
import os
import math
import shutil
import struct
import subprocess
import tempfile
from collections import defaultdict

from PIL import Image, ImageDraw

# ---- output / timing config -------------------------------------------------
W, H = 960, 540          # 16:9, Discord-friendly
FPS = 20
SPEED = 8.0              # 8x game-speed
MAX_OUT_SEC = 30.0       # hard cap on the clip length
TL_H = 26                # timeline bar height (bottom)
MARGIN = 8

PLAYER_COLORS = {0: "#2f6fdb", 1: "#d33b3b", 2: "#33c04a", 3: "#f2d11b",
                 4: "#15c2c2", 5: "#d055d0", 6: "#9a9a9a", 7: "#f08a25"}


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _at(a):
    return str(a.type).replace("Action.", "")


# ---------------------------------------------------------------------------
# 1. unit position timelines + attack events
# ---------------------------------------------------------------------------
def _build(match):
    try:
        import unit_classifier as uc
        type_map, remap = uc.build_type_map(match)
    except Exception:
        type_map, remap = {}, {}

    def canon(o):
        return remap.get(o, o)

    pcolor = {}
    for p in match.players:
        pcolor[p.name] = _hex(PLAYER_COLORS.get(getattr(p, "color_id", 0), "#cccccc"))

    units = {}          # cid -> {player, color, mil, moves:[(t,x,y)], birth, death}
    attacks = []        # (t, x, y, player)
    dim = getattr(match.map, "dimension", 220)

    # seed starting units with their real spawn point
    for p in match.players:
        for o in (p.objects or []):
            sp = getattr(o, "position", None)
            cid = canon(o.instance_id)
            mil = not (o.name and "villager" in o.name.lower())
            units[cid] = {"player": p.name, "color": pcolor.get(p.name, (200, 200, 200)),
                          "mil": mil, "moves": [], "birth": 0.0, "death": None}
            if sp is not None:
                units[cid]["moves"].append((0.0, sp.x, sp.y))

    for a in match.actions:
        if not a.player:
            continue
        at = _at(a)
        t = a.timestamp.total_seconds()
        pl = a.player.name
        pay = a.payload or {}
        pos = getattr(a, "position", None)
        x, y = (pos.x, pos.y) if pos is not None else (None, None)
        tgt = pay.get("target_id")
        ids = [canon(o) for o in pay.get("object_ids", [])]
        is_attack = at == "ORDER" and isinstance(tgt, int)
        if at in ("MOVE", "ORDER", "PATROL", "DE_ATTACK_MOVE", "GUARD") and x is not None and y is not None:
            for cid in ids:
                u = units.get(cid)
                if u is None:
                    mil = type_map.get(cid, "") != "villager"
                    u = units[cid] = {"player": pl, "color": pcolor.get(pl, (200, 200, 200)),
                                      "mil": mil, "moves": [], "birth": t, "death": None}
                u["moves"].append((t, float(x), float(y)))
            if is_attack and len(ids) >= 1:
                attacks.append((t, float(x), float(y), pl))
        elif at == "DE_ATTACK_MOVE" and x is not None and y is not None:
            attacks.append((t, float(x), float(y), pl))

    for u in units.values():
        u["moves"].sort()
        if u["moves"]:
            u["birth"] = min(u["birth"], u["moves"][0][0])
    attacks.sort()
    return units, attacks, dim


def _pos(u, t):
    """Interpolated (x,y) of a unit at time t, or None if not yet present."""
    mv = u["moves"]
    if not mv or t < u["birth"]:
        return None
    if u["death"] is not None and t > u["death"]:
        return None
    if t <= mv[0][0]:
        return mv[0][1], mv[0][2]
    if t >= mv[-1][0]:
        return mv[-1][1], mv[-1][2]
    lo, hi = 0, len(mv) - 1
    while lo + 1 < hi:
        m = (lo + hi) // 2
        if mv[m][0] <= t:
            lo = m
        else:
            hi = m
    (t0, x0, y0), (t1, x1, y1) = mv[lo], mv[lo + 1]
    f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


# ---------------------------------------------------------------------------
# 2. engagement detection + window selection
# ---------------------------------------------------------------------------
def _windows(attacks, duration, budget_game_sec):
    """Pick time windows (start,end) covering the most attack-dense stretches,
    totalling <= budget_game_sec. Returns sorted, merged windows."""
    if not attacks:
        # no battles: just take the opening + a mid sample
        return [(0.0, min(budget_game_sec, duration))]
    BIN = 6.0
    bins = defaultdict(int)
    for t, _x, _y, _p in attacks:
        bins[int(t // BIN)] += 1
    # score each bin, take the densest until budget filled, expand to +-1 bin
    order = sorted(bins, key=lambda b: -bins[b])
    chosen = []
    total = 0.0
    for b in order:
        s = max(0.0, (b - 1) * BIN)
        e = min(duration, (b + 2) * BIN)
        chosen.append((s, e))
        total += e - s
        if total >= budget_game_sec:
            break
    chosen.sort()
    # merge overlaps
    merged = []
    for s, e in chosen:
        if merged and s <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


# ---------------------------------------------------------------------------
# 3. render
# ---------------------------------------------------------------------------
def _projector(dim):
    tw = min(4.0, (W - 2 * MARGIN) / dim)
    th = tw / 2.0
    ox = W / 2 - dim * tw / 2
    oy = (H - TL_H) / 2

    def proj(x, y):
        return (x + y) * tw / 2 + ox, (y - x) * th / 2 + oy
    return proj, tw, th


def _terrain_bg(match, dim, proj, tw, th):
    img = Image.new("RGB", (W, H), (24, 28, 22))
    d = ImageDraw.Draw(img)
    try:
        mp = match.map
        # water/grass two-tone from terrain ids; cheap dominant-color fill
        from server import _terrain_hex, _load_terrain_names  # reuse palette logic
        names = _load_terrain_names(getattr(match, "dataset_id", 100))
        step = max(1, dim // 200)
        for ty in range(0, dim, step):
            for tx in range(0, dim, step):
                pass  # filled below via tiles list
        tiles = getattr(mp, "tiles", None) or []
        for tile in tiles:
            tx, tyy = tile.position.x, tile.position.y
            col = _terrain_hex(names.get(tile.terrain, "") if names else "")
            px, py = proj(tx, tyy)
            d.polygon([(px, py - th / 2), (px + tw / 2, py), (px, py + th / 2), (px - tw / 2, py)],
                      fill=_hex(col))
    except Exception:
        # plain grass diamond if terrain unavailable
        pts = [proj(0, 0), proj(dim, 0), proj(dim, dim), proj(0, dim)]
        d.polygon(pts, fill=(70, 110, 55))
    return img


def _frame(bg, units, attacks, proj, t, focus, tl):
    img = bg.copy()
    d = ImageDraw.Draw(img, "RGBA")
    # recent attack flashes
    for (at_, ax, ay, _p) in attacks:
        dt = t - at_
        if 0 <= dt < 1.2:
            px, py = proj(ax, ay)
            r = 5 + 10 * dt
            a = int(180 * (1 - dt / 1.2))
            d.ellipse([px - r, py - r, px + r, py + r], outline=(255, 220, 120, a), width=2)
    # units
    for u in units.values():
        p = _pos(u, t)
        if p is None:
            continue
        px, py = proj(*p)
        c = u["color"]
        foc = (u["player"] == focus)
        if u["mil"]:
            s = 4 if foc else 3
            d.polygon([(px, py - s), (px - s, py + s), (px + s, py + s)],
                      fill=c, outline=(255, 255, 255, 200) if foc else None)
        else:
            s = 2.5
            d.ellipse([px - s, py - s, px + s, py + s], fill=c)
    # timeline bar
    _timeline(d, t, tl)
    return img


def _timeline(d, t, tl):
    duration, windows, seg_map = tl
    y0 = H - TL_H + 4
    y1 = H - 6
    x0, x1 = MARGIN, W - MARGIN
    d.rectangle([x0, y0, x1, y1], fill=(40, 44, 50, 230), outline=(90, 96, 105, 255))
    span = x1 - x0
    # shown windows (skips = the gaps)
    for s, e in windows:
        sx = x0 + span * (s / duration)
        ex = x0 + span * (e / duration)
        d.rectangle([sx, y0, ex, y1], fill=(70, 130, 200, 200))
    # playhead at the unit-time t (real game time)
    hx = x0 + span * (t / duration)
    d.line([(hx, y0 - 2), (hx, y1 + 2)], fill=(255, 230, 120, 255), width=2)


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()      # bundled binary -> no apt dependency
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def _encode(frames_dir, out_path):
    cmd = [_ffmpeg_exe(), "-y", "-framerate", str(FPS),
           "-i", os.path.join(frames_dir, "f%05d.png"),
           "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34", "-pix_fmt", "yuv420p",
           "-row-mt", "1", "-an", out_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_clip(match, focus_player, out_path):
    duration = match.duration.total_seconds()
    units, attacks, dim = _build(match)
    budget_game = MAX_OUT_SEC * SPEED                 # game-seconds we can show
    windows = _windows(attacks, duration, budget_game)
    shown = sum(e - s for s, e in windows)
    if shown > budget_game:                            # trim last window
        over = shown - budget_game
        s, e = windows[-1]
        windows[-1] = (s, max(s, e - over))
    proj, tw, th = _projector(dim)
    bg = _terrain_bg(match, dim, proj, tw, th)
    tl = (duration, windows, None)

    tmp = tempfile.mkdtemp(prefix="clip_")
    try:
        fi = 0
        dt = SPEED / FPS                                # game-seconds advanced per frame
        for (s, e) in windows:
            t = s
            while t < e:
                img = _frame(bg, units, attacks, proj, t, focus_player, tl)
                img.save(os.path.join(tmp, f"f{fi:05d}.png"))
                fi += 1
                t += dt
        if fi == 0:
            raise RuntimeError("no frames")
        _encode(tmp, out_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path
