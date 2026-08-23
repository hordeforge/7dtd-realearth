// RealEarth section in the dashboard's Settings sidebar: lets an admin pick
// the default pack path shown on the Map page. Persisted in localStorage by
// settings-store.ts; session-only when storage is unavailable.

import type { WebModComponentProps } from "./types";
import { makeElement } from "./types";
import { getDefaultPackPath, setDefaultPackPath } from "./settings-store";

function setText(element: HTMLElement | null, text: string): void {
  if (element !== null) {
    element.textContent = text;
  }
}

export function RealEarthSettings(props: WebModComponentProps): unknown {
  const { React } = props;
  const h = makeElement(React);
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const saveButtonRef = React.useRef<HTMLButtonElement | null>(null);
  const savedRef = React.useRef<HTMLSpanElement | null>(null);

  React.useEffect(() => {
    const input = inputRef.current;
    const saveButton = saveButtonRef.current;

    function onSave(): void {
      if (input === null) {
        return;
      }
      const path = input.value.trim();
      if (path === "") {
        setText(savedRef.current, "Path must not be empty.");
        return;
      }
      const stored = setDefaultPackPath(path);
      setText(
        savedRef.current,
        stored ? `Saved: ${path}` : "Could not persist to localStorage; keeping it for this session."
      );
    }

    if (input !== null) {
      input.value = getDefaultPackPath();
    }
    if (saveButton !== null) {
      saveButton.addEventListener("click", onSave);
    }
    return () => {
      if (saveButton !== null) {
        saveButton.removeEventListener("click", onSave);
      }
    };
  }, []);

  return h(
    "div",
    { className: "re-settings" },
    h(
      "p",
      null,
      "Default pack shown on the Map page. Packs live under WebMod/data/ on the server; generate one with `make webmod-export` (demo ships as data/demo)."
    ),
    h(
      "div",
      { className: "re-settings-row" },
      h("label", { className: "re-field" }, h("span", { className: "re-label" }, "Default pack"), h("input", { ref: inputRef, className: "re-input", type: "text", spellCheck: false })),
      h("button", { ref: saveButtonRef, className: "re-btn", type: "button" }, "Save"),
      h("span", { ref: savedRef, className: "re-muted", role: "status" })
    )
  );
}
