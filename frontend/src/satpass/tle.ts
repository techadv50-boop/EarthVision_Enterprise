/** Rebuild a TLE to the 69-character column layout SGP4 requires. */

function checksumDigit(line: string): string {
  let sum = 0;
  const body = line.slice(0, 68);
  for (const ch of body) {
    if (ch >= '0' && ch <= '9') sum += Number(ch);
    else if (ch === '-') sum += 1;
  }
  return String(sum % 10);
}

function padRight(s: string, n: number): string {
  const t = s.trim();
  return t.length >= n ? t.slice(0, n) : t.padEnd(n, ' ');
}

function padLeft(s: string, n: number): string {
  const t = s.trim();
  return t.length >= n ? t.slice(-n) : t.padStart(n, ' ');
}

function field10(raw: string): string {
  const t = raw.trim();
  if (t.startsWith('-') || t.startsWith('+')) return padLeft(t, 10);
  return padLeft(t, 10);
}

function field8(raw: string): string {
  return padLeft(raw.trim(), 8);
}

function parseLine1(line: string): string | null {
  const t = line.replace(/\r/g, '').trim();
  if (t.length === 69 && t.startsWith('1 ')) return t;
  const parts = t.split(/\s+/);
  if (parts[0] !== '1' || parts.length < 8) return null;

  let satnum = '';
  let cls = 'U';
  let idx = 1;
  if (/^\d{5}[A-Z]$/.test(parts[1])) {
    satnum = parts[1].slice(0, 5);
    cls = parts[1].slice(5);
    idx = 2;
  } else if (/^\d{5}$/.test(parts[1]) && /^[A-Z]$/.test(parts[2] || '')) {
    satnum = parts[1];
    cls = parts[2];
    idx = 3;
  } else {
    return null;
  }

  const intl = parts[idx++];
  const epoch = parts[idx++];
  const ndot = parts[idx++];
  const nddot = parts[idx++];
  const bstar = parts[idx++];
  const eph = parts[idx++];
  const tail = parts[idx] || '';
  if (!intl || !epoch || !ndot || !nddot || !bstar || eph == null || !tail) return null;
  if (!/^\d{5}\.\d+$/.test(epoch)) return null;

  const digits = tail.replace(/\D/g, '');
  const elnum = digits.length > 1 ? digits.slice(0, -1) : digits;

  const body =
    `1 ${satnum.padStart(5, '0')}${cls} ${padRight(intl, 8)} ${padLeft(epoch, 14)} ` +
    `${field10(ndot)} ${field8(nddot)} ${field8(bstar)} ${eph} ${padLeft(elnum, 4)}`;
  if (body.length !== 68) return null;
  return body + checksumDigit(body);
}

function parseLine2(line: string): string | null {
  const t = line.replace(/\r/g, '').trim();
  if (t.length === 69 && t.startsWith('2 ')) return t;
  const parts = t.split(/\s+/);
  if (parts[0] !== '2' || parts.length < 8) return null;
  const satnum = parts[1];
  const inc = parts[2];
  const raan = parts[3];
  const ecc = parts[4];
  const argp = parts[5];
  const ma = parts[6];
  let motion = parts[7];
  let rev = parts[8] || '';
  if (!rev && motion.length >= 16) {
    rev = motion.slice(11);
    motion = motion.slice(0, 11);
  }
  const revDigits = rev.replace(/\D/g, '');
  const revnum = revDigits.length > 5 ? revDigits.slice(0, 5) : revDigits.slice(0, 5);
  if (!/^\d{5}$/.test(satnum)) return null;

  const body =
    `2 ${satnum.padStart(5, '0')} ${padLeft(inc, 8)} ${padLeft(raan, 8)} ${padLeft(ecc, 7)} ` +
    `${padLeft(argp, 8)} ${padLeft(ma, 8)} ${padLeft(motion, 11)}${padLeft(revnum, 5)}`;
  if (body.length !== 68) return null;
  return body + checksumDigit(body);
}

/** Return column-aligned TLE lines, or the trimmed originals if they cannot be rebuilt. */
export function canonicalizeTle(line1: string, line2: string): { line1: string; line2: string } {
  return {
    line1: parseLine1(line1) ?? line1.trim(),
    line2: parseLine2(line2) ?? line2.trim(),
  };
}
