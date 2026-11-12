'use client';

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
export default function QuestionCard(props: QuestionCardProps): React.JSX.Element {
  void props;
  throw new Error('Not implemented');
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
  void data;
  void content;
  throw new Error('Not implemented');
}
