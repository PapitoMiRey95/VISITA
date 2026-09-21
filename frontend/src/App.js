import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider } from "./context/AuthContext";
import { RoleRoute, HomeRedirect } from "./components/RoleRoute";

import Landing from "./pages/Landing";
import SignIn from "./pages/SignIn";
import Register from "./pages/Register";
import ChangePassword from "./pages/ChangePassword";
import ForgotPassword from "./pages/ForgotPassword";

import PortalLayout from "./portal/PortalLayout";
import PortalHome from "./portal/PortalHome";
import PortalAppointments from "./portal/PortalAppointments";
import PortalPrescriptions from "./portal/PortalPrescriptions";
import PortalReferrals from "./portal/PortalReferrals";
import PortalMessages from "./portal/PortalMessages";
import PortalImaging from "./portal/PortalImaging";
import PortalBloodwork from "./portal/PortalBloodwork";
import PortalMyRequests from "./portal/PortalMyRequests";
import PortalAccount from "./portal/PortalAccount";

import InternalLayout from "./internal/InternalLayout";
import Hub from "./internal/Hub";
import RxQueue from "./internal/RxQueue";
import PharmacyIntake from "./internal/PharmacyIntake";
import AppointmentQueue from "./internal/AppointmentQueue";
import Calendar from "./internal/Calendar";
import ImagingQueue from "./internal/ImagingQueue";
import BloodworkQueue from "./internal/BloodworkQueue";
import MessageQueue from "./internal/MessageQueue";
import TaskQueue from "./internal/TaskQueue";
import Referrals from "./internal/Referrals";
import Verifications from "./internal/Verifications";
import Applications from "./internal/Applications";
import Settings from "./internal/Settings";

import PharmacyLayout from "./pharmacy/PharmacyLayout";
import PharmacyRx from "./pharmacy/PharmacyRx";
import PharmacyMessages from "./pharmacy/PharmacyMessages";
import PharmacyAccount from "./pharmacy/PharmacyAccount";

function App() {
    return (
        <AuthProvider>
            <Toaster position="top-center" richColors />
            <BrowserRouter>
                <Routes>
                    <Route path="/" element={<HomeRedirect />} />
                    <Route path="/login" element={<Landing />} />
                    <Route path="/signin" element={<SignIn />} />
                    <Route path="/register" element={<Register />} />
                    <Route path="/change-password" element={<ChangePassword />} />
                    <Route path="/forgot-password" element={<ForgotPassword />} />

                    <Route
                        path="/portal"
                        element={
                            <RoleRoute roles={["patient"]}>
                                <PortalLayout />
                            </RoleRoute>
                        }
                    >
                        <Route index element={<PortalHome />} />
                        <Route path="appointments" element={<PortalAppointments />} />
                        <Route path="prescriptions" element={<PortalPrescriptions />} />
                        <Route path="referrals" element={<PortalReferrals />} />
                        <Route path="messages" element={<PortalMessages />} />
                        <Route path="imaging" element={<PortalImaging />} />
                        <Route path="bloodwork" element={<PortalBloodwork />} />
                        <Route path="requests" element={<PortalMyRequests />} />
                        <Route path="account" element={<PortalAccount />} />
                    </Route>

                    <Route
                        path="/internal"
                        element={
                            <RoleRoute roles={["staff", "physician", "admin"]}>
                                <InternalLayout />
                            </RoleRoute>
                        }
                    >
                        <Route index element={<Hub />} />
                        <Route path="rx" element={<RxQueue />} />
                        <Route path="pharmacy-intake" element={<PharmacyIntake />} />
                        <Route path="appointments" element={<AppointmentQueue />} />
                        <Route path="calendar" element={<Calendar />} />
                        <Route path="imaging" element={<ImagingQueue />} />
                        <Route path="bloodwork" element={<BloodworkQueue />} />
                        <Route path="messages" element={<MessageQueue />} />
                        <Route path="tasks" element={<TaskQueue />} />
                        <Route path="referrals" element={<Referrals />} />
                        <Route path="verifications" element={<Verifications />} />
                        <Route path="applications" element={<Applications />} />
                        <Route path="settings" element={<Settings />} />
                    </Route>

                    <Route
                        path="/pharmacy"
                        element={
                            <RoleRoute roles={["pharmacy"]}>
                                <PharmacyLayout />
                            </RoleRoute>
                        }
                    >
                        <Route index element={<PharmacyRx />} />
                        <Route path="messages" element={<PharmacyMessages />} />
                        <Route path="account" element={<PharmacyAccount />} />
                    </Route>
                </Routes>
            </BrowserRouter>
        </AuthProvider>
    );
}

export default App;
