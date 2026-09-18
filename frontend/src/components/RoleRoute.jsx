import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

function Loader() {
    return (
        <div className="min-h-screen flex items-center justify-center bg-visita-bg">
            <div className="text-visita-green font-plex font-semibold animate-pulse">Loading VIen EMR…</div>
        </div>
    );
}

export function RoleRoute({ roles, children }) {
    const { user } = useAuth();
    if (user === null) return <Loader />;
    if (user === false) return <Navigate to="/login" replace />;
    if (user.must_change_password) return <Navigate to="/change-password" replace />;
    if (roles && !roles.includes(user.role)) {
        return <Navigate to={user.role === "patient" ? "/portal" : "/internal"} replace />;
    }
    return children;
}

export function HomeRedirect() {
    const { user } = useAuth();
    if (user === null) return <Loader />;
    if (user === false) return <Navigate to="/login" replace />;
    if (user.must_change_password) return <Navigate to="/change-password" replace />;
    return <Navigate to={user.role === "patient" ? "/portal" : "/internal"} replace />;
}
