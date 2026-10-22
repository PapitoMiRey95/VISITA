import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { AnnouncementBar, MaintenanceScreen, useSystemStatus } from "./SystemStatus";

function Loader() {
    return (
        <div className="min-h-screen flex items-center justify-center bg-visita-bg">
            <div className="text-visita-green font-plex font-semibold animate-pulse">Loading VIen…</div>
        </div>
    );
}

export function RoleRoute({ roles, children, requireEncounter = false }) {
    const { user } = useAuth();
    const sys = useSystemStatus();
    if (user === null) return <Loader />;
    if (user === false) return <Navigate to="/login" replace />;
    if (user.must_change_password) return <Navigate to="/change-password" replace />;
    if (roles && !roles.includes(user.role)) {
        return <Navigate to={homePath(user.role)} replace />;
    }
    if (requireEncounter && !user.encounter_enabled) {
        return <Navigate to={homePath(user.role)} replace />;
    }
    // Installation maintenance mode: everyone except the developer_ops operator sees the maintenance screen.
    const platformRole = user.role === "developer_ops" || user.role === "operations_operator";
    if (sys.maintenance?.on && !platformRole) {
        return <MaintenanceScreen />;
    }
    return (
        <>
            {!platformRole && <AnnouncementBar />}
            {children}
        </>
    );
}

export function homePath(role) {
    if (role === "patient") return "/portal";
    if (role === "caregiver") return "/portal/people";
    if (role === "pharmacy") return "/pharmacy";
    if (role === "partner") return "/partner";
    if (role === "developer_ops" || role === "operations_operator") return "/developer";
    if (role === "network") return "/network";
    return "/internal";
}

export function HomeRedirect() {
    const { user } = useAuth();
    if (user === null) return <Loader />;
    if (user === false) return <Navigate to="/login" replace />;
    if (user.must_change_password) return <Navigate to="/change-password" replace />;
    return <Navigate to={homePath(user.role)} replace />;
}
