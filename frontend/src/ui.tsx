// Wspólne elementy interfejsu RADH: przyciski, plakietki i komunikaty.
// Wygląd w App.css (.button, .badge, .notice); kolory i rozmiary z index.css.

import type { ButtonHTMLAttributes, ReactNode } from 'react'

// Ton plakietki stanu: neutralny, sukces, błąd.
export type Tone = 'neutral' | 'ok' | 'error'

// Rodzaj danych: tajne (zna je tylko właściciel) albo jawne (przesyłane).
export type DataKind = 'private' | 'public'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  // primary: główna akcja formularza; secondary: akcja pomocnicza.
  variant?: 'primary' | 'secondary'
  // Trwa operacja: przycisk zablokowany, z aria-busy i opcjonalnie innym napisem.
  busy?: boolean
  busyLabel?: ReactNode
}

export function Button({
  variant = 'primary',
  busy = false,
  busyLabel,
  disabled,
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={`button button--${variant}`}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
    >
      {busy && busyLabel ? busyLabel : children}
    </button>
  )
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>
}

// Jedno oznaczenie danych w całej aplikacji: „tajne” albo „jawne”.
export function DataBadge({ kind }: { kind: DataKind }) {
  return <span className={`badge badge--${kind}`}>{kind === 'private' ? 'tajne' : 'jawne'}</span>
}

// Komunikat w ramce: błąd (ogłaszany czytnikom ekranu od razu) albo ostrzeżenie.
export function Notice({ tone, children }: { tone: 'error' | 'warning'; children: ReactNode }) {
  return (
    <p className={`notice notice--${tone}`} role={tone === 'error' ? 'alert' : undefined}>
      {children}
    </p>
  )
}