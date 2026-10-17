// Shared VIen brand mark — Ontario healthcare-network icon + wordmark.
// variant="dark" for dark backgrounds (light text), "light" for light backgrounds.
export function Logo({ variant = "light", iconClass = "h-8 w-8", textClass = "text-xl", showText = true, className = "" }) {
    // Vertical brand gradient: dark blue (top) -> turquoise (bottom), matching the logo mark.
    // Slightly brighter top on dark backgrounds to preserve contrast.
    const gradient = variant === "dark"
        ? "bg-gradient-to-b from-[#5aa0ff] to-[#20d0a8]"
        : "bg-gradient-to-b from-[#1e50a0] to-[#12bfa0]";
    return (
        <div className={`flex items-center gap-2 ${className}`} data-testid="brand-logo">
            <img src="/vien-logo.png" alt="VIen" className={`${iconClass} object-contain select-none`} draggable="false" />
            {showText && (
                <span className={`font-bold tracking-tight leading-tight bg-clip-text text-transparent ${gradient} ${textClass}`}>
                    VIen
                </span>
            )}
        </div>
    );
}
