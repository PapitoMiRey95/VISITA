import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Users, ChevronRight } from "lucide-react";
import { api } from "../lib/api";

export default function ManagedPeople() {
    const nav = useNavigate();
    const [data, setData] = useState({ managing: [], has_own_patient: true });

    useEffect(() => {
        api.get("/portal/my-delegations").then(({ data }) => setData(data)).catch(() => {});
    }, []);

    return (
        <div data-testid="managed-people-page">
            <h1 className="text-xl font-bold text-portal-blueDark mb-1">People I help manage</h1>
            <p className="text-sm text-slate-500 mb-4">Accounts you are authorized to help manage.</p>
            {data.managing.length === 0 ? (
                <p className="text-sm text-slate-400" data-testid="managed-people-empty">You don't have access to anyone else's account.</p>
            ) : (
                <div className="space-y-2">
                    {data.managing.map((m) => (
                        <button key={m.patient_id} data-testid="managed-person-card" onClick={() => nav(`/portal/manage/${m.patient_id}`)}
                            className="w-full flex items-center justify-between p-4 bg-white rounded-xl border border-slate-200 hover:border-portal-blue transition-colors">
                            <div className="flex items-center gap-3 text-left">
                                <div className="w-10 h-10 rounded-full bg-portal-blue/10 flex items-center justify-center"><Users className="w-5 h-5 text-portal-blue" /></div>
                                <div>
                                    <div className="font-bold text-slate-800">{m.patient_name}</div>
                                    <div className="text-xs text-slate-500">{m.relationship} · {m.permissions.length} permission{m.permissions.length === 1 ? "" : "s"}</div>
                                </div>
                            </div>
                            <ChevronRight className="w-5 h-5 text-slate-300" />
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
