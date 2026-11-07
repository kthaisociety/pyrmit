'use client';

// A Swedish domain term on the page (#75). Shows `term` as given, in Swedish in either language. In English, when
// the shared glossary (GET /api/glossary, through LanguageProvider) has the term (compared in lower case), its
// English explanation is the element's title, shown as a tooltip; in Swedish, for a term without an entry, or while
// the glossary is missing, there is no title. Needs a LanguageProvider.
import type { ReactNode } from 'react';

import { useGlossaryExplanation, useLanguage } from '@/lib/i18n';

export default function Term({ term }: { term: string }): ReactNode {
  const { language } = useLanguage();
  const explanation = useGlossaryExplanation(term);
  if (language === 'sv' || !explanation) return <span lang="sv">{term}</span>;
  return (
    <abbr lang="sv" title={explanation} className="cursor-help no-underline decoration-dotted hover:underline">
      {term}
    </abbr>
  );
}
