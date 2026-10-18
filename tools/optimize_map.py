#!/usr/bin/env python3
"""Offline optimizer for AssaultCube maps (format 9, .cgz).

Does what the game does on `/savemapoptimised` (voptimize + mapmrproper in
AC's world.cpp/worldio.cpp): wall/upper-wall textures of cubes where they can
never be seen are set to neighbouring values, so the engine's mipmapper can
merge more cubes into larger "perfect mips" and render fewer quads per frame.
Visible geometry, textures, entities and lighting are not changed, except that
exact duplicate entities (same type, position and attributes) are dropped.

With --lite (for weak machines) it also thins out decoration mapmodels that are
placed many times (rows of trees, fences, ...): of every model used at least
LITE_MIN_COUNT times, only copies at least LITE_SPACING cubes apart are kept.
Mapmodels are drawn whenever they are in view and open maps hide almost
nothing, so this is usually the biggest saving. It changes how the map looks,
so write it to a separate map (which needs a copy of the original map's .cfg).

usage: optimize_map.py [--lite] in.cgz [out.cgz]   (default: overwrite in.cgz)
"""
import gzip
import struct
import sys

HEADERSIZE = 980
SOLID, CORNER, FHF, CHF, SPACE, SEMISOLID = range(6)
SMALLEST_FACTOR = 6
INVISWTEX, INVISUTEX, INVISIBLE = 1, 2, 4
MAPMODEL = 10
LITE_MIN_COUNT = 20
LITE_SPACING = 6


class Sqr:
    __slots__ = ('type', 'floor', 'ceil', 'wtex', 'ftex', 'ctex', 'vdelta', 'utex', 'tag', 'defer', 'visible')

    def __init__(self, type, floor=0, ceil=16, wtex=0, ftex=0, ctex=0, vdelta=0, utex=0, tag=0):
        self.type, self.floor, self.ceil = type, floor, ceil
        self.wtex, self.ftex, self.ctex, self.vdelta, self.utex, self.tag = wtex, ftex, ctex, vdelta, utex, tag
        self.defer = self.visible = 0

    def copy(self):
        return Sqr(self.type, self.floor, self.ceil, self.wtex, self.ftex, self.ctex, self.vdelta, self.utex, self.tag)


def signed(b):
    return b - 256 if b > 127 else b


def load(path):
    data = gzip.open(path).read()
    head, version, headersize, sfactor, numents = struct.unpack_from('<4s4i', data)
    if head != b'ACMP' or version != 9 or headersize != HEADERSIZE:
        sys.exit('%s: only AssaultCube map format 9 is supported' % path)
    p = HEADERSIZE
    ents = [struct.unpack_from('<4h4B', data, p + 12 * i) for i in range(numents)]
    p += 12 * numents
    world, t = [], None
    while len(world) < 1 << (2 * sfactor):  # see load_world() in AC's worldio.cpp
        type = data[p]; p += 1
        if type == 255:
            world.extend(t.copy() for _ in range(data[p])); p += 1
            continue
        if type == SOLID:
            t = Sqr(SOLID, wtex=data[p], vdelta=data[p + 1], utex=data[p]); p += 2
        else:
            fl, ce, wt, ft, ct, vd, ut, tg = data[p:p + 8]; p += 8
            t = Sqr(type, signed(fl), signed(ce), wt, ft, ct, vd, ut, tg)
        world.append(t.copy())
    return data[:HEADERSIZE], sfactor, ents, world, data[p:]


def save(path, header, sfactor, ents, world, trailer):
    out = bytearray(header)
    struct.pack_into('<i', out, 16, len(ents))
    for e in ents:
        out += struct.pack('<4h4B', *e)
    t, sc = None, 0  # rlencodecubes() in AC's worldio.cpp

    def spurge():
        nonlocal sc
        while sc:
            n = min(sc, 255)
            out.extend((255, n))
            sc -= n
    for s in world:
        if s.type == SOLID:
            if t and t.type == SOLID and s.wtex == t.wtex and s.vdelta == t.vdelta:
                sc += 1
            else:
                spurge()
                out.extend((s.type, s.wtex, s.vdelta))
        else:
            if t and all(getattr(s, f) == getattr(t, f) for f in ('type', 'floor', 'ceil', 'ctex', 'ftex', 'utex', 'wtex', 'vdelta', 'tag')):
                sc += 1
            else:
                spurge()
                out.extend((s.type, s.floor & 255, s.ceil & 255, s.wtex, s.ftex, s.ctex, s.vdelta, s.utex, s.tag))
        t = s
    spurge()
    out += trailer
    with gzip.open(path, 'wb', compresslevel=9) as f:
        f.write(bytes(out))


