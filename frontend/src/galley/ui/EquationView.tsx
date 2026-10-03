import type { EquationAtom } from "../types";

export function EquationView({ atoms, number }: { atoms: EquationAtom[]; number?: string }) {
  return (
    <p className="equation-line">
      {atoms.map((atom, index) => {
        if (atom.kind === "sup") return <sup key={index}>{atom.value}</sup>;
        if (atom.kind === "sub") return <sub key={index}>{atom.value}</sub>;
        if (atom.kind === "frac") {
          return (
            <span key={index} className="frac">
              <span>{atom.num}</span>
              <span>{atom.den}</span>
            </span>
          );
        }
        return <span key={index}>{atom.value}</span>;
      })}
      {number ? <span> ({number})</span> : null}
    </p>
  );
}
