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

const COMMANDS: Record<string, string> = {
  alpha: "α",
  beta: "β",
  gamma: "γ",
  delta: "δ",
  epsilon: "ε",
  theta: "θ",
  lambda: "λ",
  mu: "μ",
  pi: "π",
  sigma: "σ",
  omega: "ω",
  Sigma: "Σ",
  Omega: "Ω",
  Delta: "Δ",
  sum: "∑",
  int: "∫",
  sqrt: "√",
  infty: "∞",
  leq: "≤",
  geq: "≥",
  neq: "≠",
  times: "×",
  div: "÷",
  pm: "±",
  cdot: "·",
  rightarrow: "→",
  partial: "∂",
};

const SUP_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ";
const SUB_CHARS = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ᵢ";
const FROM_SUP: Record<string, string> = {
  "⁰": "0",
  "¹": "1",
  "²": "2",
  "³": "3",
  "⁴": "4",
  "⁵": "5",
  "⁶": "6",
  "⁷": "7",
  "⁸": "8",
  "⁹": "9",
  "⁺": "+",
  "⁻": "-",
  "⁼": "=",
  "⁽": "(",
  "⁾": ")",
  "ⁿ": "n",
  "ⁱ": "i",
};
const FROM_SUB: Record<string, string> = {
  "₀": "0",
  "₁": "1",
  "₂": "2",
  "₃": "3",
  "₄": "4",
  "₅": "5",
  "₆": "6",
  "₇": "7",
  "₈": "8",
  "₉": "9",
  "₊": "+",
  "₋": "-",
  "₌": "=",
  "₍": "(",
  "₎": ")",
  "ᵢ": "i",
};

export function parseMath(input: string): EquationAtom[] {
  const atoms: EquationAtom[] = [];
  const pushText = (value: string) => {
    if (!value) return;
    const last = atoms[atoms.length - 1];
    if (last?.kind === "text") last.value += value;
    else atoms.push({ kind: "text", value });
  };
  const readGroup = (from: number): { value: string; next: number } | null => {
    if (input[from] !== "{") return null;
    let depth = 0;
    for (let cursor = from; cursor < input.length; cursor += 1) {
      if (input[cursor] === "{") depth += 1;
      else if (input[cursor] === "}") {
        depth -= 1;
        if (depth === 0) return { value: input.slice(from + 1, cursor), next: cursor + 1 };
      }
    }
    return null;
  };
  const readToken = (from: number): { value: string; next: number } => {
    const group = readGroup(from);
    if (group) return group;
    const match = /[A-Za-z0-9]+/.exec(input.slice(from));
    if (match && match.index === 0) return { value: match[0], next: from + match[0].length };
    return { value: input[from] || "", next: from + 1 };
  };

  let index = 0;
  while (index < input.length) {
    if (input.startsWith("\\frac", index)) {
      const num = readGroup(index + 5);
      const den = num ? readGroup(num.next) : null;
      if (num && den) {
        atoms.push({ kind: "frac", num: num.value, den: den.value });
        index = den.next;
        continue;
      }
    }
    if (input[index] === "\\") {
      const name = /\\([A-Za-z]+)/.exec(input.slice(index));
      if (name) {
        pushText(COMMANDS[name[1]] || name[1]);
        index += name[0].length;
        continue;
      }
    }
    if (input[index] === "^" || input[index] === "_") {
      const kind = input[index] === "^" ? "sup" : "sub";
      const token = readToken(index + 1);
      if (token.value) atoms.push({ kind, value: token.value });
      index = token.next;
      continue;
    }
    if (SUP_CHARS.includes(input[index])) {
      let value = "";
      while (index < input.length && SUP_CHARS.includes(input[index])) {
        value += FROM_SUP[input[index]] || input[index];
        index += 1;
      }
      atoms.push({ kind: "sup", value });
      continue;
    }
    if (SUB_CHARS.includes(input[index])) {
      let value = "";
      while (index < input.length && SUB_CHARS.includes(input[index])) {
        value += FROM_SUB[input[index]] || input[index];
        index += 1;
      }
      atoms.push({ kind: "sub", value });
      continue;
    }
    if (input[index] === "/") {
      const last = atoms[atoms.length - 1];
      const tail = last?.kind === "text" ? /^(.*?)([A-Za-z0-9]+)$/.exec(last.value) : null;
      const next = tail ? readToken(index + 1) : null;
      if (last?.kind === "text" && tail && next && next.value && !/[/\\\s]/.test(next.value)) {
        last.value = tail[1];
        if (!last.value) atoms.pop();
        atoms.push({ kind: "frac", num: tail[2], den: next.value });
        index = next.next;
        continue;
      }
    }
    pushText(input[index]);
    index += 1;
  }
  return atoms.filter((atom) => atom.kind !== "text" || atom.value);
}

export function sourceFromAtoms(atoms: EquationAtom[]): string {
  return atoms
    .map((atom) => {
      if (atom.kind === "sup") return `^{${atom.value}}`;
      if (atom.kind === "sub") return `_{${atom.value}}`;
      if (atom.kind === "frac") return `\\frac{${atom.num}}{${atom.den}}`;
      return atom.value;
    })
    .join("");
}