def remip(wmip, sfactor):
    """Rebuild all mip levels from wmip[0] (remip() in AC's world.cpp, ignoring light)."""
    for level in range(SMALLEST_FACTOR):
        w, wsize = wmip[level], 1 << (sfactor - level)
        vsize = wsize >> 1
        v = wmip[level + 1] = [None] * (vsize * vsize)
        for y in range(0, wsize, 2):
            for x in range(0, wsize, 2):
                o = [w[y * wsize + x], w[y * wsize + x + 1], w[(y + 1) * wsize + x + 1], w[(y + 1) * wsize + x]]
                r = o[0].copy()
                r.type = o[0].type if all(q.type == o[0].type for q in o) else SEMISOLID
                if r.type != SOLID:
                    open_ = [q for q in o if q.type != SOLID]
                    r.floor = min(q.floor for q in open_)
                    r.ceil = max(q.ceil for q in open_)
                r.defer = 1
                if not (level and any(q.defer for q in o)):
                    if r.type == SOLID:
                        r.defer = int(any(q.wtex != o[0].wtex for q in o))
                    else:
                        r.defer = int(any((q.type, q.floor, q.ceil, q.wtex, q.ftex, q.ctex, q.utex) !=
                                          (o[0].type, o[0].floor, o[0].ceil, o[0].wtex, o[0].ftex, o[0].ctex, o[0].utex) for q in o[1:]))
                v[(y >> 1) * vsize + (x >> 1)] = r


def countperfectmips(wmip, sfactor):
    stats = [0] * (SMALLEST_FACTOR + 1)

    def count(mip, xx, yy, bs):
        size = 1 << (sfactor - mip)
        for y in range(yy, yy + bs):
            for x in range(xx, xx + bs):
                if wmip[mip][y * size + x].defer and mip > 0:
                    count(mip - 1, x * 2, y * 2, 2)
                else:
                    stats[mip] += 1
    count(SMALLEST_FACTOR, 0, 0, 1 << (sfactor - SMALLEST_FACTOR))
    return stats


def calcworldvisibility(world, ssize):
    """Flag cubes whose wall/upper-wall texture is never rendered (calcworldvisibility() in AC's world.cpp)."""
    S = lambda x, y: world[y * ssize + x]
    for s in world:
        s.visible = INVISUTEX | INVISWTEX
    for y in range(1, ssize - 1):
        for x in range(1, ssize - 1):
            s = S(x, y)
            for q in (S(x, y - 1), S(x, y + 1), S(x + 1, y), S(x - 1, y)):
                if q.type != SOLID:
                    if s.type == SOLID or s.floor > q.floor:
                        s.visible &= ~INVISWTEX  # render_wall() draws o->wtex
                    if s.type != SOLID and s.ceil < q.ceil:
                        s.visible &= ~INVISUTEX  # render_wall() draws o->utex


