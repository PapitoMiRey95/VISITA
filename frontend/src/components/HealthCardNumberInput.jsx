import { Input } from "./ui/input";
import { normalizeHealthCardInput, formatHealthCardNumber } from "../lib/healthCard";

// Masked Health Card Number input: digits only, auto-spaced "#### ### ###", max
// 10 digits. Stores/emits the normalized 10-digit value (no spaces). Paste of
// spaced or dashed numbers is normalized automatically.
export function HealthCardNumberInput({ value, onChange, ...props }) {
    return (
        <Input
            inputMode="numeric"
            maxLength={12}
            value={formatHealthCardNumber(value)}
            onChange={(e) => onChange(normalizeHealthCardInput(e.target.value))}
            {...props}
        />
    );
}
