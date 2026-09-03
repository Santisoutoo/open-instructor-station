export interface ControlSearchProps {
  value: string;
  onChange: (value: string) => void;
}

/** Filters by label/id across **all** panels; a non-empty value flattens the picker. */
export function ControlSearch({ value, onChange }: ControlSearchProps) {
  return (
    <input
      type="search"
      className="cockpit-search"
      aria-label="Search cockpit controls"
      placeholder="Search controls"
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}
