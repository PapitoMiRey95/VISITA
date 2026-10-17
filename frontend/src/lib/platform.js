import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// Published installation config (branding / features / navigation / public copy). Public, read-only.
export function usePlatformConfig() {
    const q = useQuery({ queryKey: ["platform-config-public"], queryFn: async () => (await api.get("/system/config")).data, staleTime: 30000, refetchInterval: 60000 });
    const cfg = q.data;
    const featureState = (key) => cfg?.features?.[key] || "ON";
    const isOn = (key, role) => {
        const st = featureState(key);
        if (st === "ON") return true;
        if (st === "PILOT") return ["admin", "physician", "staff", "developer_ops"].includes(role);
        return false;
    };
    // Navigation visibility only — never authorization.
    const navVisible = (key, audience, role) => isOn(key, role) && !(cfg?.navigation?.hidden?.[audience] || []).includes(key);
    return { cfg, isOn, navVisible, publicSite: cfg?.public_site || {}, featureState };
}

// Internal nav path -> feature key (paths not listed are always visible).
export const NAV_FEATURE = {
    "/internal/rx": "rx", "/internal/send-rx": "rx", "/internal/calendar": "calendar", "/internal/appointments": "calendar",
    "/internal/exams": "results", "/internal/referrals": "referrals",
};