def optimize(world, sfactor):
    """Set invisible wtex/utex so that as many cubes as possible end up in perfect mips.

    Same idea as AC's mapmrproper(), but textures are assigned top-down over the idealized
    mipmap: every block that can become a perfect mip (geometry matches and at most one distinct
    visible texture) is made uniform, so no mip that was perfect before can get broken.
    """
    ssize = 1 << sfactor
    if any(s.type in (CORNER, FHF, CHF) for s in world):
        sys.exit('corners and heightfields are not supported by this tool, use /savemapoptimised in game')

    # voptimize(): vdelta is meaningless without heightfields
    for s in world:
        s.vdelta = 0

    calcworldvisibility(world, ssize)

    # idealized mipmap without considering light or utex/wtex -> we'll try to reach this by optimization
    ideal = [s.copy() for s in world]
    for s in ideal:
        s.wtex = s.utex = 0
    wmip = [ideal] + [None] * SMALLEST_FACTOR
    remip(wmip, sfactor)

    locked = [False] * len(world)  # part of a block that has to stay uniform
    for attr, flag, solidtoo in (('wtex', INVISWTEX, True), ('utex', INVISUTEX, False)):
        def assign(mip, x, y):
            cubes = [(yy * ssize + xx) for yy in range(y << mip, (y + 1) << mip) for xx in range(x << mip, (x + 1) << mip)]
            if mip and wmip[mip][y * (ssize >> mip) + x].defer:
                for i in range(4):
                    assign(mip - 1, x * 2 + (i & 1), y * 2 + i // 2)
                return
            if not solidtoo and world[cubes[0]].type == SOLID:
                return  # solids have no upper wall
            visible = {getattr(world[i], attr) for i in cubes if not world[i].visible & flag}
            if len(visible) > 1:
                for i in range(4):
                    assign(mip - 1, x * 2 + (i & 1), y * 2 + i // 2)
                return
            if visible:
                value = visible.pop()
            else:  # nothing visible: keep the most common value
                values = [getattr(world[i], attr) for i in cubes]
                value = max(set(values), key=values.count)
            for i in cubes:
                setattr(world[i], attr, value)
                if mip:
                    locked[i] = True
        top = ssize >> SMALLEST_FACTOR
        for y in range(top):
            for x in range(top):
                assign(SMALLEST_FACTOR, x, y)

    # cubes outside any perfect mip: use the remaining invisibilities to help the run-length-encoder
    r = None
    for i, s in enumerate(world):
        free = not locked[i]
        if s.type == SOLID:
            if r and r.type == SOLID and free and s.visible & INVISWTEX:
                s.wtex = s.utex = r.wtex
            else:
                r = s
        else:
            if (r and free and all(getattr(s, f) == getattr(r, f) for f in ('type', 'floor', 'ceil', 'ctex', 'ftex', 'vdelta', 'tag'))
                    and (s.visible & INVISWTEX or s.wtex == r.wtex) and (s.visible & INVISUTEX or s.utex == r.utex)):
                s.wtex, s.utex = r.wtex, r.utex
            else:
                r = s
    for s in world:
        s.visible = 0


def mipstats(world, sfactor):
    wmip = [world] + [None] * SMALLEST_FACTOR
    remip(wmip, sfactor)
    return countperfectmips(wmip, sfactor)


def thin_mapmodels(ents):
    """Drop copies of often repeated mapmodels that are closer than LITE_SPACING to a kept copy."""
    counts = {}
    for e in ents:
        if e[4] == MAPMODEL:
            counts[e[5]] = counts.get(e[5], 0) + 1
    kept, out = {}, []
    for e in sorted(ents, key=lambda e: (e[0], e[1])):  # walk rows of models in order
        if e[4] == MAPMODEL and counts[e[5]] >= LITE_MIN_COUNT:
            near = kept.setdefault(e[5], [])
            if any(max(abs(e[0] - k[0]), abs(e[1] - k[1])) < LITE_SPACING for k in near):
                continue
            near.append(e)
        out.append(e)
    keep = set(map(id, out))
    return [e for e in ents if id(e) in keep]  # keep the original entity order


def main():
    args = sys.argv[1:]
    lite = '--lite' in args
    if lite:
        args.remove('--lite')
    if len(args) not in (1, 2):
        sys.exit(__doc__)
    src = args[0]
    dst = args[1] if len(args) == 2 else src
    header, sfactor, ents, world, trailer = load(src)
    before = mipstats(world, sfactor)

    unique = list(dict.fromkeys(ents))
    thinned = thin_mapmodels(unique) if lite else unique
    optimize(world, sfactor)
    after = mipstats(world, sfactor)
    save(dst, header, sfactor, thinned, world, trailer)

    print('removed %d duplicate entities' % (len(ents) - len(unique)))
    if lite:
        nmm = lambda l: sum(e[4] == MAPMODEL for e in l)
        print('mapmodels: %d -> %d' % (nmm(unique), nmm(thinned)))
    print('perfect mips (mip0..mip%d) before: %s = %d cells' % (SMALLEST_FACTOR, ' / '.join(map(str, before)), sum(before)))
    print('perfect mips (mip0..mip%d) after:  %s = %d cells' % (SMALLEST_FACTOR, ' / '.join(map(str, after)), sum(after)))


if __name__ == '__main__':
    main()
