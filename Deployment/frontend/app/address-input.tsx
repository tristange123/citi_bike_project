"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

export type AddressResult = {
  label: string;
  lat: number;
  lon: number;
};

type Props = {
  apiBaseUrl: string;
  dotClassName: string;
  placeholder: string;
  // The label of the pin currently in this slot, shown whenever the user isn't typing.
  value: string;
  disabled: boolean;
  onSelect: (result: AddressResult) => void;
};

const debounceMs = 250;
const minQueryLength = 3;

export function AddressInput({ apiBaseUrl, dotClassName, placeholder, value, disabled, onSelect }: Props) {
  const listId = useId();
  const [text, setText] = useState(value);
  const [results, setResults] = useState<AddressResult[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setText(value);
  }, [value]);

  // Debounced search as the user types; each new keystroke cancels the previous request.
  useEffect(() => {
    const query = text.trim();
    if (!isOpen || query.length < minQueryLength || query === value) {
      setResults([]);
      setStatus("idle");
      return;
    }

    const timer = window.setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setStatus("loading");
      try {
        const response = await fetch(`${apiBaseUrl}/api/geocode?q=${encodeURIComponent(query)}`, {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Geocode API returned ${response.status}`);
        }
        const body = await response.json();
        setResults(body.results);
        setActiveIndex(0);
        setStatus("done");
      } catch {
        if (!controller.signal.aborted) {
          setResults([]);
          setStatus("error");
        }
      }
    }, debounceMs);

    return () => window.clearTimeout(timer);
  }, [apiBaseUrl, isOpen, text, value]);

  function choose(result: AddressResult) {
    setText(result.label);
    setIsOpen(false);
    setResults([]);
    onSelect(result);
  }

  function close() {
    abortRef.current?.abort();
    setIsOpen(false);
    setText(value);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (results.length) {
        const step = event.key === "ArrowDown" ? 1 : -1;
        setActiveIndex((index) => (index + step + results.length) % results.length);
      }
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (results[activeIndex]) {
        choose(results[activeIndex]);
      }
    } else if (event.key === "Escape") {
      close();
      event.currentTarget.blur();
    }
  }

  const showList = isOpen && text.trim().length >= minQueryLength && text.trim() !== value && status !== "idle";

  return (
    <div className="address-field">
      <span className={`pin-dot ${dotClassName}`} />
      <input
        aria-activedescendant={showList && results[activeIndex] ? `${listId}-${activeIndex}` : undefined}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={showList}
        className="address-input"
        disabled={disabled}
        onBlur={close}
        onChange={(event) => {
          setText(event.target.value);
          setIsOpen(true);
        }}
        onFocus={(event) => {
          setIsOpen(true);
          event.target.select();
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        role="combobox"
        spellCheck={false}
        type="text"
        value={text}
      />

      {showList ? (
        <ul className="address-results" id={listId} role="listbox">
          {status === "loading" && results.length === 0 ? <li className="address-status">Searching...</li> : null}
          {status === "done" && results.length === 0 ? (
            <li className="address-status">No matches in Lower Manhattan</li>
          ) : null}
          {status === "error" ? <li className="address-status">Address search is unavailable right now</li> : null}
          {results.map((result, index) => {
            const [main, ...rest] = result.label.split(", ");
            return (
              <li
                aria-selected={index === activeIndex}
                className={index === activeIndex ? "active" : ""}
                id={`${listId}-${index}`}
                key={`${result.label}-${index}`}
                // mousedown fires before the input's blur, so the choice lands before the list closes.
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(result);
                }}
                onMouseEnter={() => setActiveIndex(index)}
                role="option"
              >
                <strong>{main}</strong>
                {rest.length ? <span>{rest.join(", ")}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
