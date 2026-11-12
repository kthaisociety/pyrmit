'use client';

import { PanelLeft } from 'lucide-react';

import { useLanguage } from '@/lib/i18n';

/** The menu button that hides the chat list (in the sidebar) or brings it back (over the chat when it is hidden). */
export default function SidebarToggle({ open, onClick, className = '' }: {
  open: boolean;
  onClick: () => void;
  className?: string;
}) {
  const { t } = useLanguage();
  const label = open ? t('sidebar.close') : t('sidebar.open');
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-expanded={open}
      title={label}
      className={`rounded-lg p-2 text-zinc-500 transition hover:bg-zinc-200/70 hover:text-zinc-800 active:scale-95 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100 ${className}`}
    >
      <PanelLeft size={18} />
    </button>
  );
}
