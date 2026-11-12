'use client';

import { useState, type KeyboardEvent } from 'react';
import { MapPin, Send } from 'lucide-react';

import { useLanguage } from '@/lib/i18n';

/** One question of the agent's question card: `options` is empty for an open question (only the "Other" field). */
export interface AskedQuestion {
  question: string;
  options: string[];
}

export interface QuestionCardProps {
  questions: AskedQuestion[];
  /** Also show a button that opens the map, to answer the question about the place with a pin. */
  offerPin: boolean;
  /** Sends the user's reply as the answer to the card (one message). Absent once the card is answered. */
  onAnswer?: (reply: string) => void;
  onPin?: () => void;
  /** The user clicked "Pin it on the map": the next pin answers the card. */
  awaitingPin?: boolean;
  /** The reply the user gave: the card is locked, shows its questions and this reply, and takes no input. */
  reply?: string;
}

/** The reply of a card: the answer alone for one question, else one "<question> <answer>" line per answered one. */
function replyOf(questions: AskedQuestion[], answers: string[]): string {
  if (questions.length === 1) return answers[0]?.trim() ?? '';
  return questions
    .map((asked, index) => ({ asked, answer: answers[index]?.trim() ?? '' }))
    .filter(({ answer }) => answer)
    .map(({ asked, answer }) => `${asked.question} ${answer}`)
    .join('\n');
}

/**
 * The agent's question card, under the question it asked instead of answering (#91).
 *
 * Every question shows its options as buttons, then an "Other" text field; an open question shows only the field.
 * With one question, clicking an option sends it at once; typing in "Other" sends on Enter or "Send answer".
 * With several questions, the user picks or types an answer per question and sends them together with "Send answer",
 * enabled once at least one question has an answer. The reply is one line per answered question, "<question>
 * <answer>"; an unanswered question is left out (the agent then answers on stated assumptions).
 * A reply, from the card or typed in the chat's own input, locks the card (`reply`).
 *
 * The card is a region named "Questions for you" ("Frågor till dig"); a locked card shows the reply in it.
 * Each question is a group named by its question text, holding its option buttons and a text field named "Other"
 * ("Övrigt" on the Swedish page); the card's send button is "Send answer" ("Skicka svar").
 */
export default function QuestionCard({ questions, offerPin, onAnswer, onPin, awaitingPin, reply }: QuestionCardProps) {
  const { t } = useLanguage();
  // Per question: the clicked option or the typed text, whichever the user gave last
  const [answers, setAnswers] = useState<string[]>(() => questions.map(() => ''));
  const [typed, setTyped] = useState<boolean[]>(() => questions.map(() => false));
  const open = Boolean(onAnswer) && reply === undefined;
  const single = questions.length === 1;
  const pending = replyOf(questions, answers);

  const setAnswer = (index: number, value: string, fromField: boolean) => {
    setAnswers((current) => current.map((answer, i) => (i === index ? value : answer)));
    setTyped((current) => current.map((wasTyped, i) => (i === index ? fromField : wasTyped)));
  };
  const submit = () => {
    if (onAnswer && pending) onAnswer(pending);
  };
  const onFieldKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <section aria-label={t('chat.questionsForYou')}
             className="mt-3 space-y-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-900/40">
      {questions.map((asked, index) => (
        <div key={asked.question} role="group" aria-label={asked.question} className="space-y-2">
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{asked.question}</p>
          {open && (
            <>
              {asked.options.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {asked.options.map((option) => {
                    const chosen = !typed[index] && answers[index] === option;
                    return (
                      <button
                        key={option}
                        type="button"
                        aria-pressed={single ? undefined : chosen}
                        onClick={() => (single ? onAnswer?.(option) : setAnswer(index, chosen ? '' : option, false))}
                        className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition active:scale-[0.97] ${
                          chosen
                            ? 'border-zinc-900 bg-zinc-900 text-white dark:border-white dark:bg-white dark:text-zinc-900'
                            : 'border-zinc-300 bg-white text-zinc-800 hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700'
                        }`}
                      >
                        {option}
                      </button>
                    );
                  })}
                </div>
              )}
              <input
                type="text"
                aria-label={t('chat.other')}
                placeholder={t('chat.otherPlaceholder')}
                value={typed[index] ? answers[index] : ''}
                onChange={(event) => setAnswer(index, event.target.value, true)}
                onKeyDown={onFieldKey}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-500 focus:outline-none dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100"
              />
            </>
          )}
        </div>
      ))}

      {open && (
        <div className="flex flex-wrap items-center gap-2">
          {offerPin && onPin && (
            <button
              type="button"
              onClick={onPin}
              className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900 px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-zinc-700 active:scale-[0.97] dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              <MapPin size={14} aria-hidden />
              {t('chat.pinOnMap')}
            </button>
          )}
          <button
            type="button"
            onClick={submit}
            disabled={!pending}
            className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-blue-600 px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Send size={14} aria-hidden />
            {t('chat.sendAnswer')}
          </button>
        </div>
      )}
      {open && awaitingPin && <p className="text-xs text-zinc-500 dark:text-zinc-400">{t('chat.pinHint')}</p>}

      {reply !== undefined && (
        <p className="whitespace-pre-wrap border-t border-zinc-200 pt-2 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
          <span className="font-medium">{t('chat.yourAnswer')}:</span> {reply}
        </p>
      )}
    </section>
  );
}

function asQuestion(item: unknown): AskedQuestion | null {
  if (!item || typeof item !== 'object') return null;
  const { question, options } = item as { question?: unknown; options?: unknown };
  if (typeof question !== 'string' || !question.trim()) return null;
  return {
    question: question.trim(),
    options: Array.isArray(options) ? options.filter((o): o is string => typeof o === 'string' && Boolean(o.trim())) : [],
  };
}

/**
 * The question card of an assistant message, from its `choices` pipeline event, or null when it asked nothing.
 *
 * Reads `{questions: [{question, options}], offer_pin}`, and also the shape saved before #91, `{options, offer_pin}`,
 * as one question whose text is the message itself (`content`).
 */
export function getQuestionCard(
  data: Record<string, unknown> | undefined,
  content: string,
): { questions: AskedQuestion[]; offerPin: boolean } | null {
  if (!data) return null;
  const offerPin = data.offer_pin === true;
  let questions: AskedQuestion[];
  if (Array.isArray(data.questions)) {
    questions = data.questions.map(asQuestion).filter((q): q is AskedQuestion => q !== null);
  } else {
    const legacy = asQuestion({ question: content, options: data.options });
    questions = legacy ? [legacy] : [];
  }
  if (questions.length === 0 && offerPin && content.trim()) questions = [{ question: content.trim(), options: [] }];
  return questions.length > 0 ? { questions, offerPin } : null;
}
