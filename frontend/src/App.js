import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { RoleRoute, HomeRedirect } from "./components/RoleRoute";

import Landing from "./pages/Landing";
import PlatformAccess from "./pages/PlatformAccess";
import NetworkHome, { PersonProfile, OrgProfile } from "./network/NetworkHome";
import SignIn from "./pages/SignIn";
import Register from "./pages/Register";
import PartnerRegister from "./pages/PartnerRegister";
import ChangePassword from "./pages/ChangePassword";
import ForgotPassword from "./pages/ForgotPassword";
import Activate from "./pages/Activate";

import PortalLayout from "./portal/PortalLayout";
import PortalHome from "./portal/PortalHome";
import PortalAppointments from "./portal/PortalAppointments";
import PortalPrescriptions from "./portal/PortalPrescriptions";
import PortalReferrals from "./portal/PortalReferrals";
import PortalMessages from "./portal/PortalMessages";
import PortalMyRequests from "./portal/PortalMyRequests";
import PortalDocuments from "./portal/PortalDocuments";
import PortalInvoices from "./portal/PortalInvoices";
import PortalAccount from "./portal/PortalAccount";
import ManagedPeople from "./portal/ManagedPeople";
import PortalHealthCard from "./portal/PortalHealthCard";

import InternalLayout from "./internal/InternalLayout";
import Hub from "./internal/Hub";

// Physicians land on Patients; every other internal role keeps the Work Hub.
function InternalIndex() {
    const { user } = useAuth();
    const isPhysician = user?.role === "physician" || user?.base_role === "physician";
    return isPhysician ? <Navigate to="/internal/patients" replace /> : <Hub />;
}
import ProvisionDeveloper from "./internal/ProvisionDeveloper";
import RxQueue from "./internal/RxQueue";
import PharmacyIntake from "./internal/PharmacyIntake";
import SendPrescription from "./internal/SendPrescription";
import Professionals from "./internal/Professionals";
import AppointmentQueue from "./internal/AppointmentQueue";
import Calendar from "./internal/Calendar";
import ExamsResults from "./internal/ExamsResults";
import MessageQueue from "./internal/MessageQueue";
import TaskQueue from "./internal/TaskQueue";
import WorkHub from "./internal/WorkHub";
import Referrals from "./internal/Referrals";
import Verifications from "./internal/Verifications";
import Applications from "./internal/Applications";
import Settings from "./internal/Settings";
import ClinicProfile from "./internal/ClinicProfile";
import NotificationsPage from "./portal/NotificationCenter";
import DeveloperPortal from "./developer/DeveloperPortal";
import { SystemStatusProvider, ManagedNotice } from "./components/SystemStatus";
import { OutageBoundary } from "./components/OutageBoundary";
import { useLocation } from "react-router-dom";

// Public VIen pages (login, sign-in, registration, activation…) show the managed notice; authenticated shells get it via RoleRoute.
const PUBLIC_NOTICE_PATHS = ["/login", "/signin", "/register", "/platform-access", "/partners/register", "/change-password", "/forgot-password", "/activate"];
function PublicNotice() {
    const { pathname } = useLocation();
    return PUBLIC_NOTICE_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/")) ? <ManagedNotice /> : null;
}
import AuditCompliance from "./internal/AuditCompliance";
import Patients from "./internal/Patients";
import EncounterPage from "./encounter/EncounterPage";
import Organizations from "./internal/Organizations";
import Providers from "./internal/Providers";
import PrivateRequests from "./internal/PrivateRequests";
import Billing from "./internal/Billing";
import RegistrationQR from "./internal/RegistrationQR";
import PortalAccessRequests from "./internal/PortalAccessRequests";
import HealthCardUpdates from "./internal/HealthCardUpdates";

import PartnerLayout from "./partner/PartnerLayout";
import PartnerProfile from "./partner/PartnerProfile";

import PharmacyLayout from "./pharmacy/PharmacyLayout";
import PharmacyHub from "./pharmacy/PharmacyHub";
import PharmacyRx from "./pharmacy/PharmacyRx";
import PharmacyMessages from "./pharmacy/PharmacyMessages";
import PharmacyIncoming from "./pharmacy/PharmacyIncoming";
import PharmacyAccount from "./pharmacy/PharmacyAccount";

