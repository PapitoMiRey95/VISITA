import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export function useCounters() {
    return useQuery({
        queryKey: ["counters"],
        queryFn: async () => (await api.get("/internal/counters")).data,
        refetchInterval: 20000,
    });
}

export function useInvalidate() {
    const qc = useQueryClient();
    return () => {
        qc.invalidateQueries({ queryKey: ["counters"] });
        qc.invalidateQueries({ queryKey: ["queue"] });
    };
}
