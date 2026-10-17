import { Moon, Sun } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";

// User-level appearance: VIen Light (default) / VIen Dark. Stored per user, affects only this user.
export function ThemeToggle({ className = "" }) {
    const { user, setTheme } = useAuth();
    if (!user) return null;
    const dark = user.theme === "dark";
    const toggle = async () => {
        try { await setTheme(dark ? "light" : "dark"); } catch { toast.error("Could not save appearance preference."); }
    };
    return (
        <button type="button" onClick={toggle} title={dark ? "Switch to VIen Light" : "Switch to VIen Dark"} aria-label="Toggle appearance"
            data-testid="theme-toggle" className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold border transition-colors duration-150 ${className}`}>
            {dark ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
            <span className="hidden sm:inline" data-testid="theme-toggle-label">{dark ? "VIen Dark" : "VIen Light"}</span>
        </button>
    );
}

export function ThemeSelector() {
    const { user, setTheme } = useAuth();
    if (!user) return null;
    return (
        <div className="flex gap-2" data-testid="theme-selector">
            {[["light", "VIen Light", Sun], ["dark", "VIen Dark", Moon]].map(([v, l, Icon]) => (
                <button key={v} type="button" onClick={() => setTheme(v).catch(() => toast.error("Could not save appearance preference."))}
                    data-testid={`theme-option-${v}`}
                    className={`flex items-center gap-2 px-3 py-2 rounded-sm border text-sm font-semibold ${user.theme === v ? "bg-visita-green text-white border-visita-green" : "border-slate-300 text-slate-700"}`}>
                    <Icon className="w-4 h-4" /> {l}{v === "light" && <span className="text-[10px] opacity-70">(default)</span>}
                </button>
            ))}
        </div>
    );
}
