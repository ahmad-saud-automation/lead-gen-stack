"use client";

import { useEffect, type ReactNode } from "react";

/** A centred window over the page, the same one Fabrikam View's editors open in. Escape or a click
 *  outside closes it. */
export function Modal({
  label,
  wide,
  onClose,
  children,
}: {
  label: string;
  /** For content that needs room, like a push payload. */
  wide?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className={wide ? "editor modal wide" : "editor modal"}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

/** Asked before anything that spends money, leaves this machine, or cannot be undone.
 *
 *  The action that spends or leaves the machine is never the default: Cancel comes first, and a
 *  `secondary` choice (e.g. "Live push") sits away from where the thumb lands. */
export function Confirm({
  title,
  body,
  confirmLabel = "Confirm",
  danger,
  secondary,
  onConfirm,
  onClose,
}: {
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  secondary?: { label: string; onClick: () => void };
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal label={title} onClose={onClose}>
      <div className="editor-head">{title}</div>
      <div className="confirm-body">{body}</div>
      <div className="editor-actions">
        <button type="button" className="ctl" onClick={onClose}>
          Cancel
        </button>
        {secondary ? (
          <button type="button" className="ctl danger" onClick={secondary.onClick}>
            {secondary.label}
          </button>
        ) : null}
        <button type="button" className={danger ? "ctl danger" : "ctl solid"} onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
