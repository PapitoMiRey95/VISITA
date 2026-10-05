import { useTranslation } from "react-i18next";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import MedicationRefill from "./MedicationRefill";

export default function PortalPrescriptions() {
    const { t } = useTranslation(["requests"]);
    const { overview, refetch, managed, base } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const obo = managed ? base.split("/").pop() : null;
    const list = overview.data?.prescriptions || [];

    // Group patient requests created in the same submission (shared batch_id) so
    // one multi-medicine refill reads as a single submission.
    const groups = [];
    const byBatch = {};
    for (const r of list) {
        if (r.batch_id) {
            if (!byBatch[r.batch_id]) { byBatch[r.batch_id] = { batch_id: r.batch_id, items: [], created_at: r.created_at, status: r.status, supply: r.requested_supply_text }; groups.push(byBatch[r.batch_id]); }
            byBatch[r.batch_id].items.push(r);
        } else {
            groups.push({ single: r, created_at: r.created_at });
        }
    }

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">{t("rx.title")}</h1>
            {p && <PendingBanner status={p.verification_status} />}

            {verified && <MedicationRefill onBehalfOf={obo} onSubmitted={refetch} />}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">{t("rx.listTitle")}</h2>
                {groups.length === 0 && <p className="text-slate-500 text-sm">{t("form.noRequestsYet")}</p>}
                {groups.map((g, i) => {
                    if (g.single) {
                        const r = g.single;
                        return (
                            <Card key={r.id} className="p-4 flex justify-between items-start gap-2" data-testid="rx-history-item">
                                <div>
                                    <div className="font-bold text-slate-800">{r.medication_name} {r.strength}</div>
                                    <div className="text-sm text-slate-500">{r.ref_number}{r.requested_supply_text ? ` · ${r.requested_supply_text}` : ""}</div>
                                </div>
                                <StatusPill status={r.status} />
                            </Card>
                        );
                    }
                    return (
                        <Card key={g.batch_id || i} className="p-4" data-testid="rx-history-batch">
                            <div className="flex justify-between items-start gap-2">
                                <div className="flex-1 min-w-0">
                                    {g.items.map((r) => (
                                        <div key={r.id} className="font-bold text-slate-800">{r.medication_name} {r.strength}</div>
                                    ))}
                                    <div className="text-sm text-slate-500 mt-0.5">{g.supply || ""}</div>
                                </div>
                                <StatusPill status={g.items[0].status} />
                            </div>
                        </Card>
                    );
                })}
            </div>
        </div>
    );
}
