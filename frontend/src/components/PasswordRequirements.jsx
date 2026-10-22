import { Check, Square } from "lucide-react";
import { useTranslation } from "react-i18next";

export const PASSWORD_RULES = [
    { key: "min_length", test: (p) => (p || "").length >= 8, i18n: "auth:register.pwRules.minLength", fallback: "At least 8 characters" },
    { key: "uppercase", test: (p) => /[A-Z]/.test(p || ""), i18n: "auth:register.pwRules.uppercase", fallback: "One uppercase letter" },
    { key: "special", test: (p) => /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?~`]/.test(p || ""), i18n: "auth:register.pwRules.special", fallback: "One special character (e.g. ! @ # $ % & *)" },
];

export const passwordMeetsPolicy = (p) => PASSWORD_RULES.every((r) => r.test(p));

/** Live checklist under a password field: empty box → green check as each rule is met (icon + text, not color alone). */
export function PasswordRequirements({ password, testid = "pw-rules" }) {
    const { t } = useTranslation(["auth"]);
    return (
        <ul className="mt-2 space-y-1" data-testid={testid} aria-live="polite">
            {PASSWORD_RULES.map((r) => {
                const ok = r.test(password);
                return (
                    <li key={r.key} data-testid={`${testid}-${r.key}`} data-met={ok ? "true" : "false"}
                        className={`flex items-center gap-2 text-xs ${ok ? "text-emerald-700 font-semibold" : "text-slate-500"}`}>
                        {ok ? <Check className="w-3.5 h-3.5 text-emerald-600 shrink-0" aria-hidden="true" /> : <Square className="w-3.5 h-3.5 text-slate-400 shrink-0" aria-hidden="true" />}
                        <span className="sr-only">{ok ? t("auth:register.pwRules.met", "Met:") : t("auth:register.pwRules.unmet", "Not met:")}</span>
                        <span>{t(r.i18n, r.fallback)}</span>
                    </li>
                );
            })}
        </ul>
    );
}
