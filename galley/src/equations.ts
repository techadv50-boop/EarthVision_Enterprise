export type EquationAtom =
  | { kind: "text"; value: string }
  | { kind: "sup"; value: string }
  | { kind: "sub"; value: string }
  | { kind: "frac"; num: string; den: string };

export function atomsFromOcr(text: string): EquationAtom[] {
  const tokens = text.replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  const atoms: EquationAtom[] = [];
  tokens.forEach((token, index) => {
    const spacer = index < tokens.length - 1 ? " " : "";
    const sup = token.match(/^(.*?)\^(?:\{([^}]+)\}|([A-Za-z0-9+\-]+))$/);
    const sub = token.match(/^(.*?)_(?:\{([^}]+)\}|([A-Za-z0-9+\-]+))$/);
    const frac = token.match(/^([A-Za-z0-9+\-]+)\/([A-Za-z0-9+\-]+)$/);
    if (sup && (sup[1] || sup[2] || sup[3])) {
      if (sup[1]) atoms.push({ kind: "text", value: sup[1] });
      atoms.push({ kind: "sup", value: sup[2] || sup[3] });
      if (spacer) atoms.push({ kind: "text", value: spacer });
      return;
    }
    if (sub && (sub[1] || sub[2] || sub[3])) {
      if (sub[1]) atoms.push({ kind: "text", value: sub[1] });
      atoms.push({ kind: "sub", value: sub[2] || sub[3] });
      if (spacer) atoms.push({ kind: "text", value: spacer });
      return;
    }
    if (frac) {
      atoms.push({ kind: "frac", num: frac[1], den: frac[2] });
      if (spacer) atoms.push({ kind: "text", value: spacer });
      return;
    }
    atoms.push({ kind: "text", value: token });
    if (spacer) atoms.push({ kind: "text", value: spacer });
  });
  return atoms;
}
