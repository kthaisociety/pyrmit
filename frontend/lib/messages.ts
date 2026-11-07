// The page's texts in English and Swedish (#75), one entry per text. `sv` has to carry every key `en` has.
export const en = {} as const;

export type MessageKey = keyof typeof en;

export const sv: Record<MessageKey, string> = {};
