from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GameDefinition:
    id: str
    title: str
    description: str
    icon: str
    status: str
    accent: str
    action_label: str
    duration: str
    difficulty: str
    category: str
    objective: str = ""
    how_to: str = ""
    icon_path: str = ""

    def to_dict(self):
        return asdict(self)


GAME_CATALOG = (
    GameDefinition(
        id="human-vs-ai",
        title="Human vs AI",
        description="Distingue fotografías reales de imágenes creadas por inteligencia artificial.",
        icon="◈",
        status="available",
        accent="blue",
        action_label="Jugar Human vs AI",
        duration="3 min",
        difficulty="Intermedio",
        category="IA",
    ),
    GameDefinition(
        id="spot-deepfake", title="Spot the Deepfake",
        description="Identifica señales de manipulación audiovisual avanzada.",
        icon="◉", status="coming-soon", accent="blue", action_label="Próximamente",
        duration="3 min", difficulty="Difícil", category="IA",
    ),
    GameDefinition(
        id="password-master", title="Password Master",
        description="Construye defensas de acceso resistentes y memorables.",
        icon="⌘", status="coming-soon", accent="orange", action_label="Próximamente",
        duration="2 min", difficulty="Intermedio", category="Ciberseguridad",
    ),
    GameDefinition(
        id="social-engineering", title="Social Engineering",
        description="Reconoce tácticas de manipulación antes de actuar.",
        icon="◇", status="coming-soon", accent="violet", action_label="Próximamente",
        duration="4 min", difficulty="Intermedio", category="Seguridad Humana",
    ),
    GameDefinition(
        id="coming-soon",
        title="Próximo desafío",
        description="Una nueva experiencia de AI Fest está en preparación.",
        icon="＋",
        status="coming-soon",
        accent="orange",
        action_label="Próximamente",
        duration="—",
        difficulty="—",
        category="Nueva misión",
    ),
)


def get_game_catalog():
    return [game.to_dict() for game in GAME_CATALOG]
