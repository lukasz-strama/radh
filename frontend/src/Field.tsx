// Pojedyncze pole liczbowe z etykietą i komunikatem błędu pod spodem.

type FieldProps = {
  name: string
  label: string
  error?: string
  defaultValue?: string
}

export function Field({ name, label, error, defaultValue }: FieldProps) {
  const errorId = `${name}-error`
  return (
    <label>
      {label}
      <input
        name={name}
        type="text"
        inputMode="numeric"
        defaultValue={defaultValue}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
      />
      {error && (
        <span className="field-error" id={errorId}>
          {error}
        </span>
      )}
    </label>
  )
}