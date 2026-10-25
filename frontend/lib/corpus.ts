// Shared by the Database and Pipeline views: document types of corpus.extract and number formatting.

export const DOC_TYPE_LABELS: Record<string, { name: string; hint: string }> = {
  detaljplan: { name: 'Detaljplan', hint: 'detailed development plan: plan map, description, consultation documents, studies' },
  oversiktsplan: { name: 'Översiktsplan', hint: 'comprehensive plan for the whole kommun (where it intends to grow)' },
  bygglov: { name: 'Bygglov', hint: 'building permits: how to apply, rules, forms' },
  strandskydd: { name: 'Strandskydd', hint: 'shore protection: building near lakes, rivers and the sea' },
  avlopp: { name: 'Avlopp', hint: 'water and sewage: private sewage permits, connection to the network' },
  taxa: { name: 'Taxa', hint: 'fee schedules (permit and inspection fees)' },
  other: { name: 'Other', hint: 'everything else kept by the filter: decisions, investigations, guidance' },
};

export function docTypeName(docType: string | null | undefined): string {
  return DOC_TYPE_LABELS[docType ?? 'other']?.name ?? docType ?? 'Other';
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : value.toLocaleString('en-US');
}

/** 1876498 -> "1.9 M", 83150 -> "83 k": for tiles where the exact number is in the tooltip. */
export function compactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)} M`;
  if (value >= 10_000) return `${Math.round(value / 1000)} k`;
  return value.toLocaleString('en-US');
}
