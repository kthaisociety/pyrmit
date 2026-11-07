'use client';
import type { ReactNode } from 'react';

// A Swedish domain term on the page (#75). Shows `term` as given, in Swedish in either language. In English, when
// the shared glossary (GET /api/glossary, through LanguageProvider) has the term (compared in lower case), its
// English explanation is the element's title, shown as a tooltip; in Swedish, for a term without an entry, or while
// the glossary is missing, there is no title. Needs a LanguageProvider.
export default function Term({ term }: { term: string }): ReactNode {
  throw new Error('Not implemented');
}
