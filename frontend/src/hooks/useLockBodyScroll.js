import { useEffect } from "react";

// Locks background scrolling while a full-screen picker/modal is open (iOS-safe:
// fixes the body in place and restores the scroll position on close).
export function useLockBodyScroll(locked) {
    useEffect(() => {
        if (!locked) return undefined;
        const y = window.scrollY;
        const { style } = document.body;
        const prev = { position: style.position, top: style.top, width: style.width, overflow: style.overflow };
        style.position = "fixed"; style.top = `-${y}px`; style.width = "100%"; style.overflow = "hidden";
        return () => {
            style.position = prev.position; style.top = prev.top; style.width = prev.width; style.overflow = prev.overflow;
            window.scrollTo(0, y);
        };
    }, [locked]);
}
