export type PluginKind = 'builtin' | 'uploaded';

export interface ToolPlugin {
  id: string;
  name: string;
  description: string;
  version: string;
  service: string;
  route: string;
  icon: string;
  kind: PluginKind;
  enabled: boolean;
  entry?: string;
  overridden?: boolean;
  package?: string;
  uploaded_by?: string | null;
}

export const BUILTIN_PLUGINS: ToolPlugin[] = [
  {
    id: 'citation-assistant',
    name: 'Citation Assistant',
    description:
      'Journals assigned to this account, archive search, and new-manuscript house citations from papers already stored on this shelf.',
    version: '1.0.0',
    service: 'citation',
    route: '/journals',
    icon: 'book-open',
    kind: 'builtin',
    enabled: true,
    package: 'frontend journals + backend citations',
  },
  {
    id: 'article-review',
    name: 'Article Review / Comparison',
    description:
      'Compare the References section of the file you sent to staff with the file they returned. Review English with in-depth AI tools before publish.',
    version: '1.0.0',
    service: 'review',
    route: '/review',
    icon: 'git-compare',
    kind: 'builtin',
    enabled: true,
    package: 'frontend review pages + backend review routes',
  },
  {
    id: 'author-database',
    name: 'Author database',
    description:
      'Two wings: under process articles and published articles. Add OJS number, title, authors, emails, plagiarism, ORCID, review rounds, and galley dates.',
    version: '1.0.0',
    service: 'authors',
    route: '/authors',
    icon: 'clipboard-list',
    kind: 'builtin',
    enabled: true,
    package: 'frontend author pages + backend author_db',
  },
  {
    id: 'galley-composition',
    name: 'Galley composition',
    description:
      'Choose a journal, fill the first page and body, and save a Word proof. The same account used for citations opens this desk — no second username or password.',
    version: '1.0.0',
    service: 'galley',
    route: '/galley',
    icon: 'file-pen-line',
    kind: 'builtin',
    enabled: true,
    package: 'frontend/src/galley + backend galley router',
  },
];

export function pluginByRoute(pathname: string): ToolPlugin | undefined {
  const exact = BUILTIN_PLUGINS.find(
    (plugin) => pathname === plugin.route || pathname.startsWith(`${plugin.route}/`),
  );
  if (exact) return exact;
  const hosted = pathname.match(/^\/tools\/([a-z0-9-]+)/);
  if (!hosted) return undefined;
  return BUILTIN_PLUGINS.find((plugin) => plugin.id === hosted[1]);
}
