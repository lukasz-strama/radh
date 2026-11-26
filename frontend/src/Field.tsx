// Pojedyncze pole liczbowe z etykietą i komunikatem błędu pod spodem.
// Bez `value` pole samo trzyma swoją treść (startuje od `defaultValue`);
// z `value` i `onChange` treść trzyma komponent nadrzędny, który może ją podmienić.

type FieldProps = {
  name: string
  label: string
  error?: string
  defaultValue?: string
  value?: string
  onChange?: (value: string) => void
  // Prefiks identyfikatora komunikatu błędu, gdy ten sam formularz jest na stronie
  // dwa razy (zakładki DH i RSA + DH).
  idPrefix?: string
}

export function Field({ name, label, error, defaultValue, value, onChange, idPrefix = '' }: FieldProps) {
  const errorId = `${idPrefix}${name}-error`
  return (
    <label>
      {label}
      <input
        name={name}
        type="text"
        inputMode="numeric"
        defaultValue={value === undefined ? defaultValue : undefined}
        value={value}
        onChange={onChange && ((event) => onChange(event.target.value))}
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