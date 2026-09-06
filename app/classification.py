from typing import Literal


ChallengeType = Literal["AMBAS_IA", "AMBAS_REALES", "MIXTA"]


def classify_challenge(is_ai_a: bool, is_ai_b: bool) -> ChallengeType:
    if is_ai_a and is_ai_b:
        return "AMBAS_IA"
    if not is_ai_a and not is_ai_b:
        return "AMBAS_REALES"
    return "MIXTA"
