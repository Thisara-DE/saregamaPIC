import {
  allProfiles,
  parseProfile,
  profileName,
  serializeProfile,
  type InstrumentProfile,
} from "../instrumentProfile";

interface Props {
  value: InstrumentProfile;
  onChange: (profile: InstrumentProfile) => void;
  id?: string;
}

/**
 * "What are you playing?" as one control — the sax, then the twelve bamboo-flute
 * tunings. Used twice: in the viewer's controls row, and in the once-a-session
 * prompt, so the two can never drift apart.
 *
 * Options carry the serialized profile as their value and are read back through
 * `parseProfile`, which means the DOM never holds a shape this app has to trust:
 * the same defensive parse guards a stored preference and a select value.
 *
 * Each option names the instrument in full ("Bamboo flute in D", not "D") even
 * though the group label repeats it. A collapsed `<select>` shows only the
 * chosen option's text on every platform, and this control is read at
 * music-stand distance where "D" alone would be a guess.
 */
export function InstrumentPicker({ value, onChange, id }: Props) {
  const profiles = allProfiles();
  const sax = profiles.filter((p) => p.kind === "alto-sax");
  const flutes = profiles.filter((p) => p.kind === "bamboo-flute");

  return (
    <select
      id={id}
      className="instrument-select"
      // Named on the control itself, not left to the wrapping label: the label
      // also encloses the select, so its text alone is not a stable name.
      aria-label="Instrument"
      value={serializeProfile(value)}
      onChange={(e) => onChange(parseProfile(e.target.value))}
    >
      <optgroup label="Saxophone">
        {sax.map((p) => (
          <option key={serializeProfile(p)} value={serializeProfile(p)}>
            {profileName(p)}
          </option>
        ))}
      </optgroup>
      <optgroup label="Bamboo flute">
        {flutes.map((p) => (
          <option key={serializeProfile(p)} value={serializeProfile(p)}>
            {profileName(p)}
          </option>
        ))}
      </optgroup>
    </select>
  );
}
