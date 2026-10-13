import { vitalsToObjective } from "../VitalsPanel";
import { isGeneratedLine } from "../useSoapAutosave";

const v = { systolic_bp: 170, diastolic_bp: 75, heart_rate: 62, height_cm: 168, weight_kg: 78, bmi: 27.64 };
const FULL = "Sst: 170; Dst: 75; bpm: 62; Hgt: 168; Wgt Kg: 78; Wgt Lb: 171.96; Id W Kg: 67.74; Id W Lb: 149.34;";

test("↓ BP formatter — Sst, Dst, bpm (fields left of the button)", () => {
    expect(vitalsToObjective(v, "bp")).toBe("Sst: 170; Dst: 75; bpm: 62;");
    expect(vitalsToObjective({ systolic_bp: 177, diastolic_bp: 78, heart_rate: null }, "bp")).toBe("Sst: 177; Dst: 78;");
});
test("↓ △ formatter — Hgt cm, correct IWK/IWL, no BMI", () => expect(vitalsToObjective(v, "all")).toBe(FULL));
test("missing values omitted, order preserved", () => {
    expect(vitalsToObjective({ systolic_bp: 120, diastolic_bp: 80, heart_rate: 72, height_cm: null, weight_kg: null }, "all")).toBe("Sst: 120; Dst: 80; bpm: 72;");
    expect(vitalsToObjective({ systolic_bp: 120, diastolic_bp: null, heart_rate: null, height_cm: 168, weight_kg: null }, "all")).toBe("Hgt: 168; Id W Kg: 67.74; Id W Lb: 149.34;");
});
test("generated-line detection never matches physician text", () => {
    expect(isGeneratedLine(FULL)).toBe(true);
    expect(isGeneratedLine("Sst: 170; Dst: 75;")).toBe(true);
    expect(isGeneratedLine("Patient reports Sst: 170 at home")).toBe(false);
    expect(isGeneratedLine("Lungs clear.")).toBe(false);
});
