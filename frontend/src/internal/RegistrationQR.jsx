import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { QRCodeCanvas } from "qrcode.react";
import { toast } from "sonner";
import { QrCode, Copy, Download, Printer, Link2, AlertTriangle, RefreshCw, Loader2 } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";

export default function RegistrationQR() {
    const qrRef = useRef(null);
    const q = useQuery({
        queryKey: ["my-practice"],
        queryFn: async () => (await api.get("/internal/my-practice")).data,
        retry: 1,
        retryDelay: 800,
    });
    const p = q.data;
    const registerUrl = p ? `${window.location.origin}${p.register_path}` : "";

    const copyLink = async () => {
        try {
            await navigator.clipboard.writeText(registerUrl);
            toast.success("Registration link copied.");
        } catch { toast.error("Could not copy. Please copy it manually."); }
    };

    const downloadPng = () => {
        const canvas = qrRef.current?.querySelector("canvas");
        if (!canvas) return;
        const url = canvas.toDataURL("image/png");
        const a = document.createElement("a");
        a.href = url;
        a.download = `registration-qr-${p?.slug || "practice"}.png`;
        a.click();
        toast.success("QR downloaded.");
    };

    const printQr = () => window.print();

    return (
        <div className="animate-fade-in max-w-2xl" data-testid="registration-qr-page">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
                <QrCode className="w-6 h-6 text-visita-greenDark" /> Registration QR
            </h1>
            <p className="text-sm text-slate-500 mb-5">
                Share or print this QR code. Patients scan it to register directly with your
                practice — no registration code, physician search, or clinic selection needed.
            </p>

            {q.isLoading && (
                <p className="flex items-center gap-2 text-slate-400 text-sm" data-testid="qr-loading">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading your practice…
                </p>
            )}

            {!q.isLoading && q.isError && (
                <div className="rounded-md border border-amber-200 bg-amber-50 p-5" data-testid="qr-error">
                    <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
                        <div>
                            <div className="font-semibold text-slate-800">Practice context unavailable</div>
                            <p className="text-sm text-slate-600 mt-1">
                                We couldn't load your practice details, so the registration QR can't be
                                generated right now. This usually means your account isn't linked to an
                                active practice yet. Please try again, or contact your administrator if it persists.
                            </p>
                            <p className="text-xs text-slate-400 mt-1" data-testid="qr-error-detail">{formatErr(q.error)}</p>
                            <Button onClick={() => q.refetch()} data-testid="qr-retry" variant="outline" className="h-9 mt-3">
                                <RefreshCw className="w-4 h-4 mr-1.5" /> Retry
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {!q.isLoading && !q.isError && p && (
                <div className="bg-white border border-slate-300 rounded-sm p-6 print:border-0" data-testid="qr-card">
                    <div className="text-center mb-4">
                        <div className="text-xs uppercase tracking-wide text-slate-400">Registering with</div>
                        <div className="text-xl font-bold text-slate-800" data-testid="qr-practice-name">
                            {p.physician_name || p.clinic_name || "This practice"}
                        </div>
                        {p.clinic_name && p.physician_name && (
                            <div className="text-sm text-slate-500">{p.clinic_name}</div>
                        )}
                    </div>

                    <div ref={qrRef} className="flex justify-center my-4" data-testid="qr-canvas-wrap">
                        <div className="p-4 bg-white rounded-sm border border-slate-200">
                            <QRCodeCanvas
                                value={registerUrl}
                                size={240}
                                level="M"
                                includeMargin
                                fgColor="#0f3d2e"
                            />
                        </div>
                    </div>

                    <div className="bg-slate-50 border border-slate-200 rounded-sm px-3 py-2 flex items-center gap-2 text-sm break-all">
                        <Link2 className="w-4 h-4 text-slate-400 shrink-0" />
                        <span data-testid="qr-register-url" className="text-slate-700">{registerUrl}</span>
                    </div>

                    <div className="flex flex-wrap gap-2 mt-4 print:hidden">
                        <Button onClick={copyLink} data-testid="qr-copy-link" variant="outline" className="h-9">
                            <Copy className="w-4 h-4 mr-1.5" /> Copy link
                        </Button>
                        <Button onClick={downloadPng} data-testid="qr-download" className="h-9 bg-visita-green hover:bg-visita-greenDark text-white">
                            <Download className="w-4 h-4 mr-1.5" /> Download PNG
                        </Button>
                        <Button onClick={printQr} data-testid="qr-print" variant="outline" className="h-9">
                            <Printer className="w-4 h-4 mr-1.5" /> Print
                        </Button>
                    </div>

                    <p className="text-xs text-slate-400 mt-4 print:hidden">
                        After scanning, the patient sees “You’re registering with {p.physician_name || "this practice"}”
                        and simply answers whether they are already a patient. Each practice’s QR only registers into
                        that practice.
                    </p>
                </div>
            )}
        </div>
    );
}
