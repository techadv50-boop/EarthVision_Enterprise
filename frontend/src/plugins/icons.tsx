import type { LucideIcon } from 'lucide-react';
import {
  BookOpen,
  ClipboardList,
  FilePenLine,
  GitCompare,
  Puzzle,
  Shield,
  Sparkles,
} from 'lucide-react';

const ICONS: Record<string, LucideIcon> = {
  'book-open': BookOpen,
  'clipboard-list': ClipboardList,
  'file-pen-line': FilePenLine,
  'git-compare': GitCompare,
  puzzle: Puzzle,
  shield: Shield,
  sparkles: Sparkles,
};

export function pluginIcon(name?: string): LucideIcon {
  return ICONS[(name || '').toLowerCase()] || Puzzle;
}
