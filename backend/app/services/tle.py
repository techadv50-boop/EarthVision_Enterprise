"""Rebuild a TLE to the 69-character column layout SGP4 requires."""

from __future__ import annotations


def _checksum_digit(line: str) -> str:
    total = 0
    for ch in line[:68]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return str(total % 10)


def _pad_right(s: str, n: int) -> str:
    t = s.strip()
    return t[:n] if len(t) >= n else t.ljust(n)


def _pad_left(s: str, n: int) -> str:
    t = s.strip()
    return t[-n:] if len(t) >= n else t.rjust(n)


def _field10(raw: str) -> str:
    t = raw.strip()
    if t.startswith("-") or t.startswith("+"):
        return _pad_left(t, 10)
    return _pad_left(t, 10)


def _field8(raw: str) -> str:
    return _pad_left(raw.strip(), 8)


def canonicalize_line1(line: str) -> str:
    t = (line or "").replace("\r", "").strip()
    if len(t) == 69 and t.startswith("1 "):
        return t
    parts = t.split()
    if not parts or parts[0] != "1" or len(parts) < 8:
        return t
    idx = 1
    if len(parts[1]) == 6 and parts[1][:5].isdigit() and parts[1][5].isalpha():
        satnum, cls = parts[1][:5], parts[1][5]
        idx = 2
    elif parts[1].isdigit() and len(parts) > 2 and len(parts[2]) == 1 and parts[2].isalpha():
        satnum, cls = parts[1], parts[2]
        idx = 3
    else:
        return t
    try:
        intl, epoch, ndot, nddot, bstar, eph, tail = parts[idx : idx + 7]
    except ValueError:
        return t
    if not epoch or "." not in epoch:
        return t
    digits = "".join(ch for ch in tail if ch.isdigit())
    elnum = digits[:-1] if len(digits) > 1 else digits
    body = (
        f"1 {satnum.zfill(5)}{cls} {_pad_right(intl, 8)} {_pad_left(epoch, 14)} "
        f"{_field10(ndot)} {_field8(nddot)} {_field8(bstar)} {eph} {_pad_left(elnum, 4)}"
    )
    if len(body) != 68:
        return t
    return body + _checksum_digit(body)


def canonicalize_line2(line: str) -> str:
    t = (line or "").replace("\r", "").strip()
    if len(t) == 69 and t.startswith("2 "):
        return t
    parts = t.split()
    if not parts or parts[0] != "2" or len(parts) < 8:
        return t
    satnum, inc, raan, ecc, argp, ma, motion = parts[1:8]
    rev = parts[8] if len(parts) > 8 else ""
    if not rev and len(motion) >= 16:
        rev, motion = motion[11:], motion[:11]
    rev_digits = "".join(ch for ch in rev if ch.isdigit())[:5]
    if not satnum.isdigit():
        return t
    body = (
        f"2 {satnum.zfill(5)} {_pad_left(inc, 8)} {_pad_left(raan, 8)} {_pad_left(ecc, 7)} "
        f"{_pad_left(argp, 8)} {_pad_left(ma, 8)} {_pad_left(motion, 11)}{_pad_left(rev_digits, 5)}"
    )
    if len(body) != 68:
        return t
    return body + _checksum_digit(body)


def canonicalize_tle_line(line: str) -> str:
    raw = (line or "").strip()
    if raw.startswith("1 "):
        return canonicalize_line1(raw)
    if raw.startswith("2 "):
        return canonicalize_line2(raw)
    return raw
