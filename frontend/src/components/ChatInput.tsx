import { type FormEvent, useState } from 'react';

interface ChatInputProps {
  onSubmit: (message: string) => void;
  inputLabel: string;
  placeholder: string;
  submitLabel: string;
  disabled?: boolean;
}

export function ChatInput({
  onSubmit,
  inputLabel,
  placeholder,
  submitLabel,
  disabled = false,
}: ChatInputProps) {
  const [message, setMessage] = useState('');

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedMessage = message.trim();

    if (!trimmedMessage || disabled) {
      return;
    }

    onSubmit(trimmedMessage);
    setMessage('');
  }

  return (
    <form className="chat-input" onSubmit={handleSubmit}>
      <label className="sr-only" htmlFor="chat-message">
        {inputLabel}
      </label>
      <input
        id="chat-message"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled}>{submitLabel}</button>
    </form>
  );
}
