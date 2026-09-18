import { useNavigate } from "react-router-dom";
import { LogIn, UserPlus, UserRound, ArrowRight, Lock } from "lucide-react";
import { Button } from "../components/ui/button";

const BG = "https://customer-assets-4nw71qhi.emergentagent.net/job_visita-admin/artifacts/ndj1izcs_ChatGPT%20Image%20Sep%2018%2C%202026%2C%2010_35_01%20AM.png";

export default function Landing() {
    const nav = useNavigate();

    return (
        <div className="relative min-h-screen w-full overflow-hidden font-plex">
            <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: `url("${BG}")` }} aria-hidden />
            <div className="absolute inset-0 bg-gradient-to-r from-[#060b16]/96 via-[#0a1524]/86 to-[#0a1524]/60" aria-hidden />
            <div className="absolute inset-0 visita-scanlines" aria-hidden />

            <div className="relative z-10 min-h-screen flex flex-col lg:flex-row lg:items-center lg:justify-between px-6 py-10 lg:px-16 gap-10">
                {/* Branding */}
                <div className="max-w-xl">
                    <h1 data-text="VISITA" className="visita-glitch text-6xl sm:text-7xl lg:text-8xl font-bold tracking-tight leading-none">VISITA</h1>
                    <p className="mt-4 text-lg text-slate-200/90 font-semibold tracking-wide">Dr. Aguayo Family Practice</p>
                    <p className="mt-2 max-w-md text-sm text-slate-400 leading-relaxed">
                        Secure portal for appointments, prescriptions, referrals, and clinic communication.
                    </p>
                    <div className="mt-6 h-px w-40 bg-gradient-to-r from-cyan-400/50 to-transparent" />
                </div>

                {/* Pathways */}
                <div className="w-full max-w-md space-y-4">
                    {/* Current patients — primary */}
                    <div data-testid="pathway-current" className="rounded-md border border-cyan-400/25 bg-[#0b1524]/80 backdrop-blur-xl p-6 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8)]">
                        <div className="flex items-center gap-2 mb-1">
                            <UserRound className="w-5 h-5 text-cyan-300" />
                            <h2 className="text-xl font-bold text-slate-100 tracking-tight">Current Patients</h2>
                        </div>
                        <p className="text-sm text-slate-400 leading-relaxed mb-4">
                            If you are already a patient of Dr. Aguayo, sign in or register for portal access. An existing
                            clinic patient may not yet have a portal account — if so, please register first.
                        </p>
                        <div className="grid grid-cols-2 gap-3">
                            <Button data-testid="current-signin" onClick={() => nav("/signin")}
                                className="bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold h-11">
                                <LogIn className="w-4 h-4 mr-1.5" /> Sign In
                            </Button>
                            <Button data-testid="current-register" onClick={() => nav("/register")}
                                variant="outline" className="h-11 border-cyan-400/40 bg-transparent text-cyan-200 hover:bg-cyan-500/10 hover:text-cyan-100 font-semibold">
                                <UserPlus className="w-4 h-4 mr-1.5" /> Register
                            </Button>
                        </div>
                    </div>

                    {/* New patients — secondary */}
                    <div data-testid="pathway-new" className="rounded-md border border-white/10 bg-[#0b1524]/60 backdrop-blur-md p-5">
                        <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider mb-1">New Patients</h3>
                        <p className="text-sm text-slate-400 leading-relaxed mb-3">
                            If you are not currently a patient, you may begin a new patient request.
                        </p>
                        <button data-testid="new-patient-request" onClick={() => nav("/register?new=1")}
                            className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-200 hover:text-cyan-200 transition-colors">
                            New Patient Request <ArrowRight className="w-4 h-4" />
                        </button>
                    </div>

                    {/* Internal — discreet */}
                    <div className="flex items-center justify-between px-1 pt-1">
                        <span className="text-[11px] uppercase tracking-widest text-slate-500">Admin / Staff / Physician</span>
                        <button data-testid="internal-login" onClick={() => nav("/signin?internal=1")}
                            className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-slate-200 transition-colors">
                            <Lock className="w-3.5 h-3.5" /> Internal Login
                        </button>
                    </div>

                    <p className="text-[11px] leading-relaxed text-slate-500/80 pt-1">
                        Not for emergencies. If you are experiencing a medical emergency, call 911 or go to the nearest
                        Emergency Department.
                    </p>
                </div>
            </div>
        </div>
    );
}
