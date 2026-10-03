export type IconAsset = {
  id: string;
  name: string;
  dataUrl: string;
  widthPx: number;
  heightPx: number;
};

export type Journal = {
  id: string;
  name: string;
  abbreviation: string;
  issnP: string;
  issnE: string;
  topIcons: IconAsset[];
  partnerIcons: IconAsset[];
};

export type Author = {
  id: string;
  name: string;
  affiliation: string;
  corresponding: boolean;
  email: string;
};

export type HeadingBlock = { id: string; type: "heading"; text: string };
export type ParagraphBlock = { id: string; type: "paragraph"; text: string };
export type FigureBlock = {
  id: string;
  type: "figure";
  dataUrl: string;
  widthPx: number;
  heightPx: number;
  caption: string;
};
export type TableBlock = {
  id: string;
  type: "table";
  caption: string;
  rows: string[][];
  landscape: boolean;
};
export type EquationBlock = { id: string; type: "equation"; text: string; number: string };
export type PageBreakBlock = { id: string; type: "pageBreak" };

export type BodyBlock =
  | HeadingBlock
  | ParagraphBlock
  | FigureBlock
  | TableBlock
  | EquationBlock
  | PageBreakBlock;

export type Galley = {
  id: string;
  journalId: string;
  title: string;
  authors: Author[];
  volume: string;
  issue: string;
  startPage: string;
  received: string;
  revised: string;
  accepted: string;
  published: string;
  abstract: string;
  keywords: string;
  topIcons: IconAsset[];
  partnerIcons: IconAsset[];
  blocks: BodyBlock[];
  updatedAt: number;
};

export type Store = {
  openAccessIcon: IconAsset | null;
  journals: Journal[];
  galleys: Galley[];
};
