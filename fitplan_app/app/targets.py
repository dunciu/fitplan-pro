"""Numeric nutrition/recovery guidance computed in code, so the agents quote fixed, conservative numbers
instead of inventing them. Minors and other restricted profiles get no numeric calorie/protein targets."""
from .planlint import is_endurance


def facts(p, screen) -> str:
    minor = p.age < 18
    lines = []
    if minor:
        lines += [
            "Nutrition: NO calorie counts, deficits or numeric macro targets for this person. Say: eat regular meals and snacks, "
            "include carbohydrate foods before and after training, protein at every meal, and plenty of fluids.",
            "Ask the person to check with a GP or registered dietitian for individual needs, including iron and vitamin D.",
            "Sleep: aim for 8-10 hours a night.",
        ]
    else:
        lines.append("Sleep: aim for 7-9 hours a night; protect the night before quality or long sessions.")
        if p.weight_kg:
            if is_endurance(p.goal):
                lo, hi = 1.4, 1.8
            else:
                lo, hi = 1.6, 2.2
            lines.append(f"Protein: {p.weight_kg * lo:.0f}-{p.weight_kg * hi:.0f} g/day ({lo}-{hi} g/kg), spread over 3-4 meals.")
            lines.append(f"Fluids: about {p.weight_kg * 5:.0f}-{p.weight_kg * 7:.0f} ml in the 2-4 hours before a long session, then drink to thirst.")
        else:
            lines.append("Protein: a palm-sized portion at each meal (no weight given, so no gram target).")
        lines.append("During sessions over 60-75 minutes: about 30-60 g carbohydrate per hour; shorter sessions need no extra fuel.")
        lines.append("Energy: no calorie number is given because maintenance varies a lot. If fat loss is the goal, aim for a modest "
                     "deficit of about 10-20% below maintenance and do not go lower without a dietitian.")
    lines.append("Warning signs to stop and see a doctor: chest pain, fainting, pain you can point to with one finger "
                 "(possible stress fracture), persistent fatigue, unexplained weight loss, or illness with fever.")
    return "FACTS TO USE EXACTLY (do not change or add numbers):\n" + "\n".join(f"- {l}" for l in lines)
