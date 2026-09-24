// Shared VIen EMR brand mark — Ontario healthcare-network icon + wordmark.
// variant="dark" for dark backgrounds (light text), "light" for light backgrounds.
export function Logo({ variant = "light", iconClass = "h-8 w-8", textClass = "text-xl", showText = true, className = "" }) {
    const vien = variant === "dark" ? "text-white" : "text-[#1e50a0]";
    const emr = variant === "dark" ? "text-teal-300" : "text-[#17b3c4]";
    return (
        <div className={`flex items-center gap-2 ${className}`} data-testid="brand-logo">
            <img src="/vien-logo.png" alt="VIen EMR" className={`${iconClass} object-contain select-none`} draggable="false" />
            {showText && (
                <span className={`font-bold tracking-tight leading-none ${textClass}`}>
                    <span className={vien}>VIsita</span>
                    <span className={emr}> EMR</span>
                </span>
            )}
        </div>
    );
}