function App() {
    return (
        <AuthProvider>
            <SystemStatusProvider>
            <Toaster position="top-center" richColors />
            <BrowserRouter>
                <OutageBoundary>
                <PublicNotice />
                <Routes>
                    <Route path="/" element={<HomeRedirect />} />
                    <Route path="/login" element={<Landing />} />
                    <Route path="/platform-access" element={<PlatformAccess />} />
                    <Route path="/signin" element={<SignIn />} />
                    <Route path="/register" element={<Register />} />
                    <Route path="/register/:practiceSlug" element={<Register />} />
                    <Route path="/partners/register" element={<PartnerRegister />} />
                    <Route path="/change-password" element={<ChangePassword />} />
                    <Route path="/forgot-password" element={<ForgotPassword />} />
                    <Route path="/activate" element={<Activate />} />

                    <Route
                        path="/portal"
                        element={
                            <RoleRoute roles={["patient", "caregiver"]}>
                                <PortalLayout />
                            </RoleRoute>
                        }
                    >
                        <Route index element={<PortalHome />} />
                        <Route path="people" element={<ManagedPeople />} />
                        <Route path="manage/:patientId">
                            <Route index element={<PortalHome />} />
                            <Route path="appointments" element={<PortalAppointments />} />
                            <Route path="prescriptions" element={<PortalPrescriptions />} />
                            <Route path="documents" element={<PortalDocuments />} />
                            <Route path="requests" element={<PortalMyRequests />} />
                            <Route path="health-card" element={<PortalHealthCard />} />
                        </Route>
                        <Route path="appointments" element={<PortalAppointments />} />
                        <Route path="prescriptions" element={<PortalPrescriptions />} />
                        <Route path="referrals" element={<PortalReferrals />} />
                        <Route path="messages" element={<PortalMessages />} />
                        <Route path="imaging" element={<Navigate to="/portal/appointments" replace />} />
                        <Route path="bloodwork" element={<Navigate to="/portal/appointments" replace />} />
                        <Route path="requests" element={<PortalMyRequests />} />
                        <Route path="documents" element={<PortalDocuments />} />
                        <Route path="invoices" element={<PortalInvoices />} />
                        <Route path="notifications" element={<NotificationsPage />} />
                        <Route path="account" element={<PortalAccount />} />
                    </Route>

                    <Route path="/developer" element={<RoleRoute roles={["developer_ops", "operations_operator"]}><DeveloperPortal /></RoleRoute>} />
                    <Route path="/network" element={<RoleRoute roles={["network", "physician", "admin", "staff"]}><NetworkHome /></RoleRoute>} />
                    <Route path="/network/people/:id" element={<RoleRoute roles={["network", "physician", "admin", "staff"]}><PersonProfile /></RoleRoute>} />
                    <Route path="/network/orgs/:id" element={<RoleRoute roles={["network", "physician", "admin", "staff"]}><OrgProfile /></RoleRoute>} />
                    <Route
                        path="/internal/encounter"
                        element={
                            <RoleRoute roles={["physician"]} requireEncounter>
                                <EncounterPage />
                            </RoleRoute>
                        }
                    />
                    <Route
                        path="/internal/encounter/:visitId"
                        element={
                            <RoleRoute roles={["physician"]} requireEncounter>
                                <EncounterPage />
                            </RoleRoute>
                        }
                    />

                    <Route
                        path="/internal"
                        element={
                            <RoleRoute roles={["staff", "physician", "admin"]}>
                                <InternalLayout />
                            </RoleRoute>
                        }
                    >
                        <Route index element={<InternalIndex />} />
                        <Route path="patients" element={<Patients />} />
                        <Route path="rx" element={<RxQueue />} />
                        <Route path="pharmacy-intake" element={<PharmacyIntake />} />
                        <Route path="send-rx" element={<SendPrescription />} />
                        <Route path="appointments" element={<AppointmentQueue />} />
                        <Route path="private-requests" element={<PrivateRequests />} />
                        <Route path="billing" element={<Billing />} />
                        <Route path="calendar" element={<Calendar />} />
                        <Route path="exams" element={<ExamsResults />} />
                        <Route path="imaging" element={<Navigate to="/internal/exams" replace />} />
                        <Route path="bloodwork" element={<Navigate to="/internal/exams" replace />} />
                        <Route path="messages" element={<MessageQueue />} />
                        <Route path="work" element={<WorkHub />} />
                        <Route path="tasks" element={<TaskQueue />} /> {/* legacy intercom — kept for rollback during Preview */}
                        <Route path="referrals" element={<Referrals />} />
                        <Route path="verifications" element={<Verifications />} />
                        <Route path="applications" element={<Applications />} />
                        <Route path="registration-qr" element={<RegistrationQR />} />
                        <Route path="portal-access-requests" element={<PortalAccessRequests />} />
                        <Route path="health-card-updates" element={<HealthCardUpdates />} />
                        <Route path="organizations" element={<Organizations />} />
                        <Route path="providers" element={<Providers />} />
                        <Route path="professionals" element={<Professionals />} />
                        <Route path="settings" element={<Settings />} />
                        <Route path="clinic" element={<ClinicProfile />} />
                        <Route path="settings/audit" element={<AuditCompliance />} />
                        <Route path="system/provision-developer" element={<ProvisionDeveloper />} />
                    </Route>

                    <Route
                        path="/partner"
                        element={
                            <RoleRoute roles={["partner"]}>
                                <PartnerLayout />
                            </RoleRoute>
                        }
                    >
                        <Route index element={<PartnerProfile />} />
                    </Route>

                    <Route
                        path="/pharmacy"
                        element={
                            <RoleRoute roles={["pharmacy"]}>
                                <PharmacyLayout />
                            </RoleRoute>
                        }
                    >
                        <Route index element={<PharmacyHub />} />
                        <Route path="rx" element={<PharmacyRx />} />
                        <Route path="incoming" element={<PharmacyIncoming />} />
                        <Route path="messages" element={<PharmacyMessages />} />
                        <Route path="account" element={<PharmacyAccount />} />
                    </Route>
                </Routes>
                </OutageBoundary>
            </BrowserRouter>
            </SystemStatusProvider>
        </AuthProvider>
    );
}

export default App;
