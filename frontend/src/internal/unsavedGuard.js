import { createContext, useContext } from "react";

// Shared guard so editable pages (e.g. Settings) can warn before leaving with unsaved changes.
// InternalLayout provides setGuard; pages register { dirty, save } where save() returns a Promise<boolean>.
export const UnsavedGuardContext = createContext({ setGuard: () => {} });
export const useUnsavedGuard = () => useContext(UnsavedGuardContext);
